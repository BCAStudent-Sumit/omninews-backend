from django.apps import AppConfig


class NewsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'news'

    def ready(self):
        # Automatically launch background news fetcher on server start
        from . import auto_scheduler
        auto_scheduler.start_auto_fetcher()
