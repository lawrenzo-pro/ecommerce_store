from django.contrib import admin
from django.urls import include, path
from store.views import home

urlpatterns = [
	path("", home, name="home"),
	path("admin/", admin.site.urls),
	path("i18n/", include("django.conf.urls.i18n")),
]
