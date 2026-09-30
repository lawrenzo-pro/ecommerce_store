from django.contrib import admin
from django.urls import include, path
from store.views import cart, checkout, home, shop, single

urlpatterns = [
	path("", home, name="home"),
	path("cart/", cart, name="cart"),
	path("checkout/", checkout, name="checkout"),
	path("shop/", shop, name="shop"),
	path("single/", single, name="single"),
	path("admin/", admin.site.urls),
	path("i18n/", include("django.conf.urls.i18n")),
]
