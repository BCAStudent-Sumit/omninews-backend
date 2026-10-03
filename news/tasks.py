from celery import shared_task
from django.core.management import call_command

@shared_task
def ingest_rss_feeds():
    """Shared task to invoke the fetch_news management command."""
    call_command('fetch_news')
    return "RSS Ingestion Finished"