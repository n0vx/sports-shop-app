"""Регистрация, вход, выход и декораторы доступа."""

from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from .constants import USERNAME_RE, WELCOME_BONUS
from .ctx import get_db

bp = Blueprint("auth", __name__)

_NO_USER_ENDPOINTS = {"static", "shop.product_photo", "healthz"}


def safe_next(target):
    """Разрешаем возвращаться только на страницы этого же сайта (защита от open redirect)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parsed = urlparse(target)
    return target if not parsed.scheme and not parsed.netloc else None


def current_url():
    return request.full_path.rstrip("?") if request.method == "GET" else url_for("shop.index")


@bp.before_app_request
def load_user():
    g.user = None
    if request.endpoint in _NO_USER_ENDPOINTS:
        return
    uid = session.get("uid")
    if uid:
        g.user = get_db().get_user(uid)  # роль берём из базы на каждом запросе: права не «залипают» в cookie
        if g.user is None:
            session.pop("uid", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Войдите в аккаунт, чтобы продолжить", "info")
            return redirect(url_for("auth.login", next=current_url()))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def start_session(user):
    keep = {k: session[k] for k in ("theme", "accent", "cart") if k in session}
    session.clear()  # новый CSRF-токен и чистая сессия после входа
    session.update(keep)
    session["uid"] = user["id"]
    session.permanent = True


@bp.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if g.user:
        return redirect(url_for("shop.index"))
    if db.user_count() == 0:
        return redirect(url_for("auth.register"))
    error, status, username = None, 200, ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")[:256]
        throttle = current_app.extensions["login_throttle"]
        ip = request.remote_addr or "?"
        wait = throttle.blocked_for(ip, username)
        if wait:
            error, status = f"Слишком много неудачных попыток. Повторите через {max(1, -(-wait // 60))} мин.", 429
        else:
            user = db.authenticate(username, password) if username and password else None
            if user:
                throttle.reset(ip, username)
                start_session(user)
                return redirect(safe_next(request.args.get("next")) or url_for("shop.index"))
            throttle.fail(ip, username)
            error, status = "Неверный логин или пароль", 401
    return render_template("auth/login.html", error=error, username=username,
                           next=request.args.get("next", "")), status


@bp.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    if g.user:
        return redirect(url_for("shop.index"))
    first_run = db.user_count() == 0
    error, status, username = None, 200, ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not USERNAME_RE.match(username):
            error = "Логин: 3–20 символов, латиница, цифры и . _ -"
        elif len(password) < 6:
            error = "Пароль должен быть не короче 6 символов"
        elif len(password) > 256:
            error = "Пароль слишком длинный"
        elif password != request.form.get("password2", ""):
            error = "Пароли не совпадают"
        else:
            try:
                user = db.register(username, password)
            except ValueError as exc:
                error = str(exc)
            else:
                start_session(user)
                flash("Добро пожаловать!" if first_run else f"Добро пожаловать! Вам начислено {WELCOME_BONUS} баллов",
                      "ok")
                return redirect(safe_next(request.args.get("next")) or url_for("shop.index"))
        status = 422
    return render_template("auth/register.html", error=error, username=username, first_run=first_run,
                           next=request.args.get("next", "")), status


@bp.post("/logout")
def logout():
    keep = {k: session[k] for k in ("theme", "accent") if k in session}
    session.clear()
    session.update(keep)
    return redirect(url_for("shop.index"))
