from django.db.models import Count, Q

from .models import Category


def store_categories(request):
	return {
		"store_categories": Category.objects.annotate(
			available_product_count=Count(
				"products",
				filter=Q(products__is_available=True, products__stock__gt=0),
			)
		).order_by("name")
	}
