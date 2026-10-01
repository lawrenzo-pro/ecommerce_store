from .models import Category


def store_categories(request):
	return {
		"store_categories": Category.objects.order_by("name")
	}
