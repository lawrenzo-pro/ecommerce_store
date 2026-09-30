import json
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import AccountDetailsForm, CheckoutForm, RegistrationForm
from .models import Order, OrderItem, Product
from .services.mpesa import MpesaError, initiate_stk_push

logger = logging.getLogger(__name__)
CART_SESSION_KEY = "cart"


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
	products = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category").order_by("-created")
	return render(
		request,
		"store/index.html",
		{"products": products, "featured_product": products.first()},
	)


def cart(request):
	if request.method == "POST":
		cart_data = request.session.get(CART_SESSION_KEY, {})
		remove_id = request.POST.get("remove")
		if remove_id:
			cart_data.pop(remove_id, None)
		else:
			for product_id in list(cart_data):
				value = request.POST.get(f"quantity_{product_id}")
				if value is None:
					continue
				try:
					quantity = int(value)
					product = Product.objects.get(pk=product_id, is_available=True)
				except (TypeError, ValueError, Product.DoesNotExist):
					cart_data.pop(product_id, None)
					continue
				if quantity < 1:
					cart_data.pop(product_id, None)
				elif quantity <= product.stock:
					cart_data[product_id] = quantity
				else:
					messages.error(request, _("Quantity exceeds available stock."))
		request.session[CART_SESSION_KEY] = cart_data
		return redirect("cart")
	items, subtotal = _cart_summary(request)
	return render(request, "store/cart.html", {"cart_items": items, "subtotal": subtotal})


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
	items, subtotal = _cart_summary(request)
	if not items:
		messages.info(request, _("Your cart is empty."))
		return redirect("cart")
	form = CheckoutForm(request.POST or None)
	if request.method == "POST" and form.is_valid():
		if subtotal != subtotal.to_integral_value():
			form.add_error(None, _("M-Pesa payments must total a whole number of Kenya shillings."))
			return render(request, "store/checkout.html", {"form": form, "cart_items": items, "subtotal": subtotal})
		with transaction.atomic():
			order = Order.objects.create(
				user=request.user if request.user.is_authenticated else None,
				first_name=form.cleaned_data["first_name"],
				last_name=form.cleaned_data["last_name"],
				phone_number=form.cleaned_data["phone_number"],
				delivery_location=form.cleaned_data["delivery_location"],
				total_cost=subtotal,
			)
			OrderItem.objects.bulk_create([
				OrderItem(order=order, product=item["product"], price=item["product"].price, quantity=item["quantity"])
				for item in items
			])
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
		return redirect("checkout")
	return render(request, "store/checkout.html", {"form": form, "cart_items": items, "subtotal": subtotal})


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
	return render(request, "store/account.html", {"form": form, "orders": orders})


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
	products = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category").order_by("-created")
	return render(request, "store/shop.html", {"products": products})


def single(request):
	product = Product.objects.filter(
		is_available=True, stock__gt=0
	).select_related("category").order_by("-created").first()
	return render(request, "store/single.html", {"featured_product": product})
