import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"D:\My project\omninews_backend")
import django
import urllib.request
import re
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'omninews_backend.settings')
django.setup()
from news.models import Article

def fetch_og_image(url):
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            # Only read the head portion (up to 45KB) for speed
            html = resp.read(45000).decode('utf-8', errors='ignore')
            m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
            if not m:
                m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']', html, re.I)
            if m:
                img = m.group(1).strip()
                bad_markers = ["1x1", "pixel", "beacon", "logo", "placeholder", "default_img", "/theme/images/", "og-image.png", "default_share", "default_thumb"]
                if not any(bad in img.lower() for bad in bad_markers):
                    # Boost resolution if applicable
                    if "ichef.bbci.co.uk" in img:
                        img = img.replace("/240/", "/800/").replace("/320/", "/1024/")
                    elif "i.guim.co.uk" in img:
                        img = re.sub(r'width=\d+', 'width=1200', img)
                    return img
    except Exception:
        pass
    return None

def process_article(article_id):
    try:
        a = Article.objects.get(id=article_id)
        if a.image_url:
            return None
        img = fetch_og_image(a.url)
        if img:
            a.image_url = img
            a.save(update_fields=['image_url'])
            return (a.id, a.title[:45], img)
    except Exception:
        pass
    return None

def main():
    missing = list(Article.objects.filter(image_url__isnull=True).values_list('id', flat=True)[:150])
    print(f"Scanning {len(missing)} recent articles missing images to extract real newsroom photos...")
    updated = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        for result in executor.map(process_article, missing):
            if result:
                updated += 1
                aid, title, img = result
                print(f" -> [{aid}] {title}... => {img[:80]}...")
    print(f"\nBackfill Complete: Updated {updated} articles with authentic newsroom photography!")

if __name__ == '__main__':
    main()
