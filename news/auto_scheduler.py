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


def _keep_alive_worker():
    """
    Self-pinging background daemon:
    Sends an inbound HTTP request to Render every 8 minutes (480s) to ensure
    Render's 15-minute inactivity timer NEVER triggers, keeping the server
    awake 24/7 with zero cold starts.
    Also warms up the top language feeds in memory so readers get instant 2ms responses.
    """
    import urllib.request
    import json

    # Allow gunicorn/server to bind before initial self-ping
    time.sleep(12)
    backend_url = "https://omninews-backend.onrender.com"

    while True:
        try:
            # 1. Self-ping to reset Render 15-minute idle timer
            ping_url = f"{backend_url}/api/news/ping/"
            req = urllib.request.Request(ping_url, headers={"User-Agent": "OmniNewsKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                logger.info(f"[Keep-Alive] Server pinged: {data.get('status')}")

            # 2. Warm up top language feeds into memory cache
            warmup_targets = [
                f"{backend_url}/api/news/feed/",
                f"{backend_url}/api/news/feed/?languages=bn",
                f"{backend_url}/api/news/feed/?languages=de",
                f"{backend_url}/api/news/feed/?languages=hi",
                f"{backend_url}/api/news/feed/?genres=3&languages=bn",
            ]
            for target in warmup_targets:
                try:
                    wreq = urllib.request.Request(target, headers={"User-Agent": "OmniNewsWarmup/1.0"})
                    with urllib.request.urlopen(wreq, timeout=20) as wresp:
                        pass
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"[Keep-Alive] Ping notice: {e}")

        # Sleep for 8 minutes (480s) - well below Render's 15-minute threshold
        time.sleep(480)

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
        keep_alive_thread = threading.Thread(
            target=_keep_alive_worker,
            name="OmniNewsKeepAliveThread",
            daemon=True,
        )
        keep_alive_thread.start()
        worker_thread.start()
