from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path
from store.forms import StoreAuthenticationForm
from store.views import account, add_to_cart, cart, checkout, home, mpesa_callback, register, shop, single

urlpatterns = [
	path("", home, name="home"),
	path("cart/", cart, name="cart"),
	path("cart/add/", add_to_cart, name="add_to_cart"),
	path("checkout/", checkout, name="checkout"),
	path("payments/mpesa/callback/", mpesa_callback, name="mpesa_callback"),
	path("accounts/login/", LoginView.as_view(
		template_name="store/login.html", authentication_form=StoreAuthenticationForm,
		next_page="account",
	), name="login"),
	path("accounts/register/", register, name="register"),
	path("accounts/logout/", LogoutView.as_view(next_page="home"), name="logout"),
	path("account/", account, name="account"),
	path("shop/", shop, name="shop"),
	path("single/", single, name="single"),
	path("admin/", admin.site.urls),
	path("i18n/", include("django.conf.urls.i18n")),
]
