import re

from django import forms
from django.utils.translation import gettext_lazy as _


class CheckoutForm(forms.Form):
    first_name = forms.CharField(
        max_length=50, label=_("First name"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    last_name = forms.CharField(
        max_length=50, label=_("Last name"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    phone_number = forms.CharField(
        max_length=25, label=_("M-Pesa phone number"), widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_location = forms.CharField(
        max_length=250, label=_("Delivery location"), widget=forms.TextInput(attrs={"class": "form-control"})
    )

    def clean_phone_number(self):
        phone = re.sub(r"[\s()-]", "", self.cleaned_data["phone_number"])
        if phone.startswith("+"):
            phone = phone[1:]
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not re.fullmatch(r"254[17]\d{8}", phone):
            raise forms.ValidationError(
                _("Enter a Kenyan M-Pesa number, such as 0712345678 or 254712345678.")
            )
        return phone
