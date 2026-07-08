"""
shop/models.py — deliberately NAIVE schema for the "before" state.

Notice what is missing on purpose:
  * no composite index on Order(user, created_at)
  * no index on Order.created_at or Review.created_at
  * no full-text index on Product.description
Django DOES auto-index every ForeignKey — that stays, it's the realistic default.

The "after" indexes live in sql/indexes_after.sql (raw DDL for both engines) and as
commented-out Meta.indexes below, so each fix can be its own git commit.
"""

from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    # AFTER (full-text case study, PostgreSQL — MySQL version in sql/):
    # from django.contrib.postgres.indexes import GinIndex
    # from django.contrib.postgres.search import SearchVectorField
    # search = SearchVectorField(null=True)
    # class Meta:
    #     indexes = [GinIndex(fields=["search"])]


class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField()

    # AFTER (composite-index case study):
    # class Meta:
    #     indexes = [models.Index(fields=["user", "-created_at"],
    #                             name="idx_order_user_created")]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField()
    body = models.TextField()
    created_at = models.DateTimeField()
