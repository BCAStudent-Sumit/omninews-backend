import os

from pathlib import Path

from datetime import timedelta

from dotenv import load_dotenv



BASE_DIR = Path(__file__).resolve().parent.parent



# Load .env file

load_dotenv(BASE_DIR / '.env')



# Read SECRET_KEY from .env

SECRET_KEY = os.environ["SECRET_KEY"]

# Read DEBUG from env; Render sets DEBUG=False in environment variables.
DEBUG = os.environ.get('DEBUG', 'False').strip().lower() in ('1', 'true', 'yes')



ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    '10.0.2.2',
    '.onrender.com',
    '.vercel.app',
    'omninewsproject.vercel.app',
]
# Allow wildcard only when running locally (DEBUG=True is never set on Render)
if DEBUG:
    ALLOWED_HOSTS.append('*')



# Application definition

INSTALLED_APPS = [

    # Required core Django apps

    'django.contrib.admin',

    'django.contrib.auth',

    'django.contrib.contenttypes',

    'django.contrib.sessions',

    'django.contrib.messages',

    'django.contrib.staticfiles',



    # Third-party apps

    'rest_framework',

    'corsheaders',

    'drf_spectacular',



    # Local apps

    'users',

    'news.apps.NewsConfig',

]



MIDDLEWARE = [

    'corsheaders.middleware.CorsMiddleware',  # Must stay at the very top

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



# Database connection: Render PostgreSQL in Cloud, or MySQL/XAMPP locally

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



# Custom User Model

AUTH_USER_MODEL = 'users.User'



# Password validation

AUTH_PASSWORD_VALIDATORS = [

    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},

    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},

    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},

    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},

]



LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True



STATIC_URL = 'static/'

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'



# DRF & SimpleJWT configuration

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

    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
    },
}



# Authentication backends (support both username and email)

AUTHENTICATION_BACKENDS = [

    'users.backends.EmailOrUsernameModelBackend',

    'django.contrib.auth.backends.ModelBackend',

]



# SimpleJWT configuration

SIMPLE_JWT = {

    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),

    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),

    'ROTATE_REFRESH_TOKENS': False,

    'BLACKLIST_AFTER_ROTATION': False,

    'AUTH_HEADER_TYPES': ('Bearer',),

}



# CORS Configuration - Allow all origins so Vercel, mobile, and web connect seamlessly
# Lock CORS to explicit origins in production
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1:8000',
    'https://omninewsproject.vercel.app',
]
CORS_ALLOW_ALL_ORIGINS = DEBUG  # True only in local dev
CORS_ALLOW_CREDENTIALS = True



# Swagger / OpenAPI Settings

SPECTACULAR_SETTINGS = {

    "TITLE": "OmniNews API",

    "DESCRIPTION": "Community-moderated news platform API.",

    "VERSION": "0.1.0",

    "SERVE_INCLUDE_SCHEMA": False,

}



# Celery Configuration

CELERY_BROKER_URL = 'redis://127.0.0.1:6379/0'

CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/0'

CELERY_ACCEPT_CONTENT = ['json']

CELERY_TASK_SERIALIZER = 'json'

CELERY_RESULT_SERIALIZER = 'json'

CELERY_TIMEZONE = TIME_ZONE



# Celery Beat Periodic Scheduling

CELERY_BEAT_SCHEDULE = {

    'fetch-news-every-10-minutes': {

        'task': 'news.tasks.ingest_rss_feeds',

        'schedule': 600.0,

    },

}



# Google Gemini AI Settings

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

