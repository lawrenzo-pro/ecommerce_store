from django.contrib import admin
from django.urls import include, path
from store.views import add_to_cart, cart, checkout, home, mpesa_callback, shop, single

urlpatterns = [
	path("", home, name="home"),
	path("cart/", cart, name="cart"),
	path("cart/add/", add_to_cart, name="add_to_cart"),
	path("checkout/", checkout, name="checkout"),
	path("payments/mpesa/callback/", mpesa_callback, name="mpesa_callback"),
	path("shop/", shop, name="shop"),
	path("single/", single, name="single"),
	path("admin/", admin.site.urls),
	path("i18n/", include("django.conf.urls.i18n")),
]
