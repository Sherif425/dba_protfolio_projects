"""
shop/views_slow.py — the "BEFORE" endpoints. Every one is a real-world mistake.

Keep these forever; the point of the lab is comparing them against views_fast.py
with measured numbers.
"""

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone

from .models import Order, Product, Review


def user_orders(request, user_id):
    """MISTAKE: sort on unindexed created_at → per-user sort of a big scan.
    At 5M orders this hits seconds for heavy (Pareto-head) users."""
    orders = Order.objects.filter(user_id=user_id).order_by("-created_at")[:50]
    return JsonResponse({"orders": [
        {"id": o.id, "status": o.status, "total": str(o.total),
         "created": o.created_at.isoformat()} for o in orders
    ]})


def review_feed(request):
    """MISTAKE: N+1 explosion. 100 reviews → 1 + 100 + 100 + 100 = 301 queries.
    Django lazily fetches r.user, r.product, r.product.category one by one."""
    reviews = Review.objects.order_by("-created_at")[:100]
    return JsonResponse({"reviews": [
        {"user": r.user.username,                       # +1 query each
         "product": r.product.name,                     # +1 query each
         "category": r.product.category.name,           # +1 query each
         "rating": r.rating} for r in reviews
    ]})


def search(request):
    """MISTAKE: icontains = LIKE '%term%' — no btree index can ever serve a
    leading-wildcard match, so this is a full scan of 1M descriptions."""
    term = request.GET.get("q", "wireless")
    products = Product.objects.filter(description__icontains=term)[:20]
    return JsonResponse({"results": [
        {"id": p.id, "name": p.name, "price": str(p.price)} for p in products
    ]})


def orders_page(request):
    """MISTAKE: deep OFFSET pagination. Page 45,000 forces the database to
    read and discard 900,000 rows before returning 20."""
    page = int(request.GET.get("page", 45000))
    orders = Order.objects.order_by("id")[page * 20:(page + 1) * 20]
    return JsonResponse({"orders": [
        {"id": o.id, "total": str(o.total)} for o in orders
    ]})


def top_customers(request):
    """MISTAKE: aggregate 5M rows on every request, filtered on unindexed
    created_at. A dashboard hitting this every 30s melts the server."""
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0,
                                         microsecond=0)
    rows = (Order.objects.filter(created_at__gte=month_start, status="delivered")
            .values("user__username")
            .annotate(spent=Sum("total"))
            .order_by("-spent")[:10])
    return JsonResponse({"top": list(rows)})
