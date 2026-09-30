import base64
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
from django.conf import settings


class MpesaError(Exception):
    pass


def initiate_stk_push(phone_number, amount, account_reference):
    environment = settings.MPESA_ENVIRONMENT
    if environment not in {"sandbox", "production"}:
        raise MpesaError("MPESA_ENVIRONMENT must be sandbox or production.")
    required = (
        settings.MPESA_CONSUMER_KEY,
        settings.MPESA_CONSUMER_SECRET,
        settings.MPESA_SHORTCODE,
        settings.MPESA_PASSKEY,
        settings.MPESA_CALLBACK_URL,
    )
    if not all(required):
        raise MpesaError("M-Pesa credentials and callback URL are not configured.")
    if not settings.MPESA_CALLBACK_URL.startswith("https://"):
        raise MpesaError("MPESA_CALLBACK_URL must be a publicly reachable HTTPS URL.")

    amount = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount < 1:
        raise MpesaError("M-Pesa requires a payment amount of at least KSh 1.")

    base_url = (
        "https://sandbox.safaricom.co.ke"
        if environment == "sandbox"
        else "https://api.safaricom.co.ke"
    )
    try:
        token_response = requests.get(
            f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
            auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
            timeout=settings.MPESA_TIMEOUT,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode()
        ).decode()
        response = requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "BusinessShortCode": settings.MPESA_SHORTCODE,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": settings.MPESA_SHORTCODE,
                "PhoneNumber": phone_number,
                "CallBackURL": settings.MPESA_CALLBACK_URL,
                "AccountReference": str(account_reference)[:12],
                "TransactionDesc": f"Order {account_reference}",
            },
            timeout=settings.MPESA_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ResponseCode") != "0" or not payload.get("CheckoutRequestID"):
            raise MpesaError(payload.get("ResponseDescription", "Daraja rejected the STK request."))
        return payload
    except MpesaError:
        raise
    except (requests.RequestException, KeyError, ValueError) as error:
        raise MpesaError("Could not communicate with the Daraja API.") from error
