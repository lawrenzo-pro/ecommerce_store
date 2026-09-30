from django.shortcuts import render


def home(request):
	return render(request, "store/index.html")


def cart(request):
	return render(request, "store/cart.html")


def checkout(request):
	return render(request, "store/checkout.html")


def shop(request):
	return render(request, "store/shop.html")


def single(request):
	return render(request, "store/single.html")
