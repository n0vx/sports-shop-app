"""SPORT STORE — настольное приложение магазина спорттоваров (Tkinter + SQLite).

Запуск:  python app.py
Данные хранятся в файле store.db рядом со скриптом.
Первый зарегистрированный пользователь становится администратором.
"""

import hashlib
import hmac
import os
import re
import sqlite3
import sys
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, ttk

APP_NAME = "SPORT STORE"
DB_PATH = os.environ.get("SPORT_STORE_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "store.db"
)

BONUS_RATE = 0.05        # 5% от оплаченной суммы возвращается баллами
MAX_BONUS_SHARE = 0.30   # баллами можно оплатить не больше 30% заказа
WELCOME_BONUS = 500      # приветственные баллы новому покупателю
LOW_STOCK = 3            # «Осталось N» показываем, когда на складе <= этого числа
CARD_W = 232

USE_EMOJI = not sys.platform.startswith("linux")  # на Linux цветные эмодзи могут ронять Tk
EMOJI_FONT = "Segoe UI Emoji" if sys.platform == "win32" else "Apple Color Emoji"

CATEGORIES = ["Одежда", "Обувь", "Тренажёры и инвентарь", "Питание"]
CATEGORY_STYLE = {  # эмодзи, фон плитки (светлая тема), фон плитки (тёмная тема)
    "Одежда": ("👕", "#FDE8EA", "#3B2328"),
    "Обувь": ("👟", "#E8F0FD", "#1F2B40"),
    "Тренажёры и инвентарь": ("🏋️", "#FFF1DD", "#3E3020"),
    "Питание": ("🥤", "#E6F7EC", "#1D3326"),
}
SORTS = ["Популярные", "Сначала дешёвые", "Сначала дорогие", "По названию"]

THEMES = {
    "light": dict(
        bg="#F3F4F6", surface="#FFFFFF", border="#E2E4E8", hover="#F1F2F4",
        text="#16181D", muted="#6B7280", field="#FFFFFF",
        accent="#E4002B", accent_hover="#C30024", ok="#16A34A", danger="#DC2626",
    ),
    "dark": dict(
        bg="#0F1114", surface="#1A1D22", border="#2B2F36", hover="#242830",
        text="#F3F4F6", muted="#9AA0AA", field="#22262C",
        accent="#FF3B4E", accent_hover="#E02A3C", ok="#22C55E", danger="#F87171",
    ),
}

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
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

SEED_PRODUCTS = [
    ("Кроссовки беговые мужские", "Обувь", 12999, 12, "👟"),
    ("Куртка утеплённая ветрозащитная", "Одежда", 18999, 8, "🧥"),
    ("Протеин изолят 900 г", "Питание", 3890, 25, "🥤"),
    ("Гантель обрезиненная 10 кг", "Тренажёры и инвентарь", 2999, 15, "🏋️"),
    ("Беговая дорожка домашняя", "Тренажёры и инвентарь", 34999, 3, "🏃"),
    ("Бутсы футбольные газонные", "Обувь", 3599, 10, "⚽"),
    ("Спортивный костюм тренировочный", "Одежда", 6499, 14, "👕"),
    ("Коврик для йоги 6 мм", "Тренажёры и инвентарь", 1490, 20, "🧘"),
    ("Скакалка скоростная", "Тренажёры и инвентарь", 790, 0, "🪢"),
    ("Батончик протеиновый, 12 шт.", "Питание", 1890, 30, "🍫"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    pw_hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    role TEXT NOT NULL DEFAULT 'customer',
    bonuses INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price > 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    emoji TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    total INTEGER NOT NULL,
    bonus_spent INTEGER NOT NULL,
    bonus_earned INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")


# --------------------------------------------------------------------------- helpers

def money(n):
    return f"{int(n):,}".replace(",", "\u00a0") + "\u00a0₽"


def plural(n, forms):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return forms[1]
    return forms[2]


def ico(symbol):
    """Эмодзи-иконка с пробелом или пустая строка, если эмодзи отключены."""
    return symbol + " " if USE_EMOJI else ""


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


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


def build_theme(mode, accent):
    """Собирает палитру из режима (light/dark) и акцентного цвета, следя за читаемостью."""
    t = dict(THEMES.get(mode, THEMES[DEFAULT_THEME]))
    if not HEX_RE.match(accent or ""):
        accent = DEFAULT_ACCENT
    accent = accent.upper()
    if mode == "dark":
        if luminance(accent) < 0.12:      # слишком тёмный акцент на тёмном фоне — осветляем
            accent = mix(accent, "#FFFFFF", 0.55)
    elif luminance(accent) > 0.6:         # слишком светлый акцент на белом — затемняем
        accent = mix(accent, "#000000", 0.35)
    t["accent"] = accent
    t["accent_hover"] = mix(accent, "#000000", 0.14)
    t["on_accent"] = "#FFFFFF" if luminance(accent) < 0.3 else "#16181D"
    return t


def pick_font_family(root):
    available = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Roboto", "DejaVu Sans", "Arial"):
        if name in available:
            return name
    return "TkDefaultFont"


# --------------------------------------------------------------------------- database

class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        if self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            with self.conn:
                self.conn.executemany(
                    "INSERT INTO products(name, category, price, stock, emoji) VALUES (?,?,?,?,?)",
                    SEED_PRODUCTS,
                )

    def _migrate(self):
        """Добавляет колонки оформления в базы, созданные предыдущей версией."""
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(users)")}
        with self.conn:
            if "theme" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN theme TEXT")
            if "accent" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN accent TEXT")

    def set_user_appearance(self, user_id, theme, accent):
        with self.conn:
            self.conn.execute("UPDATE users SET theme=?, accent=? WHERE id=?", (theme, accent, user_id))

    def close(self):
        self.conn.close()

    # настройки
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # пользователи
    def user_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_user(self, user_id):
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def register(self, username, password):
        is_first = self.user_count() == 0
        salt = os.urandom(16)
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO users(username, pw_hash, salt, role, bonuses) VALUES (?,?,?,?,?)",
                    (username.lower(), hash_password(password, salt), salt,
                     "admin" if is_first else "customer", 0 if is_first else WELCOME_BONUS),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Этот логин уже занят")
        return self.get_user(cur.lastrowid)

    def authenticate(self, username, password):
        row = self.conn.execute("SELECT * FROM users WHERE username=?", (username.lower(),)).fetchone()
        if row is None:
            return None
        if not hmac.compare_digest(row["pw_hash"], hash_password(password, row["salt"])):
            return None
        return dict(row)

    # товары
    def products(self):
        return self.conn.execute("SELECT * FROM products ORDER BY id").fetchall()

    def get_product(self, product_id):
        return self.conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def save_product(self, product_id, name, category, price, stock, emoji):
        with self.conn:
            if product_id is None:
                self.conn.execute(
                    "INSERT INTO products(name, category, price, stock, emoji) VALUES (?,?,?,?,?)",
                    (name, category, price, stock, emoji),
                )
            else:
                self.conn.execute(
                    "UPDATE products SET name=?, category=?, price=?, stock=?, emoji=? WHERE id=?",
                    (name, category, price, stock, emoji, product_id),
                )

    def delete_product(self, product_id):
        with self.conn:
            self.conn.execute("DELETE FROM products WHERE id=?", (product_id,))

    # заказы
    def checkout(self, user_id, cart, use_bonuses):
        """Оформляет заказ одной транзакцией. cart: {product_id: qty}."""
        with self.conn:
            user = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            lines, total = [], 0
            for pid, qty in cart.items():
                p = self.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                if p is None:
                    raise ValueError("Один из товаров больше не продаётся — обновите корзину")
                if p["stock"] < qty:
                    raise ValueError(f"«{p['name']}»: на складе осталось {p['stock']} шт.")
                lines.append((p, qty))
                total += p["price"] * qty
            spend = min(user["bonuses"], int(total * MAX_BONUS_SHARE)) if use_bonuses else 0
            paid = total - spend
            earned = int(paid * BONUS_RATE)
            cur = self.conn.execute(
                "INSERT INTO orders(user_id, total, bonus_spent, bonus_earned, created_at) VALUES (?,?,?,?,?)",
                (user_id, total, spend, earned, datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
            order_id = cur.lastrowid
            for p, qty in lines:
                self.conn.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, p["id"]))
                self.conn.execute(
                    "INSERT INTO order_items(order_id, product_id, name, price, qty) VALUES (?,?,?,?,?)",
                    (order_id, p["id"], p["name"], p["price"], qty),
                )
            self.conn.execute(
                "UPDATE users SET bonuses = bonuses - ? + ? WHERE id=?", (spend, earned, user_id)
            )
        return dict(order_id=order_id, total=total, spent=spend, paid=paid, earned=earned)

    def orders(self, user_id, limit=30):
        result = []
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
        for o in rows:
            items = self.conn.execute(
                "SELECT name, qty FROM order_items WHERE order_id=? ORDER BY id", (o["id"],)
            ).fetchall()
            result.append((dict(o), [(i["name"], i["qty"]) for i in items]))
        return result


# --------------------------------------------------------------------------- widgets

class FlatButton(tk.Label):
    """Плоская кнопка с hover-эффектом (одинаково выглядит на Windows, macOS и Linux)."""

    def __init__(self, parent, text, command=None, *, bg, fg, hover, font,
                 border=None, padx=16, pady=8, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady,
                         cursor="hand2", highlightthickness=1, highlightbackground=border or bg, **kw)
        self._normal, self._hover, self._command, self._enabled = bg, hover, command, True
        self.bind("<Enter>", lambda e: self._enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._normal))
        self.bind("<Button-1>", lambda e: self._enabled and self._command and self._command())

    def restyle(self, bg, fg, hover, border):
        self._normal, self._hover = bg, hover
        self.configure(bg=bg, fg=fg, highlightbackground=border or bg)

    def disable(self, fg):
        self._enabled = False
        self.configure(fg=fg, cursor="arrow", bg=self._normal)


class ScrollFrame(tk.Frame):
    """Прокручиваемая область. Колесо мыши обрабатывает App (по позиции курсора)."""

    def __init__(self, parent, bg, on_width=None):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._on_width = on_width
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resized)

    def _resized(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        if self._on_width:
            self._on_width(event.width)

    def scroll(self, direction):
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(direction * 2, "units")


# --------------------------------------------------------------------------- application

class SportStoreApp(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            self.db = Database(DB_PATH)
        except sqlite3.Error as exc:
            messagebox.showerror(APP_NAME, f"Не удалось открыть базу данных:\n{exc}")
            raise SystemExit(1)

        self.title(APP_NAME)
        self.geometry("1200x800")
        self.minsize(920, 600)
        self.family = pick_font_family(self)
        self.style = ttk.Style(self)

        self.theme_name = self.db.get_setting("theme", DEFAULT_THEME)
        if self.theme_name not in THEMES:
            self.theme_name = DEFAULT_THEME
        self.accent = self.db.get_setting("accent", DEFAULT_ACCENT)
        if not HEX_RE.match(self.accent):
            self.accent = DEFAULT_ACCENT
        self.user = None
        self.cart = {}
        self.category = "Все"
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value=SORTS[0])
        self.cards, self._cols, self._toast = [], 0, None
        self.chip_buttons = {}

        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.apply_theme()
        self.render()

    # ----- тема и шрифты
    def f(self, size, weight="normal"):
        return (self.family, size, weight)

    def apply_theme(self):
        t = self.t = build_theme(self.theme_name, self.accent)
        self.configure(bg=t["bg"])
        s = self.style
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=t["field"], background=t["field"], foreground=t["text"],
                    bordercolor=t["border"], lightcolor=t["border"], darkcolor=t["border"],
                    arrowcolor=t["muted"], padding=6)
        s.map("TCombobox",
              fieldbackground=[("readonly", t["field"])], foreground=[("readonly", t["text"])],
              selectbackground=[("readonly", t["field"])], selectforeground=[("readonly", t["text"])])
        s.configure("Vertical.TScrollbar", background=t["border"], troughcolor=t["bg"],
                    bordercolor=t["bg"], lightcolor=t["border"], darkcolor=t["border"],
                    arrowcolor=t["muted"], relief="flat")
        self.option_add("*TCombobox*Listbox.background", t["field"])
        self.option_add("*TCombobox*Listbox.foreground", t["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["on_accent"])
        self.option_add("*TCombobox*Listbox.font", self.f(10))

    def adopt_user_appearance(self):
        """После входа подхватывает личные настройки оформления пользователя."""
        theme, accent = self.user.get("theme"), self.user.get("accent")
        if theme in THEMES or (accent and HEX_RE.match(accent)):
            if theme in THEMES:
                self.theme_name = theme
            if accent and HEX_RE.match(accent):
                self.accent = accent.upper()
            self.apply_theme()

    def set_appearance(self, theme=None, accent=None):
        """Меняет оформление, сохраняет его (для пользователя и как последнее на этом устройстве)."""
        if theme in THEMES:
            self.theme_name = theme
        if accent and HEX_RE.match(accent):
            self.accent = accent.upper()
        self.db.set_setting("theme", self.theme_name)
        self.db.set_setting("accent", self.accent)
        if self.user is not None:
            self.db.set_user_appearance(self.user["id"], self.theme_name, self.accent)
            self.user["theme"], self.user["accent"] = self.theme_name, self.accent
        self.apply_theme()
        self.render()

    def open_appearance(self):
        d = self.dialog("Оформление", 480, 560)

        def build():
            t = self.t
            for w in d.winfo_children():
                w.destroy()
            d.configure(bg=t["bg"])
            box = tk.Frame(d, bg=t["bg"], padx=28, pady=24)
            box.pack(fill="both", expand=True)
            tk.Label(box, text="Оформление", font=self.f(20, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
            tk.Label(box, text="Выберите режим и цвет — изменения применяются сразу и сохраняются в вашем профиле",
                     font=self.f(10), fg=t["muted"], bg=t["bg"], wraplength=420, justify="left"
                     ).pack(anchor="w", pady=(4, 18))

            tk.Label(box, text="Режим", font=self.f(10, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
            modes = tk.Frame(box, bg=t["bg"])
            modes.pack(fill="x", pady=(6, 18))
            for key, title in (("light", "Светлая"), ("dark", "Тёмная")):
                active = self.theme_name == key
                btn = self.button(
                    modes, title, lambda k=key: choose(theme=k), "primary" if active else "secondary",
                    pady=10)
                btn.pack(side="left", fill="x", expand=True, padx=(0, 6) if key == "light" else (6, 0))

            tk.Label(box, text="Цвет", font=self.f(10, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
            grid = tk.Frame(box, bg=t["bg"])
            grid.pack(fill="x", pady=(8, 6))
            for i, (name, color) in enumerate(ACCENT_PRESETS):
                cell = tk.Frame(grid, bg=t["bg"])
                cell.grid(row=i // 5, column=i % 5, padx=6, pady=6)
                selected = color.upper() == self.accent
                swatch = tk.Label(cell, text="✓" if selected else "", bg=color, width=4, height=2,
                                  fg="#FFFFFF" if luminance(color) < 0.3 else "#16181D",
                                  font=self.f(12, "bold"), cursor="hand2", highlightthickness=3,
                                  highlightbackground=t["text"] if selected else t["bg"])
                swatch.pack()
                swatch.bind("<Button-1>", lambda e, c=color: choose(accent=c))
                tk.Label(cell, text=name, font=self.f(8), fg=t["muted"], bg=t["bg"]).pack(pady=(3, 0))
            is_custom = self.accent not in {c.upper() for _, c in ACCENT_PRESETS}
            custom_row = tk.Frame(box, bg=t["bg"])
            custom_row.pack(fill="x", pady=(10, 0))
            self.button(custom_row, "Свой цвет…", pick_custom, "secondary", pady=9).pack(side="left")
            if is_custom:
                tk.Label(custom_row, text="  выбран: " + self.accent, font=self.f(10), fg=t["muted"],
                         bg=t["bg"]).pack(side="left")

            # мини-превью
            tk.Label(box, text="Так это выглядит", font=self.f(10, "bold"), fg=t["text"], bg=t["bg"]
                     ).pack(anchor="w", pady=(20, 6))
            prev = tk.Frame(box, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"],
                            padx=14, pady=12)
            prev.pack(fill="x")
            tk.Label(prev, text="12 999 ₽", font=self.f(15, "bold"), fg=t["text"],
                     bg=t["surface"]).pack(side="left")
            self.button(prev, "В корзину", None, "primary", pady=7).pack(side="right")
            self.button(prev, "Категория", None, "secondary", pady=7).pack(side="right", padx=8)

            foot = tk.Frame(box, bg=t["bg"])
            foot.pack(side="bottom", fill="x")
            self.button(foot, "По умолчанию", reset, "secondary", pady=10).pack(
                side="left", fill="x", expand=True, padx=(0, 6))
            self.button(foot, "Готово", d.destroy, "primary", pady=10).pack(
                side="left", fill="x", expand=True, padx=(6, 0))

        def choose(theme=None, accent=None):
            self.set_appearance(theme=theme, accent=accent)
            build()
            d.lift()

        def pick_custom():
            from tkinter import colorchooser
            _rgb_value, chosen = colorchooser.askcolor(color=self.accent, parent=d, title="Свой цвет")
            if chosen and HEX_RE.match(chosen):
                choose(accent=chosen)

        def reset():
            choose(theme=DEFAULT_THEME, accent=DEFAULT_ACCENT)

        build()

    # ----- общие конструкторы виджетов
    def button(self, parent, text, command=None, kind="primary", size=10, weight="bold", **over):
        t = self.t
        styles = {
            "primary": dict(bg=t["accent"], fg=t["on_accent"], hover=t["accent_hover"]),
            "secondary": dict(bg=t["surface"], fg=t["text"], hover=t["hover"], border=t["border"]),
            "ghost": dict(bg=t["surface"], fg=t["text"], hover=t["hover"]),
            "danger": dict(bg=t["surface"], fg=t["danger"], hover=t["hover"], border=t["border"]),
        }
        spec = dict(styles[kind])
        spec.update(over)
        return FlatButton(parent, text, command, font=self.f(size, weight), **spec)

    def field(self, parent, var=None, show=None, icon=None):
        t = self.t
        frame = tk.Frame(parent, bg=t["field"], highlightthickness=1, highlightbackground=t["border"])
        if icon:
            tk.Label(frame, text=icon, bg=t["field"], fg=t["muted"], font=self.f(11)).pack(side="left", padx=(12, 0))
        entry = tk.Entry(frame, textvariable=var, show=show or "", font=self.f(11), bg=t["field"],
                         fg=t["text"], insertbackground=t["text"], relief="flat", bd=0, highlightthickness=0)
        entry.pack(side="left", fill="x", expand=True, padx=12, ipady=8)
        entry.bind("<FocusIn>", lambda e: frame.configure(highlightbackground=t["accent"]))
        entry.bind("<FocusOut>", lambda e: frame.configure(highlightbackground=t["border"]))
        return frame, entry

    def tile(self, parent, product, w, h, size):
        emoji, light, dark = CATEGORY_STYLE.get(product["category"], ("🏅", "#EEEEEE", "#2A2A2A"))
        canvas = tk.Canvas(parent, width=w, height=h, bd=0, highlightthickness=0,
                           bg=light if self.theme_name == "light" else dark)
        if USE_EMOJI:
            canvas.create_text(w / 2, h / 2, text=product["emoji"] or emoji, font=(EMOJI_FONT, size))
        else:
            canvas.create_text(w / 2, h / 2, text=product["name"][:1].upper(),
                               font=self.f(int(size * 0.9), "bold"), fill=self.t["muted"])
        return canvas

    def badge(self, canvas, text, color, fg):
        w = len(text) * 7 + 20
        canvas.create_rectangle(10, 10, 10 + w, 32, fill=color, outline="")
        canvas.create_text(10 + w / 2, 21, text=text, fill=fg, font=self.f(9, "bold"))

    def toast(self, text, ok=True):
        if self._toast is not None and self._toast.winfo_exists():
            self._toast.destroy()
        label = tk.Label(self, text=text, bg=self.t["ok"] if ok else self.t["danger"],
                         fg="#FFFFFF" if self.theme_name == "light" else "#0F1114",
                         font=self.f(10, "bold"), padx=20, pady=11)
        label.place(relx=0.5, rely=0.95, anchor="s")
        label.lift()
        self._toast = label
        self.after(1800, lambda: label.winfo_exists() and label.destroy())

    def dialog(self, title, w, h):
        d = tk.Toplevel(self)
        d.title(title)
        d.configure(bg=self.t["bg"])
        d.transient(self)
        d.resizable(False, False)
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        d.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        d.bind("<Escape>", lambda e: d.destroy())
        d.update_idletasks()
        try:
            d.grab_set()
        except tk.TclError:
            pass
        return d

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.scroll(direction)
                return
            widget = widget.master

    # ----- навигация
    def clear(self):
        for w in self.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.cards, self._cols, self._toast = [], 0, None

    def render(self):
        if self.user is None:
            self.show_auth()
        else:
            self.show_shop()

    def on_close(self):
        self.db.close()
        self.destroy()

    def reload_user(self):
        self.user = self.db.get_user(self.user["id"])

    # ----- экран входа / регистрации
    def show_auth(self, mode=None):
        t = self.t
        first_run = self.db.user_count() == 0
        if mode is None:
            mode = "register" if first_run else "login"
        self.clear()

        root = tk.Frame(self, bg=t["bg"])
        root.pack(fill="both", expand=True)

        left = tk.Frame(root, bg=t["accent"], width=460)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        brand = tk.Frame(left, bg=t["accent"])
        brand.place(relx=0.5, rely=0.5, anchor="center")
        on = t["on_accent"]
        tk.Label(brand, text="SPORT", font=self.f(44, "bold italic"), fg=on, bg=t["accent"]).pack(anchor="w")
        tk.Label(brand, text="STORE", font=self.f(44, "bold italic"), fg=mix(t["accent"], on, 0.55),
                 bg=t["accent"]).pack(anchor="w")
        tk.Label(brand, text="Всё для спорта в одном месте", font=self.f(13), fg=on,
                 bg=t["accent"]).pack(anchor="w", pady=(10, 28))
        for line in ("5% баллами с каждой покупки",
                     "Оплата баллами до 30% заказа",
                     "Актуальные остатки на складе"):
            tk.Label(brand, text="✓  " + line, font=self.f(11), fg=on, bg=t["accent"]).pack(anchor="w", pady=3)

        right = tk.Frame(root, bg=t["bg"])
        right.pack(side="left", fill="both", expand=True)
        self.button(right, f"{ico('🎨')}Оформление", self.open_appearance, "secondary",
                    weight="normal").place(relx=1.0, x=-24, y=24, anchor="ne")
        card = tk.Frame(right, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"],
                        padx=40, pady=36)
        card.place(relx=0.5, rely=0.5, anchor="center")

        title = "Регистрация" if mode == "register" else "Вход в аккаунт"
        tk.Label(card, text=title, font=self.f(20, "bold"), fg=t["text"], bg=t["surface"]).pack(anchor="w")
        if first_run:
            hint = "Первый запуск: этот аккаунт станет администратором магазина"
        elif mode == "register":
            hint = f"Создайте аккаунт и получите {WELCOME_BONUS} приветственных баллов"
        else:
            hint = "Рады видеть вас снова"
        tk.Label(card, text=hint, font=self.f(10), fg=t["muted"], bg=t["surface"],
                 wraplength=320, justify="left").pack(anchor="w", pady=(4, 22))

        u_var, p_var, p2_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        tk.Label(card, text="Логин", font=self.f(9, "bold"), fg=t["text"], bg=t["surface"]).pack(anchor="w")
        u_frame, u_entry = self.field(card, u_var)
        u_frame.pack(fill="x", pady=(5, 14))
        tk.Label(card, text="Пароль", font=self.f(9, "bold"), fg=t["text"], bg=t["surface"]).pack(anchor="w")
        p_frame, p_entry = self.field(card, p_var, show="•")
        p_frame.pack(fill="x", pady=(5, 14))
        p2_entry = None
        if mode == "register":
            tk.Label(card, text="Повторите пароль", font=self.f(9, "bold"), fg=t["text"],
                     bg=t["surface"]).pack(anchor="w")
            p2_frame, p2_entry = self.field(card, p2_var, show="•")
            p2_frame.pack(fill="x", pady=(5, 14))

        error = tk.Label(card, text="", font=self.f(9), fg=t["danger"], bg=t["surface"],
                         wraplength=320, justify="left", anchor="w")
        error.pack(fill="x", pady=(0, 8))

        def submit(_event=None):
            username, password = u_var.get().strip(), p_var.get()
            if mode == "register":
                if not USERNAME_RE.match(username):
                    error.config(text="Логин: 3–20 символов, латиница, цифры и . _ -")
                    return
                if len(password) < 6:
                    error.config(text="Пароль должен быть не короче 6 символов")
                    return
                if password != p2_var.get():
                    error.config(text="Пароли не совпадают")
                    return
                try:
                    user = self.db.register(username, password)
                except ValueError as exc:
                    error.config(text=str(exc))
                    return
            else:
                user = self.db.authenticate(username, password)
                if user is None:
                    error.config(text="Неверный логин или пароль")
                    return
            self.user = user
            self.cart.clear()
            self.adopt_user_appearance()
            self.show_shop()

        self.button(card, "Зарегистрироваться" if mode == "register" else "Войти", submit,
                    size=11, pady=11).pack(fill="x")
        if not first_run:
            other = "login" if mode == "register" else "register"
            text = "Уже есть аккаунт? Войти" if mode == "register" else "Нет аккаунта? Зарегистрироваться"
            link = tk.Label(card, text=text, font=self.f(10), fg=t["accent"], bg=t["surface"], cursor="hand2")
            link.pack(pady=(16, 0))
            link.bind("<Button-1>", lambda e: self.show_auth(other))

        for entry in (u_entry, p_entry, p2_entry):
            if entry is not None:
                entry.bind("<Return>", submit)
        u_entry.focus_set()

    # ----- главный экран
    def show_shop(self):
        t = self.t
        admin = self.user["role"] == "admin"
        self.clear()
        self.chip_buttons = {}

        header = tk.Frame(self, bg=t["surface"])
        header.pack(fill="x")
        tk.Frame(header, bg=t["accent"], height=4).pack(fill="x")
        bar = tk.Frame(header, bg=t["surface"], padx=24, pady=14)
        bar.pack(fill="x")

        logo = tk.Frame(bar, bg=t["surface"])
        logo.pack(side="left")
        tk.Label(logo, text="SPORT", font=self.f(20, "bold italic"), fg=t["accent"], bg=t["surface"]).pack(side="left")
        tk.Label(logo, text="STORE", font=self.f(20, "bold italic"), fg=t["text"], bg=t["surface"]).pack(side="left", padx=(5, 0))

        right = tk.Frame(bar, bg=t["surface"])
        right.pack(side="right")
        self.button(right, f"{ico('🎨')}Оформление", self.open_appearance, "secondary",
                    weight="normal").pack(side="left", padx=4)
        self.profile_btn = self.button(right, "", self.open_profile, "secondary")
        self.profile_btn.pack(side="left", padx=4)
        self.cart_btn = self.button(right, "", self.open_cart, "primary")
        self.cart_btn.pack(side="left", padx=(4, 0))

        search_box = tk.Frame(bar, bg=t["surface"])
        search_box.pack(side="left", fill="x", expand=True, padx=28)
        s_frame, s_entry = self.field(search_box, self.search_var, icon=ico("🔍") or "⌕")
        s_frame.pack(fill="x")
        s_entry.bind("<KeyRelease>", lambda e: self.refresh_catalog())
        tk.Frame(header, bg=t["border"], height=1).pack(fill="x")

        chips = tk.Frame(self, bg=t["bg"])
        chips.pack(fill="x", padx=24, pady=(16, 4))
        for name in ["Все"] + CATEGORIES:
            btn = self.button(chips, name, lambda n=name: self.set_category(n), "secondary",
                              size=10, padx=16, pady=7)
            btn.pack(side="left", padx=(0, 8))
            self.chip_buttons[name] = btn
        self.update_chips()
        if admin:
            self.button(chips, "＋ Новый товар", lambda: self.open_product_dialog(None), "primary",
                        padx=16, pady=7).pack(side="right")

        info = tk.Frame(self, bg=t["bg"])
        info.pack(fill="x", padx=24, pady=(8, 0))
        self.count_label = tk.Label(info, text="", font=self.f(10), fg=t["muted"], bg=t["bg"])
        self.count_label.pack(side="left")
        sort_box = ttk.Combobox(info, textvariable=self.sort_var, values=SORTS, state="readonly",
                                width=20, font=self.f(10))
        sort_box.pack(side="right")
        sort_box.bind("<<ComboboxSelected>>", lambda e: (sort_box.selection_clear(), self.refresh_catalog()))
        tk.Label(info, text="Сортировка:", font=self.f(10), fg=t["muted"], bg=t["bg"]).pack(side="right", padx=(0, 8))

        self.scroller = ScrollFrame(self, bg=t["bg"], on_width=self.on_catalog_width)
        self.scroller.pack(fill="both", expand=True, padx=(14, 0), pady=(6, 0))
        self.grid_frame = self.scroller.inner
        self.grid_frame.configure(padx=6, pady=6)

        self.update_header()
        self.refresh_catalog()

    def update_header(self):
        count = sum(self.cart.values())
        self.cart_btn.configure(text=f"{ico('🛒')}Корзина · {count}")
        self.profile_btn.configure(text=f"{ico('👤')}{self.user['username']} · {self.user['bonuses']} б.")

    def update_chips(self):
        t = self.t
        for name, btn in self.chip_buttons.items():
            if name == self.category:
                btn.restyle(t["accent"], t["on_accent"], t["accent_hover"], None)
            else:
                btn.restyle(t["surface"], t["text"], t["hover"], t["border"])

    def set_category(self, name):
        self.category = name
        self.update_chips()
        self.refresh_catalog()

    def on_catalog_width(self, width):
        cols = max(1, (width - 24) // (CARD_W + 20))
        if cols != self._cols:
            self._cols = cols
            self.layout_cards()

    def filtered_products(self):
        query = self.search_var.get().strip().lower()
        items = [
            p for p in self.db.products()
            if (self.category == "Все" or p["category"] == self.category)
            and (not query or query in p["name"].lower() or query in p["category"].lower())
        ]
        sort = self.sort_var.get()
        if sort == "Сначала дешёвые":
            items.sort(key=lambda p: p["price"])
        elif sort == "Сначала дорогие":
            items.sort(key=lambda p: -p["price"])
        elif sort == "По названию":
            items.sort(key=lambda p: p["name"].lower())
        return items

    def refresh_catalog(self):
        items = self.filtered_products()
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.cards = []
        if not items:
            box = tk.Frame(self.grid_frame, bg=self.t["bg"])
            box.grid(row=0, column=0, columnspan=16, pady=80)
            tk.Label(box, text="Ничего не найдено", font=self.f(16, "bold"), fg=self.t["text"],
                     bg=self.t["bg"]).pack()
            tk.Label(box, text="Попробуйте изменить запрос или выбрать другую категорию",
                     font=self.f(10), fg=self.t["muted"], bg=self.t["bg"]).pack(pady=(6, 0))
        for p in items:
            self.cards.append(self.make_card(self.grid_frame, p))
        n = len(items)
        self.count_label.configure(text=f"{n} {plural(n, ('товар', 'товара', 'товаров'))}")
        self.layout_cards()

    def layout_cards(self):
        if not self.cards:
            return
        cols = max(self._cols, 1)
        for i in range(16):
            self.grid_frame.columnconfigure(i, weight=1 if i < cols else 0)
        for i, card in enumerate(self.cards):
            card.grid(row=i // cols, column=i % cols, padx=10, pady=10, sticky="n")

    def make_card(self, parent, p):
        t = self.t
        admin = self.user["role"] == "admin"
        card = tk.Frame(parent, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"])
        tile = self.tile(card, p, CARD_W - 2, 150, 54)
        tile.pack(fill="x")
        if p["stock"] == 0:
            self.badge(tile, "Нет в наличии", t["muted"], t["bg"])
        elif p["stock"] <= LOW_STOCK:
            self.badge(tile, f"Осталось {p['stock']}", t["accent"], t["on_accent"])

        body = tk.Frame(card, bg=t["surface"], padx=14, pady=12)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=p["category"].upper(), font=self.f(8, "bold"), fg=t["muted"],
                 bg=t["surface"], anchor="w").pack(fill="x")
        tk.Label(body, text=p["name"], font=self.f(11), fg=t["text"], bg=t["surface"], anchor="nw",
                 justify="left", wraplength=CARD_W - 34, height=2).pack(fill="x", pady=(4, 6))
        tk.Label(body, text=money(p["price"]), font=self.f(16, "bold"), fg=t["text"],
                 bg=t["surface"], anchor="w").pack(fill="x")
        if p["stock"] > 0:
            buy = self.button(body, "В корзину", lambda pid=p["id"]: self.add_to_cart(pid), "primary", pady=9)
        else:
            buy = self.button(body, "Нет в наличии", None, "secondary", pady=9)
            buy.disable(t["muted"])
        buy.pack(fill="x", pady=(10, 0))
        if admin:
            row = tk.Frame(body, bg=t["surface"])
            row.pack(fill="x", pady=(8, 0))
            self.button(row, "Изменить", lambda pr=p: self.open_product_dialog(pr), "secondary",
                        size=9, pady=5).pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.button(row, "Удалить", lambda pr=p: self.delete_product(pr), "danger",
                        size=9, pady=5).pack(side="left", fill="x", expand=True, padx=(4, 0))
        return card

    # ----- корзина
    def add_to_cart(self, product_id):
        p = self.db.get_product(product_id)
        if p is None:
            self.toast("Товар больше не продаётся", ok=False)
            self.refresh_catalog()
            return
        if self.cart.get(product_id, 0) + 1 > p["stock"]:
            self.toast(f"Больше нет в наличии (на складе {p['stock']} шт.)", ok=False)
            return
        self.cart[product_id] = self.cart.get(product_id, 0) + 1
        self.update_header()
        self.toast("Добавлено в корзину")

    def cart_items(self):
        items = []
        for pid, qty in list(self.cart.items()):
            p = self.db.get_product(pid)
            if p is None or p["stock"] <= 0:
                del self.cart[pid]
                continue
            qty = min(qty, p["stock"])
            self.cart[pid] = qty
            items.append((p, qty))
        return items

    def open_cart(self):
        t = self.t
        d = self.dialog("Корзина", 700, 680)
        use_bonus = tk.BooleanVar(value=False)
        body = tk.Frame(d, bg=t["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=20)

        def change(pid, delta):
            p = self.db.get_product(pid)
            new = self.cart.get(pid, 0) + delta
            if new <= 0:
                self.cart.pop(pid, None)
            elif p is not None and new <= p["stock"]:
                self.cart[pid] = new
            self.update_header()
            render()

        def remove(pid):
            self.cart.pop(pid, None)
            self.update_header()
            render()

        def render():
            for w in body.winfo_children():
                w.destroy()
            tk.Label(body, text="Корзина", font=self.f(20, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
            items = self.cart_items()
            if not items:
                tk.Label(body, text="Здесь пока пусто", font=self.f(13), fg=t["muted"], bg=t["bg"]).pack(pady=(80, 6))
                tk.Label(body, text="Добавьте товары из каталога", font=self.f(10), fg=t["muted"],
                         bg=t["bg"]).pack()
                self.button(body, "Вернуться в каталог", d.destroy, "primary", padx=22, pady=10).pack(pady=24)
                return

            total = sum(p["price"] * q for p, q in items)
            self.reload_user()
            bonuses = self.user["bonuses"]
            max_spend = min(bonuses, int(total * MAX_BONUS_SHARE))
            if max_spend == 0:
                use_bonus.set(False)
            spend = max_spend if use_bonus.get() else 0
            paid = total - spend
            earned = int(paid * BONUS_RATE)

            footer = tk.Frame(body, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"],
                              padx=18, pady=14)
            footer.pack(side="bottom", fill="x")
            lst = ScrollFrame(body, bg=t["bg"])
            lst.pack(fill="both", expand=True, pady=(12, 12))

            for p, qty in items:
                r = tk.Frame(lst.inner, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"])
                r.pack(fill="x", pady=5, padx=(0, 10))
                self.tile(r, p, 64, 64, 26).pack(side="left", padx=10, pady=10)
                self.button(r, "✕", lambda pid=p["id"]: remove(pid), "ghost", size=10, padx=10, pady=4,
                            fg=t["muted"]).pack(side="right", padx=(0, 10))
                tk.Label(r, text=money(p["price"] * qty), font=self.f(12, "bold"), fg=t["text"],
                         bg=t["surface"], width=11, anchor="e").pack(side="right", padx=8)
                ctl = tk.Frame(r, bg=t["surface"])
                ctl.pack(side="right", padx=8)
                self.button(ctl, "−", lambda pid=p["id"]: change(pid, -1), "secondary", padx=9, pady=2).pack(side="left")
                tk.Label(ctl, text=str(qty), font=self.f(11, "bold"), fg=t["text"], bg=t["surface"],
                         width=3).pack(side="left")
                self.button(ctl, "+", lambda pid=p["id"]: change(pid, 1), "secondary", padx=9, pady=2).pack(side="left")
                info = tk.Frame(r, bg=t["surface"])
                info.pack(side="left", fill="x", expand=True)
                tk.Label(info, text=p["name"], font=self.f(11), fg=t["text"], bg=t["surface"],
                         anchor="w", justify="left", wraplength=190).pack(fill="x")
                tk.Label(info, text=f"{money(p['price'])} за шт.", font=self.f(9), fg=t["muted"],
                         bg=t["surface"], anchor="w").pack(fill="x")

            def line(label, value, bold=False, color=None):
                row = tk.Frame(footer, bg=t["surface"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=label, font=self.f(12 if bold else 10, "bold" if bold else "normal"),
                         fg=t["text"] if bold else t["muted"], bg=t["surface"]).pack(side="left")
                tk.Label(row, text=value, font=self.f(14 if bold else 10, "bold" if bold else "normal"),
                         fg=color or t["text"], bg=t["surface"]).pack(side="right")

            line("Товары", money(total))
            check = tk.Checkbutton(
                footer, text=f"Списать баллы (доступно {bonuses}, максимум {max_spend})",
                variable=use_bonus, command=render, font=self.f(10), fg=t["text"], bg=t["surface"],
                activebackground=t["surface"], activeforeground=t["text"], selectcolor=t["field"],
                highlightthickness=0, bd=0, anchor="w",
                state="normal" if max_spend > 0 else "disabled",
            )
            check.pack(fill="x", pady=4)
            if spend:
                line("Списано баллами", "− " + money(spend), color=t["ok"])
            line("Будет начислено", f"+ {earned} б.", color=t["ok"])
            tk.Frame(footer, bg=t["border"], height=1).pack(fill="x", pady=8)
            line("К оплате", money(paid), bold=True)
            err = tk.Label(footer, text="", font=self.f(9), fg=t["danger"], bg=t["surface"],
                           wraplength=600, justify="left", anchor="w")
            err.pack(fill="x")

            def checkout():
                try:
                    result = self.db.checkout(self.user["id"], dict(self.cart), use_bonus.get())
                except ValueError as exc:
                    err.config(text=str(exc))
                    return
                self.cart.clear()
                self.reload_user()
                d.destroy()
                self.update_header()
                self.refresh_catalog()
                self.show_receipt(result)

            self.button(footer, f"Оформить заказ · {money(paid)}", checkout, "primary",
                        size=11, pady=11).pack(fill="x", pady=(10, 0))

        render()

    def show_receipt(self, r):
        t = self.t
        d = self.dialog("Заказ оформлен", 420, 400)
        box = tk.Frame(d, bg=t["bg"], padx=30, pady=26)
        box.pack(fill="both", expand=True)
        tk.Label(box, text="✓", font=self.f(34, "bold"), fg="#FFFFFF", bg=t["ok"], width=3).pack()
        tk.Label(box, text="Заказ оформлен", font=self.f(18, "bold"), fg=t["text"], bg=t["bg"]).pack(pady=(14, 2))
        tk.Label(box, text=f"Заказ № {r['order_id']}", font=self.f(10), fg=t["muted"], bg=t["bg"]).pack()
        card = tk.Frame(box, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"], padx=18, pady=12)
        card.pack(fill="x", pady=18)
        for label, value, color in (
            ("Сумма заказа", money(r["total"]), t["text"]),
            ("Списано баллами", "− " + money(r["spent"]), t["text"]),
            ("Оплачено", money(r["paid"]), t["text"]),
            ("Начислено баллов", f"+ {r['earned']}", t["ok"]),
        ):
            row = tk.Frame(card, bg=t["surface"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=self.f(10), fg=t["muted"], bg=t["surface"]).pack(side="left")
            tk.Label(row, text=value, font=self.f(10, "bold"), fg=color, bg=t["surface"]).pack(side="right")
        self.button(box, "Отлично", d.destroy, "primary", size=11, pady=10).pack(fill="x")

    # ----- профиль
    def open_profile(self):
        t = self.t
        self.reload_user()
        d = self.dialog("Профиль", 600, 680)
        box = tk.Frame(d, bg=t["bg"], padx=24, pady=20)
        box.pack(fill="both", expand=True)
        head = tk.Frame(box, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"], padx=18, pady=16)
        head.pack(fill="x")
        tk.Label(head, text=self.user["username"], font=self.f(18, "bold"), fg=t["text"], bg=t["surface"]).pack(anchor="w")
        role = "Администратор" if self.user["role"] == "admin" else "Покупатель"
        tk.Label(head, text=role, font=self.f(10), fg=t["muted"], bg=t["surface"]).pack(anchor="w")
        tk.Label(head, text=f"{self.user['bonuses']} баллов", font=self.f(22, "bold"), fg=t["accent"],
                 bg=t["surface"]).pack(anchor="w", pady=(10, 0))
        tk.Label(head, text=f"1 балл = 1 ₽ · до {int(MAX_BONUS_SHARE * 100)}% от суммы заказа",
                 font=self.f(9), fg=t["muted"], bg=t["surface"]).pack(anchor="w")

        tk.Label(box, text="История заказов", font=self.f(13, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w", pady=(18, 6))
        self.button(box, "Выйти из аккаунта", lambda: (d.destroy(), self.logout()), "danger",
                    size=10, pady=9).pack(side="bottom", fill="x", pady=(12, 0))
        orders = self.db.orders(self.user["id"])
        if not orders:
            tk.Label(box, text="Заказов пока нет", font=self.f(10), fg=t["muted"], bg=t["bg"]).pack(pady=20)
            return
        lst = ScrollFrame(box, bg=t["bg"])
        lst.pack(fill="both", expand=True)
        for o, items in orders:
            when = datetime.strptime(o["created_at"], "%Y-%m-%d %H:%M").strftime("%d.%m.%Y %H:%M")
            row = tk.Frame(lst.inner, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"],
                           padx=14, pady=10)
            row.pack(fill="x", pady=4, padx=(0, 10))
            top = tk.Frame(row, bg=t["surface"])
            top.pack(fill="x")
            tk.Label(top, text=f"Заказ № {o['id']}", font=self.f(10, "bold"), fg=t["text"], bg=t["surface"]).pack(side="left")
            tk.Label(top, text=when, font=self.f(9), fg=t["muted"], bg=t["surface"]).pack(side="right")
            tk.Label(row, text=", ".join(f"{n} × {q}" for n, q in items), font=self.f(9), fg=t["muted"],
                     bg=t["surface"], wraplength=470, justify="left", anchor="w").pack(fill="x", pady=(4, 4))
            paid = o["total"] - o["bonus_spent"]
            tk.Label(row, text=f"Оплачено {money(paid)} · начислено {o['bonus_earned']} б."
                               + (f" · списано {o['bonus_spent']} б." if o["bonus_spent"] else ""),
                     font=self.f(9, "bold"), fg=t["text"], bg=t["surface"], anchor="w").pack(fill="x")

    def logout(self):
        self.user = None
        self.cart.clear()
        self.category = "Все"
        self.search_var.set("")
        self.show_auth("login")

    # ----- управление товарами (администратор)
    def open_product_dialog(self, product):
        t = self.t
        if self.user["role"] != "admin":
            return
        d = self.dialog("Новый товар" if product is None else "Редактирование товара", 460, 600)
        box = tk.Frame(d, bg=t["bg"], padx=28, pady=24)
        box.pack(fill="both", expand=True)
        tk.Label(box, text="Новый товар" if product is None else "Изменить товар",
                 font=self.f(18, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w", pady=(0, 16))

        name_v = tk.StringVar(value=product["name"] if product else "")
        price_v = tk.StringVar(value=str(product["price"]) if product else "")
        stock_v = tk.StringVar(value=str(product["stock"]) if product else "10")
        emoji_v = tk.StringVar(value=product["emoji"] if product else "")
        cat_v = tk.StringVar(value=product["category"] if product else CATEGORIES[0])

        def label(text):
            tk.Label(box, text=text, font=self.f(9, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")

        label("Название")
        f, name_entry = self.field(box, name_v)
        f.pack(fill="x", pady=(5, 12))
        label("Категория")
        combo = ttk.Combobox(box, textvariable=cat_v, values=CATEGORIES, state="readonly", font=self.f(11))
        combo.pack(fill="x", pady=(5, 12))
        row = tk.Frame(box, bg=t["bg"])
        row.pack(fill="x")
        left = tk.Frame(row, bg=t["bg"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right = tk.Frame(row, bg=t["bg"])
        right.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(left, text="Цена, ₽", font=self.f(9, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
        f, _ = self.field(left, price_v)
        f.pack(fill="x", pady=(5, 12))
        tk.Label(right, text="Остаток, шт.", font=self.f(9, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")
        f, _ = self.field(right, stock_v)
        f.pack(fill="x", pady=(5, 12))
        label("Значок-эмодзи (необязательно)")
        f, _ = self.field(box, emoji_v)
        f.pack(fill="x", pady=(5, 12))

        err = tk.Label(box, text="", font=self.f(9), fg=t["danger"], bg=t["bg"], wraplength=400,
                       justify="left", anchor="w")
        err.pack(fill="x")

        def save():
            name = name_v.get().strip()
            if not 2 <= len(name) <= 80:
                err.config(text="Название: от 2 до 80 символов")
                return
            try:
                price = int(price_v.get().replace(" ", "").replace("\u00a0", ""))
                stock = int(stock_v.get().strip())
            except ValueError:
                err.config(text="Цена и остаток должны быть целыми числами")
                return
            if price <= 0:
                err.config(text="Цена должна быть больше нуля")
                return
            if stock < 0:
                err.config(text="Остаток не может быть отрицательным")
                return
            self.db.save_product(product["id"] if product else None, name, cat_v.get(), price, stock,
                                 emoji_v.get().strip()[:4])
            d.destroy()
            self.refresh_catalog()
            self.toast("Товар добавлен" if product is None else "Изменения сохранены")

        btns = tk.Frame(box, bg=t["bg"])
        btns.pack(side="bottom", fill="x")
        self.button(btns, "Отмена", d.destroy, "secondary", pady=10).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.button(btns, "Сохранить", save, "primary", pady=10).pack(side="left", fill="x", expand=True, padx=(6, 0))
        name_entry.focus_set()
        name_entry.bind("<Return>", lambda e: save())

    def delete_product(self, product):
        if self.user["role"] != "admin":
            return
        if messagebox.askyesno("Удаление товара", f"Удалить «{product['name']}» из каталога?", parent=self):
            self.db.delete_product(product["id"])
            self.cart.pop(product["id"], None)
            self.update_header()
            self.refresh_catalog()
            self.toast("Товар удалён")


def main():
    if sys.platform == "win32":  # чёткий текст на экранах с масштабированием
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = SportStoreApp()
    app.mainloop()


if __name__ == "__main__":
    main()