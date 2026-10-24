import os
import sys
import time
import threading
import logging
from django.core.management import call_command

logger = logging.getLogger(__name__)

_scheduler_started = False
_lock = threading.Lock()

# Automatically fetch every 10 minutes (600 seconds)
INTERVAL_SECONDS = 600

def _background_worker():
    # Allow the Django HTTP server to finish binding before starting the first fetch
    time.sleep(3)
    print("\n========================================================")
    print(" [OmniNews Auto-Fetcher] Automated news pipeline started")
    print(" Latest news will be fetched automatically every 10 min.")
    print(" No manual 'fetch_news' command needed!")
    print("========================================================\n")

    while True:
        try:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [Auto-Fetcher] Automatically fetching fresh stories (BBC, Google News)...")
            call_command('fetch_news')
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [Auto-Fetcher Warning] Error while fetching: {e}")
        
        # Wait for the next interval
        time.sleep(INTERVAL_SECONDS)

def start_auto_fetcher():
    """
    Starts the automated background news fetcher thread safely.
    Runs only once in the primary Django server process.
    """
    global _scheduler_started
    with _lock:
        if _scheduler_started:
            return

        # When running `manage.py runserver`, Django runs two processes:
        # 1. The autoreload watcher (RUN_MAIN is unset)
        # 2. The actual serving worker (RUN_MAIN == 'true')
        # We only start the fetcher in the actual server worker.
        is_runserver = any('runserver' in arg for arg in sys.argv)
        if is_runserver and os.environ.get('RUN_MAIN') != 'true':
            return

        # Do not run during database migrations or management tasks
        excluded_commands = ['makemigrations', 'migrate', 'collectstatic', 'shell', 'test']
        if any(cmd in sys.argv for cmd in excluded_commands):
            return

        _scheduler_started = True
        worker_thread = threading.Thread(
            target=_background_worker,
            name="OmniNewsAutoFetcherThread",
            daemon=True,
        )
        worker_thread.start()
