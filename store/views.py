from django.shortcuts import render
from .models import Product


def home(request):
	products = Product.objects.filter(is_available=True).select_related("category").order_by("-created")
	return render(request, "store/index.html", {"products": products})


def cart(request):
	return render(request, "store/cart.html")


def checkout(request):
	return render(request, "store/checkout.html")


def shop(request):
	return render(request, "store/shop.html")


def single(request):
	return render(request, "store/single.html")
