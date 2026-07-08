"""
shop/views_fast.py — the "AFTER" endpoints.

Each function's docstring names the fix. The index-dependent ones need
sql/indexes_after.sql applied (or the Meta.indexes in models.py uncommented +
migrated) before they show their full speedup — that's the point: same query
shape, different physical design.
"""

from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db import connection
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone

from .models import Order, Product, Review


def user_orders(request, user_id):
    """FIX: composite index (user_id, created_at DESC) — the ORDER BY is served
    directly from index order, LIMIT 50 stops after 50 index entries.
    Bonus: .only() trims the row to what we serialize."""
    orders = (Order.objects.filter(user_id=user_id)
              .order_by("-created_at")
              .only("id", "status", "total", "created_at")[:50])
    return JsonResponse({"orders": [
        {"id": o.id, "status": o.status, "total": str(o.total),
         "created": o.created_at.isoformat()} for o in orders
    ]})


def review_feed(request):
    """FIX: select_related follows the FK chain in ONE joined query.
    301 queries → 1. No index needed — this one is pure ORM discipline."""
    reviews = (Review.objects
               .select_related("user", "product__category")
               .order_by("-created_at")[:100])
    return JsonResponse({"reviews": [
        {"user": r.user.username,
         "product": r.product.name,
         "category": r.product.category.name,
         "rating": r.rating} for r in reviews
    ]})


def search(request):
    """FIX: real full-text search.
    PostgreSQL: tsvector + GIN index. MySQL: FULLTEXT ... MATCH AGAINST.
    Same endpoint, engine-appropriate implementation — a nice case-study moment."""
    term = request.GET.get("q", "wireless")
    if connection.vendor == "postgresql":
        qs = (Product.objects
              .annotate(sv=SearchVector("description"))
              .filter(sv=SearchQuery(term))[:20])
        # Production note: precompute the vector into a SearchVectorField column
        # with a GIN index (see models.py comments) — annotating per-query still
        # scans. The indexed version is the real "after" number.
        results = [{"id": p.id, "name": p.name, "price": str(p.price)}
                   for p in qs]
    else:
        with connection.cursor() as cur:
            cur.execute(
                """SELECT id, name, price FROM shop_product
                   WHERE MATCH(description) AGAINST (%s IN NATURAL LANGUAGE MODE)
                   LIMIT 20""", [term])
            results = [{"id": r[0], "name": r[1], "price": str(r[2])}
                       for r in cur.fetchall()]
    return JsonResponse({"results": results})


def orders_page(request):
    """FIX: keyset (seek) pagination — 'give me 20 rows after id X' is a pure
    index seek, constant time at any depth. The API contract changes from
    ?page=N to ?after=<last_id>; that trade-off belongs in the case study."""
    after = int(request.GET.get("after", 0))
    orders = Order.objects.filter(id__gt=after).order_by("id")[:20]
    data = [{"id": o.id, "total": str(o.total)} for o in orders]
    next_cursor = data[-1]["id"] if data else None
    return JsonResponse({"orders": data, "next_after": next_cursor})


def top_customers(request):
    """FIX (step 1): partial/composite index on (status, created_at) INCLUDE
    (user_id, total) turns the scan into an index-only range read.
    FIX (step 2, in sql/matview.sql): materialized view refreshed by cron —
    the dashboard then reads 10 precomputed rows. Measure both steps."""
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0,
                                         microsecond=0)
    rows = (Order.objects.filter(created_at__gte=month_start, status="delivered")
            .values("user__username")
            .annotate(spent=Sum("total"))
            .order_by("-spent")[:10])
    return JsonResponse({"top": list(rows)})
