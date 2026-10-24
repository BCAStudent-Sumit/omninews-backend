try:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.backends.mysql.features import DatabaseFeatures

    # 1. Bypass MariaDB minimum version check (when using local MySQL/MariaDB)
    BaseDatabaseWrapper.check_database_version_supported = lambda self: None

    # 2. Disable 'RETURNING' clause for MariaDB 10.4 compatibility
    DatabaseFeatures.can_return_columns_from_insert = False
except Exception:
    pass

try:
    # 3. Expose Celery app so shared_task works properly
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except Exception:
    pass
