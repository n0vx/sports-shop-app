"""SPORT STORE — веб-версия магазина спорттоваров (Flask + MySQL)."""

import os
import secrets
from datetime import timedelta

from flask import Flask, jsonify, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import admin, auth, shop
from .config import load_config
from .ctx import wants_json
from .context import init_context
from .db import Database, DatabaseUnavailable, Error, friendly_db_error
from .security import init_security

__all__ = ["create_app", "DatabaseUnavailable"]


def _secret_key(app, configured):
    """Ключ подписи сессий: из SECRET_KEY или из файла instance/secret_key (создаётся при первом запуске),
    чтобы после перезапуска никого не «разлогинивало»."""
    if configured:
        return configured
    path = os.path.join(app.instance_path, "secret_key")
    try:
        with open(path, encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key)
    except OSError:
        pass  # не смогли сохранить — ключ будет жить до перезапуска
    return key


def create_app(config=None, load_env=True):
    app = Flask(__name__)
    cfg = load_config(config, use_env_file=load_env)
    app.config.update(
        SECRET_KEY=_secret_key(app, cfg["SECRET_KEY"]),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,           # форма с фото до 20 МБ + запас
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg["HTTPS"],
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        TESTING=bool(cfg.get("TESTING")),
    )
    app.json.ensure_ascii = False
    if cfg["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.extensions["db"] = Database(cfg["MYSQL"])  # DatabaseUnavailable — если MySQL недоступен
    init_security(app, https=cfg["HTTPS"])
    init_context(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(shop.bp)
    app.register_blueprint(admin.bp)

    def error_page(code, title, message):
        if wants_json():
            return jsonify(ok=False, message=message), code
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(exc):
        if getattr(exc, "description", "") == "csrf":
            return error_page(400, "Сессия устарела", "Обновите страницу и повторите действие.")
        return error_page(400, "Некорректный запрос", "Не удалось обработать запрос.")

    @app.errorhandler(403)
    def forbidden(exc):
        return error_page(403, "Нет доступа", "Эта страница доступна только администратору.")

    @app.errorhandler(404)
    def not_found(exc):
        return error_page(404, "Страница не найдена", "Такой страницы нет или товар уже убрали.")

    @app.errorhandler(413)
    def too_large(exc):
        return error_page(413, "Файл слишком большой", "Фото должно весить не больше 20 МБ.")

    @app.errorhandler(Error)
    def database_error(exc):
        app.logger.error("Ошибка MySQL: %s", exc)
        return error_page(503, "База данных недоступна", friendly_db_error(exc))

    @app.errorhandler(500)
    def server_error(exc):
        return error_page(500, "Что-то пошло не так", "Мы уже знаем о проблеме. Попробуйте ещё раз чуть позже.")

    @app.get("/healthz")
    def healthz():
        app.extensions["db"].ping()
        return jsonify(status="ok")

    return app
