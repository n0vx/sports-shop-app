"""Общие данные для шаблонов: оформление пользователя, фильтры форматирования."""

import time
from datetime import datetime

from flask import g, session

from .constants import (APP_NAME, BONUS_RATE, CATEGORIES, CATEGORY_EMOJI, LOW_STOCK, MAX_BONUS_SHARE, PHOTO_ACCEPT,
                        SORTS, WELCOME_BONUS)
from .theme import (ACCENT_PRESETS, DEFAULT_ACCENT, DEFAULT_THEME, accent_vars, valid_accent, valid_theme)


ASSET_VERSION = str(int(time.time()))  # сбрасывает кэш css/js браузера после перезапуска


def current_appearance():
    """Тема и акцент: сохранённые в профиле важнее выбранных в этой сессии, затем значения по умолчанию."""
    user = g.get("user")
    theme = valid_theme(user.get("theme") if user else None) or valid_theme(session.get("theme")) or DEFAULT_THEME
    accent = (valid_accent(user.get("accent") if user else None) or valid_accent(session.get("accent"))
              or DEFAULT_ACCENT)
    return theme, accent


def money(value):
    return f"{int(value):,}".replace(",", " ") + " ₽"


def plural(n, forms):
    """plural(5, "товар,товара,товаров") -> «товаров»."""
    one, few, many = forms.split(",")
    n10, n100 = int(n) % 10, int(n) % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def dt(value, fmt="%d.%m.%Y %H:%M"):
    return value.strftime(fmt) if isinstance(value, datetime) else str(value)


def cat_class(category):
    return f"c{CATEGORIES.index(category)}" if category in CATEGORIES else "cx"


def cart_count():
    try:
        return sum(int(v) for v in (session.get("cart") or {}).values())
    except (TypeError, ValueError):
        return 0


def init_context(app):
    app.jinja_env.filters.update(money=money, plural=plural, dt=dt)
    app.jinja_env.globals.update(cat_class=cat_class, category_emoji=CATEGORY_EMOJI)

    @app.context_processor
    def inject():
        theme, accent = current_appearance()
        return dict(
            asset_version=ASSET_VERSION, app_name=APP_NAME, user=g.get("user"), cart_count=cart_count(), categories=CATEGORIES, sorts=SORTS,
            theme=theme, accent=accent, theme_vars=accent_vars(theme, accent), csp_nonce=g.get("csp_nonce", ""),
            accent_presets=ACCENT_PRESETS, photo_accept=PHOTO_ACCEPT, low_stock=LOW_STOCK,
            welcome_bonus=WELCOME_BONUS, bonus_rate_pct=int(BONUS_RATE * 100),
            max_bonus_pct=int(MAX_BONUS_SHARE * 100))
