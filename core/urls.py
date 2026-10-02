from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from store.forms import StoreAuthenticationForm
from store.views import (
	account,
	add_to_cart,
	cart,
	category_products,
	checkout,
	home,
	mpesa_callback,
	paystack_callback,
	product_detail,
	register,
	shop,
	single,
	toggle_wishlist,
)

urlpatterns = [
	path("", home, name="home"),
	path("cart/", cart, name="cart"),
	path("cart/add/", add_to_cart, name="add_to_cart"),
	path("checkout/", checkout, name="checkout"),
	path("payments/mpesa/callback/", mpesa_callback, name="mpesa_callback"),
	path("payments/paystack/callback/", paystack_callback, name="paystack_callback"),
	path("accounts/login/", LoginView.as_view(
		template_name="store/login.html", authentication_form=StoreAuthenticationForm,
		next_page="account",
	), name="login"),
	path("accounts/register/", register, name="register"),
	path("accounts/logout/", LogoutView.as_view(next_page="home"), name="logout"),
	path("account/", account, name="account"),
	path("shop/", shop, name="shop"),
	path("categories/<slug:slug>/", category_products, name="category"),
	path("products/<slug:slug>/", product_detail, name="product_detail"),
	path("products/<slug:slug>/wishlist/", toggle_wishlist, name="toggle_wishlist"),
	path("single/", single, name="single"),
	path("admin/", admin.site.urls),
	path("i18n/", include("django.conf.urls.i18n")),
]

if settings.DEBUG:
	urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
