from django.urls import path

from . import views_fast, views_slow

urlpatterns = [
    # BEFORE
    path("slow/users/<int:user_id>/orders/", views_slow.user_orders),
    path("slow/reviews/feed/", views_slow.review_feed),
    path("slow/products/search/", views_slow.search),
    path("slow/orders/", views_slow.orders_page),
    path("slow/dashboard/top-customers/", views_slow.top_customers),
    # AFTER
    path("fast/users/<int:user_id>/orders/", views_fast.user_orders),
    path("fast/reviews/feed/", views_fast.review_feed),
    path("fast/products/search/", views_fast.search),
    path("fast/orders/", views_fast.orders_page),
    path("fast/dashboard/top-customers/", views_fast.top_customers),
]
