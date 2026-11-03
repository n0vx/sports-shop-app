"""Защита: CSRF, заголовки безопасности (CSP с nonce), ограничение подбора пароля."""

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import abort, g, request, session

from .constants import LOGIN_MAX_FAILS, LOGIN_WINDOW_SEC


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


class LoginThrottle:
    """Ограничивает подбор пароля: N неудач за окно — и вход на время закрыт (для пары IP+логин и для IP целиком)."""

    def __init__(self, max_fails=LOGIN_MAX_FAILS, window=LOGIN_WINDOW_SEC):
        self.max_fails, self.window = max_fails, window
        self._fails = defaultdict(deque)
        self._lock = threading.Lock()

    def _keys(self, ip, username):
        return ((ip, username.lower()), self.max_fails), ((ip, None), self.max_fails * 6)

    def _prune(self, bucket, now):
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()

    def blocked_for(self, ip, username):
        """Сколько секунд ещё ждать (0 — можно пробовать)."""
        now = time.monotonic()
        with self._lock:
            wait = 0
            for key, limit in self._keys(ip, username):
                bucket = self._fails.get(key)
                if not bucket:
                    continue
                self._prune(bucket, now)
                if len(bucket) >= limit:
                    wait = max(wait, int(self.window - (now - bucket[0])) + 1)
            return wait

    def fail(self, ip, username):
        now = time.monotonic()
        with self._lock:
            for key, _ in self._keys(ip, username):
                self._fails[key].append(now)
            if len(self._fails) > 5000:  # не даём словарю расти бесконечно
                for key in [k for k, b in self._fails.items() if not b or now - b[-1] > self.window]:
                    del self._fails[key]

    def reset(self, ip, username):
        with self._lock:
            self._fails.pop((ip, username.lower()), None)


def init_security(app, https=False):
    app.extensions["login_throttle"] = LoginThrottle()
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def _csrf_check():
        g.csp_nonce = secrets.token_urlsafe(16)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
            expected = session.get("_csrf") or ""
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, description="csrf")

    @app.after_request
    def _headers(resp):
        nonce = g.get("csp_nonce", "")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            f"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'nonce-{nonce}'; "
            "script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if https:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if "Cache-Control" not in resp.headers and request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-cache"  # страницы зависят от пользователя — не кэшируем вслепую
        return resp
