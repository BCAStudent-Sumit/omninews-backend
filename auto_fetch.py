import os
import time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'omninews_backend.settings')
django.setup()

from django.core.management import call_command

INTERVAL_SECONDS = 600  # 10 minutes

def main():
    print("=" * 60)
    print(" OmniNews Auto-Fetcher (Running every 10 minutes)")
    print("=" * 60)
    while True:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching latest news...")
        try:
            call_command('fetch_news')
        except Exception as e:
            print(f"Error during fetch: {e}")
        
        print(f"Next update in 10 minutes. (Press Ctrl+C to stop)")
        time.sleep(INTERVAL_SECONDS)

if __name__ == '__main__':
    main()
