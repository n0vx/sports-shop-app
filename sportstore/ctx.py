"""Доступ к общим объектам приложения."""

from flask import current_app, request


def get_db():
    return current_app.extensions["db"]


def wants_json():
    """fetch-запросы из нашего JS (X-Requested-With: fetch) получают JSON вместо редиректа."""
    return request.headers.get("X-Requested-With") == "fetch" or request.is_json
