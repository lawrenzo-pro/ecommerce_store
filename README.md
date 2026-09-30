# ecommerce_store

## M-Pesa setup

Install the project dependencies with `python -m pip install -r requirements.txt`.

The checkout uses Daraja STK Push in sandbox mode by default. Copy `.env.example` into your environment configuration and provide the Daraja consumer key, consumer secret, shortcode, passkey, and a publicly reachable HTTPS callback URL. The callback path is `/payments/mpesa/callback/`; a local development server needs an HTTPS tunnel for Daraja to reach it. Settings read process environment variables, so `.env` values must be exported or loaded by the environment that starts Django.

Run `python manage.py migrate` after updating the order model. The callback marks an order paid only when its checkout request ID, amount, phone number, and receipt match the stored order. Never expose Daraja credentials in source control.

## Languages

The English and Kiswahili selector uses Django's language cookie and the translation catalog in `locale/sw/LC_MESSAGES/django.po`. After changing translations, run `python manage.py compilemessages` (GNU gettext is required).

## Checks

Run the focused application tests with `python manage.py test`.