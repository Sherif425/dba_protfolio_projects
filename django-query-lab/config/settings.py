"""
Django settings for the query-optimization lab.

Databases:
  default -> PostgreSQL 16 (docker compose service `pg`)
  mysql   -> MySQL 8.4     (docker compose service `mysql`)

Set USE_SQLITE=1 to run a quick smoke test with zero external services
(e.g. `USE_SQLITE=1 python manage.py migrate && USE_SQLITE=1 python manage.py seed`).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "lab-only-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",  # SearchVector for the full-text case study
    "shop",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("USE_SQLITE") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "smoke.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PG_DB", "shop"),
            "USER": os.environ.get("PG_USER", "postgres"),
            "PASSWORD": os.environ.get("PG_PASSWORD", "devpass"),
            "HOST": os.environ.get("PG_HOST", "127.0.0.1"),
            "PORT": os.environ.get("PG_PORT", "5432"),
        },
        "mysql": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MYSQL_DB", "shop"),
            "USER": os.environ.get("MYSQL_USER", "root"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", "devpass"),
            "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
