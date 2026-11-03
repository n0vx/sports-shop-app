"""Оформление: светлая/тёмная тема + акцентный цвет. Единственное место, где считаются цвета.

Остальная палитра (фон, карточки, границы) живёт в CSS под [data-theme="light|dark"], а акцент считается
здесь, чтобы текст на кнопках всегда оставался читаемым, какой бы цвет ни выбрал пользователь.
"""

from .constants import HEX_RE

THEMES = ("light", "dark")
DEFAULT_THEME = "light"
DEFAULT_ACCENT = "#E4002B"
ACCENT_PRESETS = [  # (название, цвет)
    ("Красный", "#E4002B"),
    ("Оранжевый", "#F26A1B"),
    ("Янтарный", "#D99A00"),
    ("Зелёный", "#16A34A"),
    ("Бирюзовый", "#0891B2"),
    ("Синий", "#1D6FF2"),
    ("Фиолетовый", "#7C3AED"),
    ("Розовый", "#DB2777"),
    ("Графит", "#374151"),
]


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(color, other, amount):
    """Смешивает color с other: amount=0 — исходный цвет, 1 — other."""
    a, b = _rgb(color), _rgb(other)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(a, b)))


def luminance(color):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def valid_theme(value):
    return value if value in THEMES else None


def valid_accent(value):
    return value.upper() if isinstance(value, str) and HEX_RE.match(value) else None


def accent_vars(mode, accent):
    """CSS-переменные акцента для режима. Слишком тёмный цвет в тёмной теме осветляется, слишком светлый
    в светлой — затемняется; цвет текста на акценте выбирается по яркости."""
    accent = valid_accent(accent) or DEFAULT_ACCENT
    if mode == "dark":
        if luminance(accent) < 0.12:
            accent = mix(accent, "#FFFFFF", 0.55)
    elif luminance(accent) > 0.6:
        accent = mix(accent, "#000000", 0.35)
    return {
        "--accent": accent,
        "--accent-hover": mix(accent, "#000000", 0.14),
        "--on-accent": "#FFFFFF" if luminance(accent) < 0.3 else "#16181D",
    }
