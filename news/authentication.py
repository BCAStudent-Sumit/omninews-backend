from rest_framework_simplejwt.authentication import JWTAuthentication


class LenientJWTAuthentication(JWTAuthentication):
    """
    Subclass of JWTAuthentication that gracefully ignores 'Bearer null',
    'Bearer undefined', and expired tokens on safe read requests (GET/HEAD/OPTIONS),
    allowing guest users to view public feeds and bookmarks without 401 Unauthorized errors.
    """
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        token_str = raw_token.decode('utf-8', errors='ignore') if isinstance(raw_token, bytes) else str(raw_token)
        if token_str.strip().lower() in ('null', 'undefined', ''):
            return None

        try:
            return super().authenticate(request)
        except Exception:
            # On safe read requests, treat expired/invalid tokens as guest rather than aborting with 401
            if request.method in ('GET', 'HEAD', 'OPTIONS'):
                return None
            raise
