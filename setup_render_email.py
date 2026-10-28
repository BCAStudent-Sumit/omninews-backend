"""
setup_render_email.py

Automates setting EMAIL environment variables on Render.
Supports two modes:
1. Automated API Mode: Give your Render API Token, and it pushes the variables directly.
2. Direct Copy-Paste / .env Mode: Generates the exact format to save to your Render Dashboard.
"""

import sys
import json
import urllib.request
import urllib.error

def prompt_credentials():
    print("=" * 60)
    print(" OmniNews: Render Email Environment Setup")
    print("=" * 60)
    print("\nIf you are using Gmail:")
    print("  1. Go to https://myaccount.google.com/apppasswords")
    print("  2. Create an App Password named 'OmniNews'")
    print("  3. Use your full Gmail address and that 16-character password.\n")

    email_user = input("Enter your sender email (e.g. news@gmail.com): ").strip()
    if not email_user:
        print("Email cannot be empty!")
        sys.exit(1)

    email_pass = input("Enter your App Password / SMTP password: ").strip()
    if not email_pass:
        print("Password cannot be empty!")
        sys.exit(1)

    smtp_host = input("Enter SMTP Host [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
    smtp_port = input("Enter SMTP Port [587]: ").strip() or "587"
    from_name = input("Enter Sender Name [OmniNews]: ").strip() or "OmniNews"
    from_email = f"{from_name} <{email_user}>"

    env_vars = [
        {"key": "EMAIL_BACKEND", "value": "django.core.mail.backends.smtp.EmailBackend"},
        {"key": "EMAIL_HOST", "value": smtp_host},
        {"key": "EMAIL_PORT", "value": smtp_port},
        {"key": "EMAIL_USE_TLS", "value": "True"},
        {"key": "EMAIL_HOST_USER", "value": email_user},
        {"key": "EMAIL_HOST_PASSWORD", "value": email_pass},
        {"key": "DEFAULT_FROM_EMAIL", "value": from_email},
        {"key": "FRONTEND_URL", "value": "https://omninewsproject.vercel.app"},
    ]
    return env_vars

def push_via_render_api(env_vars):
    render_token = input("\nEnter your Render API Key (from https://dashboard.render.com/u/settings#api-keys) [or press Enter to skip]: ").strip()
    if not render_token:
        return False

    service_id = input("Enter your Render Web Service ID (starts with 'srv-', or leave blank to search): ").strip()

    headers = {
        "Authorization": f"Bearer {render_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if not service_id:
        req = urllib.request.Request("https://api.render.com/v1/services", headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                services = json.loads(resp.read().decode())
                backend_srv = None
                for s in services:
                    service_obj = s.get("service", s)
                    if "omninews" in service_obj.get("name", "").lower():
                        backend_srv = service_obj
                        break
                if backend_srv:
                    service_id = backend_srv.get("id")
                    print(f"Found service: {backend_srv.get('name')} ({service_id})")
                else:
                    print("Could not auto-detect service ID. Please find it on your Render URL.")
                    return False
        except Exception as e:
            print(f"Error fetching services: {e}")
            return False

    if service_id:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars"
        payload = json.dumps(env_vars).encode()
        req = urllib.request.Request(url, data=payload, headers=headers, method="PUT")
        try:
            with urllib.request.urlopen(req) as resp:
                print("\n[SUCCESS] Environment variables successfully updated on Render!")
                return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            print(f"\n[ERROR] Failed to push to Render API: {e.code} - {err_body}")
            return False

    return False

def main():
    env_vars = prompt_credentials()
    success = push_via_render_api(env_vars)

    if not success:
        print("\n" + "=" * 60)
        print(" Quick Copy-Paste for Render Dashboard (Manual Option)")
        print("=" * 60)
        print("1. Open: https://dashboard.render.com")
        print("2. Click your 'omninews-backend' Web Service -> Environment")
        print("3. Add or edit these Environment Variables:\n")
        for item in env_vars:
            print(f"{item['key']} = {item['value']}")
        print("=" * 60)

if __name__ == "__main__":
    main()
