import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _


class StoreAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label=_("Username"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        label=_("Password"), widget=forms.PasswordInput(attrs={"class": "form-control"})
    )


class RegistrationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class AccountDetailsForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        labels = {
            "first_name": _("First name"),
            "last_name": _("Last name"),
            "email": _("Email address"),
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }


class CheckoutForm(forms.Form):
    first_name = forms.CharField(
        max_length=50, label=_("First name"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    last_name = forms.CharField(
        max_length=50, label=_("Last name"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    email = forms.EmailField(
        label=_("Email address"), widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"})
    )
    phone_number = forms.CharField(
        max_length=25, label=_("Phone number"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_location = forms.CharField(
        max_length=250, label=_("Delivery location"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    payment_method = forms.ChoiceField(
        choices=[
            ("paystack", _("Paystack (Card, M-Pesa, Bank)")),
            ("mpesa", _("M-Pesa Direct STK Push")),
        ],
        initial="paystack",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        label=_("Payment method"),
    )

    def clean_phone_number(self):
        phone = re.sub(r"[\s()-]", "", self.cleaned_data["phone_number"])
        if phone.startswith("+"):
            phone = phone[1:]
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not re.fullmatch(r"254[17]\d{8}", phone):
            raise forms.ValidationError(
                _("Enter a valid phone number, such as 0712345678 or 254712345678.")
            )
        return phone

