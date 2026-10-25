"""
WSGI config for omninews_backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'omninews_backend.settings')

application = get_wsgi_application()

# ---------------------------------------------------------
# Keep-Alive Heartbeat: Prevents Render free tier from sleeping
# ---------------------------------------------------------
import threading
import time
import urllib.request

def _render_keep_alive():
    time.sleep(60)  # Wait 1 min after startup
    while True:
        try:
            req = urllib.request.Request(
                "https://omninews-backend.onrender.com/api/news/telecast/",
                headers={"User-Agent": "OmniNews-Heartbeat/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as _:
                pass
        except Exception:
            pass
        time.sleep(600)  # Every 10 minutes (Render sleeps after 15 min idle)

if os.environ.get("RENDER"):
    t = threading.Thread(target=_render_keep_alive, daemon=True)
    t.start()
