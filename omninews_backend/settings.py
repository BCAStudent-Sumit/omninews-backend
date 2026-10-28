import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ["SECRET_KEY"]

# FIX 1: DEBUG from env — Render's `DEBUG=False` env var now takes effect.
# Never hardcode DEBUG=True; that setting was masking all Render env overrides.
DEBUG = os.environ.get('DEBUG', 'False').strip().lower() in ('1', 'true', 'yes')

# ---------------------------------------------------------------------------
# Hosts & Origins
# ---------------------------------------------------------------------------
# FIX 2: ALLOWED_HOSTS from env — no wildcard '*' in production.
# In render.yaml set: ALLOWED_HOSTS_EXTRA=omninews-backend.onrender.com
_base_hosts = [
    '127.0.0.1',
    'localhost',
    '10.0.2.2',
    '.onrender.com',
    '.vercel.app',
    'omninewsproject.vercel.app',
]
_extra_hosts = [
    h.strip()
    for h in os.environ.get('ALLOWED_HOSTS_EXTRA', '').split(',')
    if h.strip()
]
ALLOWED_HOSTS = _base_hosts + _extra_hosts
# Wildcard only in local dev; Render always sets DEBUG=False so this never fires in prod.
if DEBUG:
    ALLOWED_HOSTS.append('*')

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'corsheaders',
    'drf_spectacular',

    # Local
    'users',
    'news.apps.NewsConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',          # Must stay at the very top
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'omninews_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'omninews_backend.wsgi.application'

# ---------------------------------------------------------------------------
# Database — Render PostgreSQL in Cloud, MySQL/XAMPP locally, SQLite fallback
# ---------------------------------------------------------------------------
try:
    import dj_database_url
except ImportError:
    dj_database_url = None

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL and dj_database_url:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
elif os.environ.get('USE_SQLITE') == '1':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
elif 'DB_NAME' in os.environ:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'omninews'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = [
    'users.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# ---------------------------------------------------------------------------
# Email SMTP Configuration
# Reads dynamically from environment variables
# ---------------------------------------------------------------------------
# Switch from console backend to standard SMTP backend
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')

# SMTP Server configuration (example shown for Gmail)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = True

# Credentials loaded from environment
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')

# Sender display in emails
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER) or 'OmniNews <noreply@omninews.io>'

# Public frontend URL — used in password-reset email links
FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://omninewsproject.vercel.app')

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# DRF — authentication, permissions, throttling, pagination
# FIX 8: global throttle defaults protect every view not already throttled.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'news.authentication.LenientJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # Global throttles — per-view overrides can tighten these further.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        # Named scopes used by specific views
        'ai_assist_anon': '20/min',
        'fetch_news_user': '10/min',
    },
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ---------------------------------------------------------------------------
# CORS
# FIX 3: CORS from env — CORS_ALLOW_ALL_ORIGINS is False in production.
# To add an extra origin in production set: CORS_ALLOWED_ORIGINS_EXTRA=https://myapp.com
# ---------------------------------------------------------------------------
_cors_base = [
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1:8000',
    'https://omninewsproject.vercel.app',
]
_cors_extra = [
    o.strip()
    for o in os.environ.get('CORS_ALLOWED_ORIGINS_EXTRA', '').split(',')
    if o.strip()
]
CORS_ALLOWED_ORIGINS = _cors_base + _cors_extra
# Allow all only in local dev; Render sets DEBUG=False so this is always False there.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Swagger / OpenAPI
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "OmniNews API",
    "DESCRIPTION": "Community-moderated news platform API.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    'fetch-news-every-10-minutes': {
        'task': 'news.tasks.ingest_rss_feeds',
        'schedule': 600.0,
    },
}

# ---------------------------------------------------------------------------
# Google Gemini AI
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
