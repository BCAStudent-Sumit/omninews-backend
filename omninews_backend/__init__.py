from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.mysql.features import DatabaseFeatures

# 1. Bypass MariaDB minimum version check
BaseDatabaseWrapper.check_database_version_supported = lambda self: None

# 2. Disable 'RETURNING' clause for MariaDB 10.4 compatibility
DatabaseFeatures.can_return_columns_from_insert = False