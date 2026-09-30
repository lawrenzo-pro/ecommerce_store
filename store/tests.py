import json
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import CheckoutForm
from .models import Category, Order, Product


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
		self.assertContains(response, "KSh 250.00")

		self.client.post(reverse("cart"), {f"quantity_{self.product.pk}": "3"})
		self.assertEqual(self.client.session["cart"][str(self.product.pk)], 3)
		self.client.post(reverse("cart"), {"remove": str(self.product.pk)})
		self.assertEqual(self.client.session["cart"], {})

	def test_checkout_creates_order_and_requests_stk_push(self):
		self.set_cart(quantity=2)
		checkout_response = {
			"CheckoutRequestID": "ws_CO_test_123",
			"MerchantRequestID": "merchant_test_123",
		}
		with patch("store.views.initiate_stk_push", return_value=checkout_response) as push:
			response = self.client.post(
				reverse("checkout"),
				{
					"first_name": "Ada",
					"last_name": "Njeri",
					"phone_number": "0712 345 678",
					"delivery_location": "Kilimani",
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

	def test_checkout_rejects_invalid_phone_before_creating_order(self):
		self.set_cart()
		response = self.client.post(
			reverse("checkout"),
			{
				"first_name": "Ada",
				"last_name": "Njeri",
				"phone_number": "1234",
				"delivery_location": "Kilimani",
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Order.objects.count(), 0)
		self.assertContains(response, "Enter a Kenyan M-Pesa number")

	def test_checkout_rejects_fractional_shilling_total(self):
		self.product.price = "125.50"
		self.product.save(update_fields=["price"])
		self.set_cart()
		response = self.client.post(
			reverse("checkout"),
			{
				"first_name": "Ada",
				"last_name": "Njeri",
				"phone_number": "0712345678",
				"delivery_location": "Kilimani",
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Order.objects.count(), 0)
		self.assertContains(response, "M-Pesa payments must total a whole number")

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
					"phone_number": phone,
					"delivery_location": "Kilimani",
				}
			)
			self.assertTrue(form.is_valid(), form.errors)
			self.assertEqual(form.cleaned_data["phone_number"], normalized)


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
		payload = mock_post.call_args.kwargs["json"]
		self.assertEqual(payload["PhoneNumber"], "254712345678")
		self.assertEqual(payload["Amount"], 125)
