import logging
from decimal import Decimal
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_API_BASE = "https://api.paystack.co"


class PaystackError(Exception):
    """Exception raised for Paystack API errors."""
    pass


def _get_headers():
    secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not secret_key:
        raise PaystackError("PAYSTACK_SECRET_KEY is not configured.")
    return {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }


def initialize_transaction(email, amount_in_kes, reference, callback_url, currency="KES"):
    """
    Initialize a Paystack transaction.
    `amount_in_kes` is converted to sub-units (cents / kobo, i.e. x100).
    """
    url = f"{PAYSTACK_API_BASE}/transaction/initialize"
    try:
        amount_subunit = int((Decimal(str(amount_in_kes)) * 100).to_integral_value())
    except (ValueError, TypeError) as exc:
        raise PaystackError(f"Invalid transaction amount: {amount_in_kes}") from exc

    payload = {
        "email": email,
        "amount": amount_subunit,
        "reference": str(reference),
        "callback_url": callback_url,
        "currency": currency,
        "metadata": {
            "order_id": str(reference),
            "custom_fields": [
                {"display_name": "Order ID", "variable_name": "order_id", "value": str(reference)}
            ],
        },
    }

    try:
        response = requests.post(url, json=payload, headers=_get_headers(), timeout=15)
        res_data = response.json()
    except Exception as exc:
        logger.exception("Failed to connect to Paystack API")
        raise PaystackError("Could not connect to payment gateway. Please try again.") from exc

    if not response.ok or not res_data.get("status"):
        error_msg = res_data.get("message", "Paystack initialization failed.")
        logger.error("Paystack transaction initialization failed: %s", error_msg)
        raise PaystackError(error_msg)

    data = res_data.get("data", {})
    return {
        "authorization_url": data.get("authorization_url"),
        "access_code": data.get("access_code"),
        "reference": data.get("reference"),
    }


def verify_transaction(reference):
    """
    Verify a Paystack transaction by reference.
    Returns the response JSON dictionary from Paystack.
    """
    url = f"{PAYSTACK_API_BASE}/transaction/verify/{reference}"
    try:
        response = requests.get(url, headers=_get_headers(), timeout=15)
        res_data = response.json()
    except Exception as exc:
        logger.exception("Failed to connect to Paystack API during verification")
        raise PaystackError("Could not verify transaction with payment gateway.") from exc

    if not response.ok:
        error_msg = res_data.get("message", "Paystack verification failed.")
        logger.error("Paystack transaction verification failed: %s", error_msg)
        raise PaystackError(error_msg)

    return res_data
