import os
import time
import hmac
import hashlib
import urllib.parse
from typing import Optional, Dict, Any


def get_stream_signing_secret() -> str:
    """Retrieve signing secret from environment with secure fallback."""
    return os.getenv('STREAM_SIGNING_SECRET', 'omninews-stream-default-signing-secret-2026').strip()


class StreamSigner:
    """
    Modular Stream URL Signing Service.
    Signs stream paths using HMAC-SHA256 over (path, user_id, expiry).
    Easily replaceable by CDN-native signing (Mux, AWS IVS, Cloudflare Stream tokens) later.
    """

    DEFAULT_LIFETIME = 300  # 5 minutes

    @classmethod
    def sign_url(cls, stream_url: str, user_id: Any, lifetime_seconds: int = DEFAULT_LIFETIME) -> str:
        """
        Signs a stream URL, returning a short-lived URL with token, expires, and uid params.
        """
        if not stream_url:
            return ""

        parsed = urllib.parse.urlparse(stream_url)
        path = parsed.path or "/"
        expiry = int(time.time()) + lifetime_seconds
        uid_str = str(user_id) if user_id is not None else "anon"

        secret = get_stream_signing_secret()
        message = f"{path}:{uid_str}:{expiry}"
        token = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

        # Build query parameters
        existing_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        # Remove any prior signature params
        filtered = [p for p in existing_params if p[0] not in ('token', 'expires', 'uid')]
        filtered.extend([
            ('token', token),
            ('expires', str(expiry)),
            ('uid', uid_str),
        ])
        new_query = urllib.parse.urlencode(filtered)

        signed_parts = parsed._replace(query=new_query)
        return urllib.parse.urlunparse(signed_parts)

    @classmethod
    def verify_url(cls, signed_url: str, expected_user_id: Optional[Any] = None) -> bool:
        """
        Validates token integrity and expiry on a signed stream URL.
        """
        if not signed_url:
            return False

        try:
            parsed = urllib.parse.urlparse(signed_url)
            params = dict(urllib.parse.parse_qsl(parsed.query))

            token = params.get('token')
            expires_str = params.get('expires')
            uid = params.get('uid')

            if not token or not expires_str or not uid:
                return False

            expiry = int(expires_str)
            # Check expiration
            if time.time() > expiry:
                return False

            if expected_user_id is not None and str(expected_user_id) != str(uid):
                return False

            path = parsed.path or "/"
            secret = get_stream_signing_secret()
            message = f"{path}:{uid}:{expiry}"
            expected_token = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

            return hmac.compare_digest(token, expected_token)
        except Exception:
            return False

    @classmethod
    def create_token_payload(cls, path: str, user_id: Any, lifetime_seconds: int = DEFAULT_LIFETIME) -> Dict[str, Any]:
        """
        Generates a token payload object for client token refresh.
        """
        clean_path = path or "/"
        expiry = int(time.time()) + lifetime_seconds
        uid_str = str(user_id) if user_id is not None else "anon"

        secret = get_stream_signing_secret()
        message = f"{clean_path}:{uid_str}:{expiry}"
        token = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

        return {
            "token": token,
            "expires": expiry,
            "expires_in": lifetime_seconds,
            "uid": uid_str,
            "path": clean_path,
        }
