import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import CheckoutForm
from .models import Category, Order, Product, WishlistItem


@override_settings(ALLOWED_HOSTS=["localhost"])
class StorefrontWorkflowTests(TestCase):
	def setUp(self):
		self.client = Client(HTTP_HOST="localhost")
		self.category = Category.objects.create(name="Electronics", slug="electronics")
		self.product = Product.objects.create(
			category=self.category,
			name="Test phone",
			slug="test-phone",
			price="125.00",
			stock=5,
		)

	def set_cart(self, quantity=1):
		session = self.client.session
		session["cart"] = {str(self.product.pk): quantity}
		session.save()

	def test_cart_add_update_and_remove(self):
		response = self.client.post(
			reverse("add_to_cart"), {"product_id": self.product.pk, "quantity": 2}
		)
		self.assertRedirects(response, reverse("cart"), fetch_redirect_response=False)
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 2)

		response = self.client.get(reverse("cart"))
		self.assertContains(response, "Test phone")
		self.assertContains(response, "KES 250.00")

		self.client.post(reverse("cart"), {f"quantity_{self.product.pk}": "3"})
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 3)
		self.client.post(reverse("cart"), {"remove": str(self.product.pk)})
		self.assertEqual(self.client.session["cart"], {})

	def test_homepage_featured_product_uses_cart_endpoint(self):
		response = self.client.get(reverse("home"))
		self.assertEqual(response.context["featured_product"], self.product)
		self.assertContains(
			response,
			f'name="product_id" value="{self.product.pk}"',
		)
		self.client.post(
			reverse("add_to_cart"), {"product_id": self.product.pk, "quantity": 1}
		)
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 1)

	def test_homepage_search_matches_product_name_and_description(self):
		laptop = Product.objects.create(
			category=self.category,
			name="Laptop",
			slug="laptop",
			description="Portable workstation",
			price="750.00",
		)
		camera = Product.objects.create(
			category=self.category,
			name="Digital camera",
			slug="digital-camera",
			description="Compact device with optical zoom",
			price="300.00",
		)

		response = self.client.get(reverse("home"), {"q": "laptop"})
		self.assertEqual(response.context["query"], "laptop")
		self.assertContains(response, "Laptop")
		self.assertNotContains(response, "Test phone")
		self.assertNotContains(response, "Digital camera")
		self.assertContains(response, 'value="laptop"')
		self.assertEqual(list(response.context["products"]), [laptop])

		response = self.client.get(reverse("home"), {"q": "optical zoom"})
		self.assertEqual(list(response.context["products"]), [camera])
		self.assertContains(response, "optical zoom")

	def test_homepage_search_only_returns_available_in_stock_products(self):
		unavailable_product = Product.objects.create(
			category=self.category,
			name="Unavailable laptop",
			slug="unavailable-laptop",
			price="500.00",
			is_available=False,
		)
		out_of_stock_product = Product.objects.create(
			category=self.category,
			name="Out of stock laptop",
			slug="out-of-stock-laptop",
			price="500.00",
			stock=0,
		)

		response = self.client.get(reverse("home"), {"q": "laptop"})

		self.assertNotContains(response, unavailable_product.name)
		self.assertNotContains(response, out_of_stock_product.name)

	def test_categories_are_dynamic_and_filter_home_and_shop_catalogs(self):
		other_category = Category.objects.create(
			name="Hostel Living", slug="hostel-living"
		)
		other_product = Product.objects.create(
			category=other_category,
			name="Desk lamp",
			slug="desk-lamp",
			price="1200.00",
		)

		response = self.client.get(reverse("home"))
		self.assertContains(response, "Electronics")
		self.assertContains(response, "Hostel Living")
		self.assertContains(
			response, reverse("category", kwargs={"slug": other_category.slug})
		)
		self.assertNotContains(response, "(1)")

		for route_name in ("home", "shop"):
			with self.subTest(route=route_name):
				response = self.client.get(
					reverse(route_name), {"category": other_category.slug}
				)
				self.assertEqual(list(response.context["products"]), [other_product])
				self.assertContains(response, "Desk lamp")
				self.assertNotContains(response, "Test phone")

		category_response = self.client.get(
			reverse("category", kwargs={"slug": other_category.slug})
		)
		self.assertEqual(category_response.status_code, 200)
		self.assertEqual(category_response.context["category"], other_category)
		self.assertEqual(list(category_response.context["products"]), [other_product])

	def test_product_detail_page_displays_description(self):
		self.product.description = "A durable phone for everyday campus use."
		self.product.save(update_fields=["description"])

		response = self.client.get(
			reverse("product_detail", kwargs={"slug": self.product.slug})
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, self.product.name)
		self.assertContains(response, self.product.description)

	def test_homepage_features_random_products_from_the_visible_catalog(self):
		second_product = Product.objects.create(
			category=self.category,
			name="Test laptop",
			slug="test-laptop",
			price="800.00",
		)
		response = self.client.get(reverse("home"))
		featured_products = response.context["featured_products"]

		self.assertGreaterEqual(len(featured_products), 1)
		self.assertLessEqual(len(featured_products), 3)
		self.assertEqual(set(featured_products), {self.product, second_product})
		for product in featured_products:
			self.assertContains(
				response,
				reverse("product_detail", kwargs={"slug": product.slug}),
			)

	def test_homepage_shows_only_a_small_product_sample(self):
		for index in range(8):
			Product.objects.create(
				category=self.category,
				name=f"Additional product {index}",
				slug=f"additional-product-{index}",
				price="100.00",
			)

		home_response = self.client.get(reverse("home"))

		self.assertEqual(len(home_response.context["products"]), 4)
		self.assertNotContains(home_response, "View all products")

	def test_category_page_has_no_breadcrumb_or_page_banner(self):
		response = self.client.get(
			reverse("category", kwargs={"slug": self.category.slug})
		)

		self.assertNotContains(response, "breadcrumb")
		self.assertNotContains(response, "Pages")
		self.assertNotContains(response, 'class="container-fluid page-header')

	def test_category_page_omits_generic_service_promises(self):
		response = self.client.get(
			reverse("category", kwargs={"slug": self.category.slug})
		)

		self.assertNotContains(response, "Free Shipping")
		self.assertNotContains(response, "Free Return")
		self.assertNotContains(response, "Support 24/7")

	def test_catalog_uses_uploaded_product_image_url(self):
		from django.core.files.uploadedfile import SimpleUploadedFile

		product = Product.objects.create(
			category=self.category,
			name="Image test product",
			slug="image-test-product",
			price="199.00",
			image=SimpleUploadedFile(
				"product.png", b"test-image-content", content_type="image/png"
			),
		)
		self.addCleanup(product.image.delete, save=False)

		response = self.client.get(reverse("home"))

		self.assertContains(response, f'src="{product.image.url}"')
		self.assertContains(response, 'class="catalog-product-image')

	def test_shop_and_single_pages_use_database_product_for_add_button(self):
		for route_name in ("home", "shop", "single"):
			with self.subTest(route=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, "Test phone")
				self.assertContains(
					response, f'name="product_id" value="{self.product.pk}"'
				)
				self.assertNotContains(response, "Apple iPad Mini")

	def test_empty_catalog_does_not_render_demo_product_controls(self):
		self.product.delete()
		for route_name in ("home", "shop", "single"):
			with self.subTest(route=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, "No products available yet.")
				self.assertNotContains(response, "Apple iPad Mini")
				self.assertNotContains(response, "Add to cart")

	def test_storefront_pages_display_kes_only(self):
		self.set_cart()
		user = get_user_model().objects.create_user(username="kes-customer")
		self.client.force_login(user)
		Order.objects.create(
			user=user,
			first_name="KES",
			last_name="Customer",
			phone_number="254712345678",
			delivery_location="Nairobi",
			total_cost="125.00",
		)
		for route_name in ("home", "shop", "single", "cart", "account"):
			with self.subTest(route=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				content = response.content.decode()
				self.assertIn("KES", content)
				for old_currency in ("$", "USD", "Euro", "Dolar", "KSh"):
					self.assertNotIn(old_currency, content)

	def test_storefront_pages_share_base_layout_without_legacy_chrome(self):
		self.set_cart()
		response = self.client.get(reverse("home"))
		content = response.content.decode()
		header = content.split("</header>", 1)[0]
		self.assertIn(">Account</small>", header)
		self.assertIn("English", header)
		self.assertNotIn("<small>KES</small>", header)
		self.assertNotIn("All Categories", header)
		self.assertNotIn("All Categories", content)
		nav = content.split('class="container-fluid nav-bar', 1)[1].split(
			"{% block content %}", 1
		)[0]
		self.assertIn('aria-label="Toggle navigation"', nav)
		self.assertIn('class="fas fa-shopping-cart', nav)
		for footer_detail in (
			"University of Eldoret, Main Campus",
			"ayutide@iuiu.ac.ug",
			"+254 700 000 000",
			"mailto:",
			"tel:",
		):
			self.assertNotIn(footer_detail, content)
		self.assertNotContains(response, "My Dashboard")
		for route_name in (
			"home", "shop", "single", "cart", "login", "register"
		):
			with self.subTest(route=route_name):
				response = self.client.get(reverse(route_name))
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, "EldoMarket")
				self.assertNotContains(response, "123 Street New York")
				self.assertNotContains(response, "+0123 456 7890")
				self.assertNotContains(response, ">Single Page</a>")
				self.assertNotContains(response, "bestseller.html")
				self.assertNotContains(response, "404.html")
		self.assertRedirects(
			self.client.get(reverse("checkout")),
			reverse("cart"),
			fetch_redirect_response=False,
		)
		user = get_user_model().objects.create_user(username="base-layout-customer")
		self.client.force_login(user)
		response = self.client.get(reverse("account"))
		self.assertContains(response, "EldoMarket")
		self.assertNotContains(response, "Electro - Electronics Website Template")
		self.assertNotContains(response, "123 Street New York")

	def test_checkout_creates_order_and_requests_stk_push(self):
		self.set_cart(quantity=2)
		checkout_response = {
			"CheckoutRequestID": "ws_CO_test_123",
			"MerchantRequestID": "merchant_test_123",
		}
		with patch("store.views.initiate_stk_push", return_value=checkout_response) as push:
			response = self.client.post(
				reverse("cart"),
				{
					"action": "checkout",
					"first_name": "Ada",
					"last_name": "Njeri",
					"email": "ada@example.com",
					"phone_number": "0712 345 678",
					"delivery_location": "Kilimani",
					"payment_method": "mpesa",
				},
			)

		self.assertRedirects(response, reverse("cart"), fetch_redirect_response=False)
		order = Order.objects.get()
		self.assertEqual(order.phone_number, "254712345678")
		self.assertEqual(order.total_cost, Decimal("250.00"))
		self.assertEqual(order.payment_status, "processing")
		self.assertEqual(order.items.get().quantity, 2)
		self.assertTrue(push.called)
		self.assertNotIn("cart", self.client.session)

	def test_checkout_with_paystack_initializes_transaction_and_keeps_cart(self):
		self.set_cart(quantity=2)
		paystack_init_response = {
			"authorization_url": "https://checkout.paystack.com/test-auth-url",
			"access_code": "test_access_code",
			"reference": "ORD-1-20261002000000",
		}
		with patch("store.views.initialize_transaction", return_value=paystack_init_response) as paystack_mock:
			response = self.client.post(
				reverse("cart"),
				{
					"action": "checkout",
					"first_name": "Ada",
					"last_name": "Njeri",
					"email": "ada@example.com",
					"phone_number": "0712345678",
					"delivery_location": "Kilimani",
					"payment_method": "paystack",
				},
			)

		self.assertRedirects(response, "https://checkout.paystack.com/test-auth-url", fetch_redirect_response=False)
		order = Order.objects.get()
		self.assertEqual(order.email, "ada@example.com")
		self.assertEqual(order.payment_method, "paystack")
		self.assertTrue(order.paystack_reference.startswith(f"ORD-{order.pk}-"))
		self.assertEqual(order.payment_status, "pending")
		self.assertTrue(paystack_mock.called)
		# Crucial check: session cart MUST be kept intact when redirecting to Paystack
		self.assertIn("cart", self.client.session)
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 2)

	def test_paystack_callback_success_marks_paid_and_clears_cart(self):
		order = Order.objects.create(
			first_name="Ada",
			last_name="Njeri",
			email="ada@example.com",
			phone_number="254712345678",
			delivery_location="Kilimani",
			total_cost=Decimal("250.00"),
			payment_status="pending",
			payment_method="paystack",
			paystack_reference="ORD-TEST-123",
		)
		self.set_cart(quantity=2)
		verify_response = {
			"status": True,
			"data": {"status": "success", "reference": "ORD-TEST-123"},
		}
		with patch("store.views.verify_transaction", return_value=verify_response):
			response = self.client.get(
				reverse("paystack_callback"), {"reference": "ORD-TEST-123"}
			)

		self.assertRedirects(response, reverse("cart"), fetch_redirect_response=False)
		order.refresh_from_db()
		self.assertTrue(order.is_paid)
		self.assertEqual(order.payment_status, "paid")
		self.assertNotIn("cart", self.client.session)
		self.assertContains(self.client.get(reverse("cart")), "payment was successful")

	def test_paystack_callback_cancelled_marks_cancelled_and_keeps_cart(self):
		order = Order.objects.create(
			first_name="Ada",
			last_name="Njeri",
			email="ada@example.com",
			phone_number="254712345678",
			delivery_location="Kilimani",
			total_cost=Decimal("250.00"),
			payment_status="pending",
			payment_method="paystack",
			paystack_reference="ORD-TEST-456",
		)
		self.set_cart(quantity=2)
		verify_response = {
			"status": True,
			"data": {"status": "abandoned", "reference": "ORD-TEST-456"},
		}
		with patch("store.views.verify_transaction", return_value=verify_response):
			response = self.client.get(
				reverse("paystack_callback"), {"reference": "ORD-TEST-456"}
			)

		self.assertRedirects(response, reverse("cart"), fetch_redirect_response=False)
		order.refresh_from_db()
		self.assertFalse(order.is_paid)
		self.assertEqual(order.payment_status, "cancelled")
		# Crucial check: session cart MUST be preserved on cancellation
		self.assertIn("cart", self.client.session)
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 2)
		cart_response = self.client.get(reverse("cart"))
		self.assertContains(cart_response, "Your transaction was cancelled")
		self.assertContains(cart_response, "your cart items have been saved")

	def test_checkout_rejects_invalid_phone_before_creating_order(self):
		self.set_cart()
		response = self.client.post(
			reverse("cart"),
			{
				"action": "checkout",
				"first_name": "Ada",
				"last_name": "Njeri",
				"email": "ada@example.com",
				"phone_number": "1234",
				"delivery_location": "Kilimani",
				"payment_method": "paystack",
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Order.objects.count(), 0)
		self.assertContains(response, "Enter a valid phone number")

	def test_checkout_rejects_quantity_above_stock(self):
		self.set_cart()
		response = self.client.post(
			reverse("cart"),
			{
				"action": "checkout",
				f"quantity_{self.product.pk}": str(self.product.stock + 1),
				"first_name": "Ada",
				"last_name": "Njeri",
				"email": "ada@example.com",
				"phone_number": "0712345678",
				"delivery_location": "Kilimani",
				"payment_method": "paystack",
			},
		)
		self.assertRedirects(response, reverse("cart"), fetch_redirect_response=False)
		self.assertEqual(Order.objects.count(), 0)
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 1)
		self.assertContains(self.client.get(reverse("cart")), "Quantity exceeds available stock.")

	def test_checkout_rejects_fractional_shilling_total_for_mpesa(self):
		self.product.price = "125.50"
		self.product.save(update_fields=["price"])
		self.set_cart()
		response = self.client.post(
			reverse("cart"),
			{
				"action": "checkout",
				"first_name": "Ada",
				"last_name": "Njeri",
				"email": "ada@example.com",
				"phone_number": "0712345678",
				"delivery_location": "Kilimani",
				"payment_method": "mpesa",
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Order.objects.count(), 0)
		self.assertContains(response, "M-Pesa payments must total a whole number")

	def test_checkout_associates_signed_in_customer_with_order(self):
		user = get_user_model().objects.create_user(username="checkout-customer")
		self.client.force_login(user)
		self.set_cart()
		with patch(
			"store.views.initiate_stk_push",
			return_value={"CheckoutRequestID": "ws_CO_customer_123"},
		):
			self.client.post(
				reverse("cart"),
				{
					"action": "checkout",
					"first_name": "Ada",
					"last_name": "Njeri",
					"email": "ada@example.com",
					"phone_number": "0712345678",
					"delivery_location": "Kilimani",
					"payment_method": "mpesa",
				},
			)
		self.assertEqual(Order.objects.get().user, user)

	def test_successful_callback_marks_order_paid_once(self):
		order = Order.objects.create(
			first_name="Ada",
			last_name="Njeri",
			phone_number="254712345678",
			delivery_location="Kilimani",
			total_cost="125.00",
			payment_status="processing",
			checkout_request_id="ws_CO_callback_123",
		)
		callback = {
			"Body": {
				"stkCallback": {
					"CheckoutRequestID": order.checkout_request_id,
					"ResultCode": 0,
					"CallbackMetadata": {
						"Item": [
							{"Name": "Amount", "Value": 125},
							{"Name": "MpesaReceiptNumber", "Value": "QAB123XYZ"},
							{"Name": "PhoneNumber", "Value": 254712345678},
						]
					},
				}
			}
		}
		response = self.client.post(
			reverse("mpesa_callback"),
			data=json.dumps(callback),
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 200)
		order.refresh_from_db()
		self.assertTrue(order.is_paid)
		self.assertEqual(order.payment_status, "paid")
		self.assertEqual(order.mpesa_receipt_number, "QAB123XYZ")

		callback["Body"]["stkCallback"]["ResultCode"] = 1
		self.client.post(
			reverse("mpesa_callback"),
			data=json.dumps(callback),
			content_type="application/json",
		)
		order.refresh_from_db()
		self.assertTrue(order.is_paid)

	def test_language_selector_sets_swahili_cookie_and_catalog(self):
		response = self.client.post(
			reverse("set_language"), {"language": "sw", "next": reverse("cart")}
		)
		self.assertEqual(response.status_code, 302)
		self.assertEqual(self.client.cookies["django_language"].value, "sw")
		response = self.client.get(reverse("cart"))
		self.assertContains(response, 'lang="sw"')
		self.assertContains(response, "Kikapu chako hakina bidhaa.")


class CheckoutFormTests(TestCase):
	def test_accepts_local_and_international_kenyan_phone_formats(self):
		for phone, normalized in (
			("0712345678", "254712345678"),
			("+254 712 345 678", "254712345678"),
		):
			form = CheckoutForm(
				data={
					"first_name": "Ada",
					"last_name": "Njeri",
					"email": "ada@example.com",
					"phone_number": phone,
					"delivery_location": "Kilimani",
					"payment_method": "paystack",
				}
			)
			self.assertTrue(form.is_valid(), form.errors)
			self.assertEqual(form.cleaned_data["phone_number"], normalized)


@override_settings(ALLOWED_HOSTS=["localhost"])
class AccountDashboardTests(TestCase):
	def setUp(self):
		self.client = Client(HTTP_HOST="localhost")
		self.user_model = get_user_model()
		self.user = self.user_model.objects.create_user(
			username="account-holder", password="R8m$eZ4qV!7pL2x"
		)

	def test_guest_menu_offers_login_and_registration(self):
		response = self.client.get(reverse("home"))
		self.assertContains(response, reverse("login"))
		self.assertContains(response, reverse("register"))

	def test_authenticated_menu_and_account_are_localized(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse("home"))
		self.assertContains(response, reverse("account"))
		self.assertContains(response, reverse("logout"))
		self.client.post(
			reverse("set_language"), {"language": "sw", "next": reverse("account")}
		)
		response = self.client.get(reverse("account"))
		self.assertContains(response, 'lang="sw"')
		self.assertContains(response, "Akaunti Yangu")

	def test_registration_logs_in_and_opens_dashboard(self):
		response = self.client.post(
			reverse("register"),
			{
				"username": "new-customer",
				"password1": "R8m$eZ4qV!7pL2x",
				"password2": "R8m$eZ4qV!7pL2x",
			},
		)
		self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
		self.assertEqual(self.client.get(reverse("account")).status_code, 200)
		self.assertContains(self.client.get(reverse("home")), reverse("logout"))

	def test_login_redirects_to_dashboard_and_logout_requires_post(self):
		response = self.client.post(
			reverse("login"),
			{"username": "account-holder", "password": "R8m$eZ4qV!7pL2x"},
		)
		self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
		self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
		response = self.client.post(reverse("logout"))
		self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
		self.assertNotIn("_auth_user_id", self.client.session)

	def test_dashboard_updates_profile_and_only_shows_own_orders(self):
		other_user = self.user_model.objects.create_user(username="other-customer")
		own_order = Order.objects.create(
			user=self.user,
			first_name="Account",
			last_name="Holder",
			phone_number="254712345678",
			delivery_location="Nairobi",
			total_cost="500.00",
		)
		other_order = Order.objects.create(
			user=other_user,
			first_name="Other",
			last_name="Customer",
			phone_number="254712345678",
			delivery_location="Nairobi",
			total_cost="250.00",
		)
		self.client.force_login(self.user)
		response = self.client.get(reverse("account"))
		self.assertContains(response, f"#{own_order.pk}")
		self.assertNotContains(response, f"#{other_order.pk}")

		response = self.client.post(
			reverse("account"),
			{"first_name": "Amina", "last_name": "Wanjiku", "email": "amina@example.com"},
		)
		self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
		self.user.refresh_from_db()
		self.assertEqual(self.user.first_name, "Amina")

	def test_wishlist_add_remove_and_account_listing_are_user_specific(self):
		category = Category.objects.create(name="Wishlist Category", slug="wishlist")
		product = Product.objects.create(
			category=category,
			name="Wishlist phone",
			slug="wishlist-phone",
			price="225.00",
		)
		other_user = self.user_model.objects.create_user(username="other-wishlist-user")
		self.client.force_login(self.user)

		response = self.client.post(
			reverse("toggle_wishlist", kwargs={"slug": product.slug}),
			{"action": "add", "next": reverse("account")},
		)
		self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
		self.assertTrue(
			WishlistItem.objects.filter(user=self.user, product=product).exists()
		)
		self.client.post(
			reverse("toggle_wishlist", kwargs={"slug": product.slug}),
			{"action": "add", "next": reverse("account")},
		)
		self.assertEqual(
			WishlistItem.objects.filter(user=self.user, product=product).count(), 1
		)
		account_response = self.client.get(reverse("account"))
		self.assertContains(account_response, product.name)
		self.assertEqual(
			list(account_response.context["wishlist_items"].values_list("product", flat=True)),
			[product.pk],
		)
		self.assertFalse(
			WishlistItem.objects.filter(user=other_user, product=product).exists()
		)

		self.client.post(
			reverse("toggle_wishlist", kwargs={"slug": product.slug}),
			{"action": "remove", "next": reverse("account")},
		)
		self.assertFalse(
			WishlistItem.objects.filter(user=self.user, product=product).exists()
		)


@override_settings(
	MPESA_ENVIRONMENT="sandbox",
	MPESA_CONSUMER_KEY="test-key",
	MPESA_CONSUMER_SECRET="test-secret",
	MPESA_SHORTCODE="174379",
	MPESA_PASSKEY="test-passkey",
	MPESA_CALLBACK_URL="https://example.test/payments/mpesa/callback/",
)
class MpesaClientTests(TestCase):
	@patch("store.services.mpesa.requests.post")
	@patch("store.services.mpesa.requests.get")
	def test_stk_push_uses_normalized_phone_and_whole_shilling_amount(
		self, mock_get, mock_post
	):
		from .services.mpesa import initiate_stk_push

		mock_get.return_value.json.return_value = {"access_token": "test-token"}
		mock_post.return_value.json.return_value = {
			"ResponseCode": "0",
			"CheckoutRequestID": "ws_CO_test_456",
			"MerchantRequestID": "merchant_test_456",
		}

		result = initiate_stk_push("254712345678", "125.00", "42")

		self.assertEqual(result["CheckoutRequestID"], "ws_CO_test_456")
		self.assertEqual(
			mock_post.call_args.kwargs["headers"]["Authorization"],
			"Bearer test-token",
		)
		payload = mock_post.call_args.kwargs["json"]
		self.assertEqual(payload["PhoneNumber"], "254712345678")
		self.assertEqual(payload["Amount"], 125)
