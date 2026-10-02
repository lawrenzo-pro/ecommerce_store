import json
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import AccountDetailsForm, CheckoutForm, RegistrationForm
from .models import Category, Order, OrderItem, Product, WishlistItem
from .services.mpesa import MpesaError, initiate_stk_push
from .services.paystack import PaystackError, initialize_transaction, verify_transaction

logger = logging.getLogger(__name__)
CART_SESSION_KEY = "cart"


def _wishlisted_product_ids(user, products):
	if not user.is_authenticated:
		return set()
	return set(
		WishlistItem.objects.filter(
			user=user, product__in=products
		).values_list("product_id", flat=True)
	)


def _cart_summary(request):
	cart_data = request.session.get(CART_SESSION_KEY, {})
	products = Product.objects.filter(
		pk__in=cart_data.keys(), is_available=True
	).select_related("category")
	items = []
	valid_cart = {}
	subtotal = Decimal("0.00")
	for product in products:
		try:
			quantity = int(cart_data.get(str(product.pk), 0))
		except (TypeError, ValueError):
			continue
		if quantity < 1 or product.stock < 1:
			continue
		quantity = min(quantity, product.stock)
		line_total = product.price * quantity
		items.append({"product": product, "quantity": quantity, "line_total": line_total})
		valid_cart[str(product.pk)] = quantity
		subtotal += line_total
	if valid_cart != cart_data:
		request.session[CART_SESSION_KEY] = valid_cart
	return items, subtotal


def home(request):
	query = request.GET.get("q", "").strip()
	category_slug = request.GET.get("category", "").strip()
	products = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category")
	if query:
		products = products.filter(
			Q(name__icontains=query) | Q(description__icontains=query)
		)
	if category_slug:
		products = products.filter(category__slug=category_slug)
	products = products.order_by("-created")
	featured_products = list(products.order_by("?")[:3])
	wishlisted_product_ids = _wishlisted_product_ids(request.user, products)
	homepage_products = list(products.order_by("?")[:4])
	return render(
		request,
		"store/index.html",
		{
			"products": homepage_products,
			"featured_products": featured_products,
			"featured_product": featured_products[0] if featured_products else None,
			"wishlisted_product_ids": wishlisted_product_ids,
			"query": query,
			"selected_category": category_slug,
		},
	)


def cart(request):
	if request.method == "POST":
		cart_data = request.session.get(CART_SESSION_KEY, {})
		remove_id = request.POST.get("remove")
		quantity_error = False
		if remove_id:
			cart_data.pop(remove_id, None)
		else:
			for product_id in list(cart_data):
				value = request.POST.get(f"quantity_{product_id}")
				if value is None:
					continue
				try:
					quantity = int(value)
				except (TypeError, ValueError):
					quantity_error = True
					messages.error(request, _("Enter a valid product quantity."))
					continue
				try:
					product = Product.objects.get(pk=product_id, is_available=True)
				except Product.DoesNotExist:
					cart_data.pop(product_id, None)
					quantity_error = True
					messages.error(request, _("A product in your cart is no longer available."))
					continue
				if quantity < 1:
					if request.POST.get("action") == "checkout":
						quantity_error = True
						messages.error(request, _("Product quantities must be greater than zero."))
					else:
						cart_data.pop(product_id, None)
				elif quantity <= product.stock:
					cart_data[product_id] = quantity
				else:
					quantity_error = True
					messages.error(request, _("Quantity exceeds available stock."))
		request.session[CART_SESSION_KEY] = cart_data
		if request.POST.get("action") == "checkout":
			if quantity_error:
				return redirect("cart")
			items, subtotal = _cart_summary(request)
			if not items:
				messages.info(request, _("Your cart is empty."))
				return redirect("cart")
			form = CheckoutForm(request.POST)
			return _complete_checkout(request, items, subtotal, form)
		return redirect("cart")
	items, subtotal = _cart_summary(request)
	return render(
		request,
		"store/cart.html",
		{"cart_items": items, "subtotal": subtotal, "form": CheckoutForm()},
	)


def _complete_checkout(request, items, subtotal, form):
	if not form.is_valid():
		return render(
			request,
			"store/cart.html",
			{"form": form, "cart_items": items, "subtotal": subtotal},
		)
	payment_method = form.cleaned_data.get("payment_method", "paystack")
	if payment_method == "mpesa" and subtotal != subtotal.to_integral_value():
		form.add_error(None, _("M-Pesa payments must total a whole number of Kenya shillings."))
		return render(
			request,
			"store/cart.html",
			{"form": form, "cart_items": items, "subtotal": subtotal},
		)

	with transaction.atomic():
		order = Order.objects.create(
			user=request.user if request.user.is_authenticated else None,
			first_name=form.cleaned_data["first_name"],
			last_name=form.cleaned_data["last_name"],
			email=form.cleaned_data["email"],
			phone_number=form.cleaned_data["phone_number"],
			delivery_location=form.cleaned_data["delivery_location"],
			total_cost=subtotal,
			payment_method=payment_method,
		)
		OrderItem.objects.bulk_create([
			OrderItem(order=order, product=item["product"], price=item["product"].price, quantity=item["quantity"])
			for item in items
		])

	if payment_method == "paystack":
		callback_url = request.build_absolute_uri(reverse("paystack_callback"))
		reference = f"ORD-{order.pk}-{order.created.strftime('%Y%m%d%H%M%S')}"
		try:
			paystack_res = initialize_transaction(
				email=order.email,
				amount_in_kes=order.total_cost,
				reference=reference,
				callback_url=callback_url,
			)
		except PaystackError as exc:
			logger.exception("Paystack initialization failed for order %s", order.pk)
			messages.error(
				request,
				_("Could not initiate Paystack transaction: %(error)s") % {"error": str(exc)},
			)
			return redirect("cart")

		order.paystack_reference = reference
		order.payment_status = "pending"
		order.save(update_fields=["paystack_reference", "payment_status"])
		# Note: Session cart is kept intact here until payment verification succeeds
		return redirect(paystack_res["authorization_url"])

	try:
		response = initiate_stk_push(
			order.phone_number, order.total_cost, str(order.pk)
		)
	except MpesaError:
		logger.exception("M-Pesa STK Push failed for order %s", order.pk)
		messages.error(
			request,
			_("We could not start the M-Pesa payment. Your order %(order_id)s was saved; please try again or contact support.")
			% {"order_id": order.pk},
		)
	else:
		order.checkout_request_id = response["CheckoutRequestID"]
		order.merchant_request_id = response.get("MerchantRequestID", "")
		order.payment_status = "processing"
		order.save(update_fields=["checkout_request_id", "merchant_request_id", "payment_status"])
		request.session.pop(CART_SESSION_KEY, None)
		messages.success(request, _("Payment request sent. Enter your M-Pesa PIN on your phone to complete order %(order_id)s.") % {"order_id": order.pk})
	return redirect("cart")


def paystack_callback(request):
	reference = request.GET.get("reference") or request.GET.get("trxref") or request.POST.get("reference")
	if not reference:
		messages.error(request, _("No transaction reference provided."))
		return redirect("cart")

	order = Order.objects.filter(paystack_reference=reference).first()
	if not order:
		messages.error(request, _("Order not found for transaction reference."))
		return redirect("cart")

	if order.is_paid:
		messages.success(
			request,
			_("Payment completed successfully for order #%(order_id)s!") % {"order_id": order.pk},
		)
		return redirect("cart")

	try:
		verification = verify_transaction(reference)
		data = verification.get("data", {})
		status = data.get("status")
	except PaystackError as exc:
		logger.exception("Verification failed for Paystack reference %s", reference)
		messages.error(
			request,
			_("Could not verify transaction: %(error)s") % {"error": str(exc)},
		)
		return redirect("cart")

	if status == "success":
		order.is_paid = True
		order.payment_status = "paid"
		order.save(update_fields=["is_paid", "payment_status"])
		request.session.pop(CART_SESSION_KEY, None)
		messages.success(
			request,
			_("Thank you! Your payment was successful and order #%(order_id)s has been confirmed.")
			% {"order_id": order.pk},
		)
	else:
		order.payment_status = "cancelled" if status in ("abandoned", "cancelled") else "failed"
		order.save(update_fields=["payment_status"])
		# DO NOT clear cart! Keep cart intact in session.
		messages.info(
			request,
			_("Your transaction was cancelled. No charges were made, and your cart items have been saved so you can try again whenever you're ready."),
		)

	return redirect("cart")



@require_POST
def add_to_cart(request):
	try:
		product = Product.objects.get(pk=request.POST.get("product_id"), is_available=True)
		quantity = int(request.POST.get("quantity", "1"))
	except (Product.DoesNotExist, TypeError, ValueError):
		messages.error(request, _("That product is not available."))
		return redirect("home")
	if quantity < 1:
		messages.error(request, _("Choose a quantity greater than zero."))
		return redirect("home")
	cart_data = request.session.get(CART_SESSION_KEY, {})
	new_quantity = int(cart_data.get(str(product.pk), 0)) + quantity
	if new_quantity > product.stock:
		messages.error(request, _("Quantity exceeds available stock."))
		return redirect("home")
	cart_data[str(product.pk)] = new_quantity
	request.session[CART_SESSION_KEY] = cart_data
	messages.success(request, _("Product added to your cart."))
	return redirect("cart")


def checkout(request):
	return redirect("cart")


def register(request):
	if request.user.is_authenticated:
		return redirect("account")
	form = RegistrationForm(request.POST or None)
	if request.method == "POST" and form.is_valid():
		user = form.save()
		login(request, user)
		messages.success(request, _("Your account has been created."))
		return redirect("account")
	return render(request, "store/register.html", {"form": form})


@login_required
def account(request):
	form = AccountDetailsForm(request.POST or None, instance=request.user)
	if request.method == "POST" and form.is_valid():
		form.save()
		messages.success(request, _("Your account details have been updated."))
		return redirect("account")
	orders = request.user.orders.prefetch_related("items__product").order_by("-created")
	wishlist_items = request.user.wishlist_items.select_related(
		"product", "product__category"
	)
	return render(
		request,
		"store/account.html",
		{"form": form, "orders": orders, "wishlist_items": wishlist_items},
	)


@require_POST
def toggle_wishlist(request, slug):
	if not request.user.is_authenticated:
		detail_url = reverse("product_detail", kwargs={"slug": slug})
		return redirect_to_login(detail_url)
	product = get_object_or_404(Product, slug=slug)
	action = request.POST.get("action", "add")
	if action == "remove":
		WishlistItem.objects.filter(user=request.user, product=product).delete()
		messages.info(request, _("Product removed from your wishlist."))
	elif action == "add":
		if product.is_available:
			WishlistItem.objects.get_or_create(user=request.user, product=product)
			messages.success(request, _("Product added to your wishlist."))
		else:
			messages.error(request, _("This product is no longer available."))
	else:
		messages.error(request, _("Invalid wishlist action."))

	next_url = request.POST.get("next", "")
	if next_url and url_has_allowed_host_and_scheme(
		next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
	):
		return redirect(next_url)
	return redirect("product_detail", slug=product.slug)


@csrf_exempt
@require_POST
def mpesa_callback(request):
	try:
		callback = json.loads(request.body)["Body"]["stkCallback"]
		checkout_id = callback["CheckoutRequestID"]
		result_code = int(callback["ResultCode"])
	except (KeyError, TypeError, ValueError, json.JSONDecodeError):
		return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid callback"}, status=400)
	with transaction.atomic():
		order = Order.objects.select_for_update().filter(checkout_request_id=checkout_id).first()
		if order and not order.is_paid:
			if result_code == 0:
				metadata = callback.get("CallbackMetadata", {}).get("Item", [])
				values = {item.get("Name"): item.get("Value") for item in metadata}
				expected_amount = int(order.total_cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
				if (
					values.get("Amount") != expected_amount
					or str(values.get("PhoneNumber", "")) != order.phone_number
					or not values.get("MpesaReceiptNumber")
				):
					logger.warning("M-Pesa callback details did not match order %s", order.pk)
					return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
				order.is_paid = True
				order.payment_status = "paid"
				order.mpesa_receipt_number = str(values["MpesaReceiptNumber"])
			else:
				order.payment_status = "failed"
			order.save(update_fields=["is_paid", "payment_status", "mpesa_receipt_number"])
	return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


def shop(request):
	query = request.GET.get("q", "").strip()
	category_slug = request.GET.get("category", "").strip()
	products = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category")
	if query:
		products = products.filter(
			Q(name__icontains=query) | Q(description__icontains=query)
		)
	if category_slug:
		products = products.filter(category__slug=category_slug)
	products = products.order_by("-created")
	wishlisted_product_ids = _wishlisted_product_ids(request.user, products)
	return render(
		request,
		"store/shop.html",
		{
			"products": products,
			"query": query,
			"selected_category": category_slug,
			"wishlisted_product_ids": wishlisted_product_ids,
		},
	)


def category_products(request, slug):
	category = get_object_or_404(Category, slug=slug)
	query = request.GET.get("q", "").strip()
	products = Product.objects.filter(
		category=category, is_available=True, stock__gt=0
	).select_related("category")
	if query:
		products = products.filter(
			Q(name__icontains=query) | Q(description__icontains=query)
		)
	products = products.order_by("-created")
	wishlisted_product_ids = _wishlisted_product_ids(request.user, products)
	return render(
		request,
		"store/shop.html",
		{
			"products": products,
			"query": query,
			"selected_category": category.slug,
			"category": category,
			"wishlisted_product_ids": wishlisted_product_ids,
		},
	)


def product_detail(request, slug):
	product = get_object_or_404(
		Product.objects.select_related("category"),
		slug=slug,
		is_available=True,
	)
	is_wishlisted = request.user.is_authenticated and WishlistItem.objects.filter(
		user=request.user, product=product
	).exists()
	return render(
		request,
		"store/product_detail.html",
		{"product": product, "is_wishlisted": is_wishlisted},
	)


def single(request):
	product = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category").order_by("-created").first()
	return render(request, "store/single.html", {"featured_product": product})
