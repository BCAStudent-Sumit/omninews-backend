import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'omninews_backend.settings')

app = Celery('omninews_backend')

# Reads configurations prefixed with CELERY_ from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discovers tasks from all installed apps (looks for news/tasks.py)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')