"""SPORT STORE — настольное приложение магазина спорттоваров (Tkinter + MySQL).

Установка:  pip install -r requirements.txt
Запуск:     python app.py
При первом запуске приложение попросит данные для подключения к MySQL и само создаст таблицы.
Первый зарегистрированный пользователь становится администратором.
"""

import base64
import configparser
import hashlib
import hmac
import io
import os
import re
import sys
import tkinter as tk
import warnings
from datetime import datetime
from tkinter import filedialog
from tkinter import font as tkfont
from tkinter import messagebox, ttk

try:
    import mysql.connector
    from mysql.connector import errorcode
except ImportError:  # сообщение покажем при запуске, см. main()
    mysql = None

try:  # Pillow нужен только для фото товаров; без него остальное приложение работает
    from PIL import Image, ImageOps
    _LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
except ImportError:
    Image = ImageOps = _LANCZOS = None

APP_NAME = "SPORT STORE"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("SPORT_STORE_CONFIG") or os.path.join(APP_DIR, "config.ini")
SCHEMA_PATH = os.path.join(APP_DIR, "schema.sql")

BONUS_RATE = 0.05        # 5% от оплаченной суммы возвращается баллами
MAX_BONUS_SHARE = 0.30   # баллами можно оплатить не больше 30% заказа
WELCOME_BONUS = 500      # приветственные баллы новому покупателю
LOW_STOCK = 3            # «Осталось N» показываем, когда на складе <= этого числа
CARD_W = 232

PHOTO_MAX_SIDE = 1000                 # в базу кладём фото не больше 1000 px по длинной стороне
PHOTO_MAX_BYTES = 20 * 1024 * 1024    # исходный файл не больше 20 МБ
PHOTO_MAX_PIXELS = 60_000_000         # защита от «бомб» — гигантских картинок, которые съедают всю память
PHOTO_GLOB = "*.jpg *.jpeg *.png *.webp *.bmp *.gif"

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

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


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


def prepare_image(path):
    """Читает файл с картинкой и возвращает байты JPEG, готовые к сохранению в базе.

    Фото уменьшается, поворачивается по EXIF (снимки с телефона), прозрачность заменяется белым фоном.
    Все метаданные, включая геолокацию съёмки, отбрасываются. Ошибки — ValueError с понятным текстом.
    """
    if Image is None:
        raise ValueError("Для работы с фото нужна библиотека Pillow.\nУстановите её: pip install -r requirements.txt")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise ValueError("Не удалось прочитать файл")
    if size == 0:
        raise ValueError("Файл пустой")
    if size > PHOTO_MAX_BYTES:
        raise ValueError(f"Файл слишком большой (максимум {PHOTO_MAX_BYTES // 2 ** 20} МБ)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            old_limit, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, PHOTO_MAX_PIXELS
            try:
                with Image.open(path) as img:
                    img.load()
                    img = ImageOps.exif_transpose(img)
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        rgba = img.convert("RGBA")
                        img = Image.new("RGB", rgba.size, (255, 255, 255))
                        img.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        img = img.convert("RGB")
            finally:
                Image.MAX_IMAGE_PIXELS = old_limit
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Слишком большая картинка. Уменьшите её и попробуйте снова.")
    except Exception:
        raise ValueError("Не удалось открыть файл как изображение.\nПоддерживаются JPG, PNG, WEBP, BMP и GIF.")
    img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), _LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------------- config

class Config:
    """Настройки из config.ini. Переменные окружения SPORT_STORE_MYSQL_* имеют приоритет."""

    DEFAULTS = {
        "mysql": {"host": "127.0.0.1", "port": "3306", "user": "root", "password": "",
                  "database": "sport_store"},
        "ui": {"theme": DEFAULT_THEME, "accent": DEFAULT_ACCENT},
    }

    def __init__(self, path):
        self.path = path
        self.parser = configparser.ConfigParser(interpolation=None)
        self.parser.read_dict(self.DEFAULTS)
        self.file_existed = os.path.exists(path)
        try:
            self.parser.read(path, encoding="utf-8")
        except (configparser.Error, OSError):
            pass

    def get(self, section, key):
        return self.parser.get(section, key, fallback=self.DEFAULTS[section][key])

    def set(self, section, key, value):
        self.parser.set(section, key, str(value))

    def env_overrides(self):
        return {k: os.environ["SPORT_STORE_MYSQL_" + k.upper()]
                for k in self.DEFAULTS["mysql"] if "SPORT_STORE_MYSQL_" + k.upper() in os.environ}

    def mysql(self):
        values = {k: self.get("mysql", k) for k in self.DEFAULTS["mysql"]}
        values.update(self.env_overrides())
        try:
            values["port"] = int(values["port"])
        except ValueError:
            values["port"] = 3306
        return values

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                self.parser.write(fh)
            try:
                os.chmod(self.path, 0o600)  # в файле лежит пароль от БД
            except OSError:
                pass
        except OSError:
            pass


# --------------------------------------------------------------------------- database

def friendly_db_error(exc, cfg=None):
    """Понятное сообщение об ошибке MySQL для пользователя."""
    errno = getattr(exc, "errno", None)
    host = f"{cfg['host']}:{cfg['port']}" if cfg else "серверу"
    if errno in (2003, 2002, 2005, 2013, 2055):
        return (f"Не удалось подключиться к MySQL ({host}). Проверьте, что сервер запущен, "
                f"а адрес и порт указаны верно.")
    if errno == 1045:
        return "MySQL отклонил логин или пароль."
    if errno == 1044:
        return "У этого пользователя нет прав на указанную базу данных."
    if errno == 1049:
        return "Базы данных с таким именем нет, а прав на её создание у пользователя нет."
    return f"Ошибка MySQL: {exc}"


class Database:
    """Слой данных поверх MySQL. Одно соединение, автоподключение при обрыве."""

    def __init__(self, cfg, seed=True):
        self.cfg = cfg
        if not DB_NAME_RE.match(cfg["database"]):
            raise ValueError("Имя базы: только латиница, цифры и _ (до 64 символов)")
        self.conn = self._connect()
        self._init_schema()
        if seed and self._one("SELECT COUNT(*) AS n FROM products")["n"] == 0:
            cur = self.conn.cursor()
            cur.executemany(
                "INSERT INTO products(name, category, price, stock, emoji) VALUES (%s,%s,%s,%s,%s)",
                SEED_PRODUCTS,
            )
            cur.close()

    # ----- подключение
    def _connect(self):
        cfg = self.cfg
        base = dict(host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"],
                    charset="utf8mb4", collation="utf8mb4_unicode_ci", connection_timeout=8,
                    autocommit=True)
        try:
            return mysql.connector.connect(database=cfg["database"], **base)
        except mysql.connector.Error as exc:
            if exc.errno != errorcode.ER_BAD_DB_ERROR:
                raise
        conn = mysql.connector.connect(**base)  # базы нет — пробуем создать
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE `{cfg['database']}` CHARACTER SET utf8mb4 "
                    f"COLLATE utf8mb4_unicode_ci")
        cur.close()
        conn.close()
        # переподключаемся уже с именем базы, чтобы автопереподключение потом тоже её выбирало
        return mysql.connector.connect(database=cfg["database"], **base)

    def _init_schema(self):
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            text = "\n".join(line for line in fh if not line.lstrip().startswith("--"))
        cur = self.conn.cursor()
        for statement in text.split(";"):
            if statement.strip():
                cur.execute(statement)
        cur.close()

    def close(self):
        try:
            self.conn.close()
        except mysql.connector.Error:
            pass

    def _cursor(self):
        self.conn.ping(reconnect=True, attempts=2, delay=1)
        return self.conn.cursor(dictionary=True)

    def _all(self, sql, params=()):
        cur = self._cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def _one(self, sql, params=()):
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _run(self, sql, params=()):
        cur = self._cursor()
        try:
            cur.execute(sql, params)
            return cur.lastrowid
        finally:
            cur.close()

    # ----- пользователи
    def user_count(self):
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]

    def get_user(self, user_id):
        return self._one("SELECT * FROM users WHERE id=%s", (user_id,))

    def register(self, username, password):
        is_first = self.user_count() == 0
        salt = os.urandom(16)
        try:
            new_id = self._run(
                "INSERT INTO users(username, pw_hash, salt, role, bonuses) VALUES (%s,%s,%s,%s,%s)",
                (username.lower(), hash_password(password, salt), salt,
                 "admin" if is_first else "customer", 0 if is_first else WELCOME_BONUS),
            )
        except mysql.connector.IntegrityError:
            raise ValueError("Этот логин уже занят")
        return self.get_user(new_id)

    def authenticate(self, username, password):
        row = self._one("SELECT * FROM users WHERE username=%s", (username.lower(),))
        if row is None:
            return None
        expected = hash_password(password, bytes(row["salt"]))
        if not hmac.compare_digest(bytes(row["pw_hash"]), expected):
            return None
        return row

    def set_user_appearance(self, user_id, theme, accent):
        self._run("UPDATE users SET theme=%s, accent=%s WHERE id=%s", (theme, accent, user_id))

    # ----- товары
    # image_ver — версия фото (NULL, если фото нет); сами байты не тянем, пока они не понадобятся
    PRODUCT_SELECT = ("SELECT p.*, i.updated_at AS image_ver FROM products p "
                      "LEFT JOIN product_images i ON i.product_id = p.id")

    def products(self):
        return self._all(self.PRODUCT_SELECT + " ORDER BY p.id")

    def get_product(self, product_id):
        return self._one(self.PRODUCT_SELECT + " WHERE p.id=%s", (product_id,))

    def save_product(self, product_id, name, category, price, stock, emoji):
        """Создаёт или обновляет товар и возвращает его id."""
        if product_id is None:
            return self._run("INSERT INTO products(name, category, price, stock, emoji) VALUES (%s,%s,%s,%s,%s)",
                             (name, category, price, stock, emoji))
        self._run("UPDATE products SET name=%s, category=%s, price=%s, stock=%s, emoji=%s WHERE id=%s",
                  (name, category, price, stock, emoji, product_id))
        return product_id

    def delete_product(self, product_id):
        self._run("DELETE FROM products WHERE id=%s", (product_id,))  # фото удалится каскадом

    # ----- фото товаров
    def set_product_image(self, product_id, data):
        """Сохраняет (или заменяет) фото. Новая версия ставится автоматически."""
        self._run("REPLACE INTO product_images(product_id, data, updated_at) VALUES (%s,%s,NOW(6))",
                  (product_id, data))

    def remove_product_image(self, product_id):
        self._run("DELETE FROM product_images WHERE product_id=%s", (product_id,))

    def get_images(self, product_ids):
        """{product_id: (версия, байты JPEG)} одним запросом."""
        ids = [int(i) for i in product_ids]
        if not ids:
            return {}
        rows = self._all(
            "SELECT product_id, updated_at AS ver, data FROM product_images WHERE product_id IN (%s)"
            % ",".join(["%s"] * len(ids)), ids)
        return {r["product_id"]: (r["ver"], bytes(r["data"])) for r in rows}

    # ----- заказы
    def checkout(self, user_id, cart, use_bonuses):
        """Оформляет заказ одной транзакцией. cart: {product_id: qty}.

        Строки пользователя и товаров блокируются (SELECT ... FOR UPDATE), поэтому два покупателя,
        одновременно берущие последний товар, не смогут «продать» его дважды.
        """
        self.conn.ping(reconnect=True, attempts=2, delay=1)
        cur = self.conn.cursor(dictionary=True)
        try:
            self.conn.start_transaction()
            cur.execute("SELECT id, bonuses FROM users WHERE id=%s FOR UPDATE", (user_id,))
            user = cur.fetchone()
            if user is None:
                raise ValueError("Аккаунт не найден — войдите заново")
            lines, total = [], 0
            for pid in sorted(cart):  # единый порядок блокировок — без взаимных зависаний
                qty = cart[pid]
                cur.execute("SELECT * FROM products WHERE id=%s FOR UPDATE", (pid,))
                p = cur.fetchone()
                if p is None:
                    raise ValueError("Один из товаров больше не продаётся — обновите корзину")
                if p["stock"] < qty:
                    raise ValueError(f"«{p['name']}»: на складе осталось {p['stock']} шт.")
                lines.append((p, qty))
                total += p["price"] * qty
            spend = min(user["bonuses"], int(total * MAX_BONUS_SHARE)) if use_bonuses else 0
            paid = total - spend
            earned = int(paid * BONUS_RATE)
            cur.execute(
                "INSERT INTO orders(user_id, total, bonus_spent, bonus_earned) VALUES (%s,%s,%s,%s)",
                (user_id, total, spend, earned),
            )
            order_id = cur.lastrowid
            for p, qty in lines:
                cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, p["id"]))
                cur.execute(
                    "INSERT INTO order_items(order_id, product_id, name, price, qty) VALUES (%s,%s,%s,%s,%s)",
                    (order_id, p["id"], p["name"], p["price"], qty),
                )
            cur.execute("UPDATE users SET bonuses = bonuses - %s + %s WHERE id=%s", (spend, earned, user_id))
            self.conn.commit()
        except BaseException:
            try:
                self.conn.rollback()
            except mysql.connector.Error:
                pass
            raise
        finally:
            cur.close()
        return dict(order_id=order_id, total=total, spent=spend, paid=paid, earned=earned)

    def orders(self, user_id, limit=30):
        result = []
        for o in self._all("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                           (user_id, int(limit))):
            items = self._all("SELECT name, qty FROM order_items WHERE order_id=%s ORDER BY id", (o["id"],))
            result.append((o, [(i["name"], i["qty"]) for i in items]))
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
        self.title(APP_NAME)
        self.geometry("1200x800")
        self.minsize(920, 600)
        self.family = pick_font_family(self)
        self.style = ttk.Style(self)

        self.config_file = Config(CONFIG_PATH)
        self.db = None
        self.theme_name = self.config_file.get("ui", "theme")
        if self.theme_name not in THEMES:
            self.theme_name = DEFAULT_THEME
        self.accent = self.config_file.get("ui", "accent")
        if not HEX_RE.match(self.accent):
            self.accent = DEFAULT_ACCENT
        self.user = None
        self.cart = {}
        self.category = "Все"
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value=SORTS[0])
        self.cards, self._cols, self._toast = [], 0, None
        self.chip_buttons = {}
        self._pil, self._photos, self._photo_dir = {}, {}, None  # кэши фото и последняя папка выбора

        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.apply_theme()
        self.connect_on_start()

    def connect_on_start(self):
        """Пробуем подключиться по сохранённым настройкам; если не вышло — показываем форму."""
        if not self.config_file.file_existed and not self.config_file.env_overrides():
            self.show_connect()  # первый запуск: сначала нужно указать, куда подключаться
            return
        cfg = self.config_file.mysql()
        try:
            self.db = Database(cfg)
        except (mysql.connector.Error, ValueError, OSError) as exc:
            self.show_connect(error=friendly_db_error(exc, cfg) if isinstance(exc, mysql.connector.Error)
                              else str(exc))
            return
        self.render()

    def report_callback_exception(self, exc, val, tb):
        """Потеря связи с MySQL во время работы — сообщение вместо traceback в консоли."""
        if mysql is not None and isinstance(val, mysql.connector.Error):
            messagebox.showerror(APP_NAME, friendly_db_error(val) + "\n\nДействие не выполнено, "
                                 "попробуйте ещё раз.", parent=self)
        else:
            super().report_callback_exception(exc, val, tb)

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
        self.config_file.set("ui", "theme", self.theme_name)  # запоминаем на этом компьютере
        self.config_file.set("ui", "accent", self.accent)
        self.config_file.save()
        if self.user is not None and self.db is not None:
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

    # ----- фото товаров
    def _remember(self, key, img):
        self._pil[key] = img
        while len(self._pil) > 120:  # ограничиваем память: выкидываем самые старые
            self._pil.pop(next(iter(self._pil)))

    @staticmethod
    def _decode(data):
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                return im.convert("RGB")
        except Exception:
            return None  # повреждённые данные в базе — покажем заглушку

    def _fit_photo(self, img, w, h):
        """Вписывает картинку в w×h с обрезкой по краям (как object-fit: cover) и делает PhotoImage."""
        fitted = ImageOps.fit(img, (w, h), method=_LANCZOS, centering=(0.5, 0.5))
        buf = io.BytesIO()
        fitted.save(buf, "PNG")
        return tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()))

    def photo_from_bytes(self, data, w, h):
        if Image is None:
            return None
        img = self._decode(data)
        return self._fit_photo(img, w, h) if img is not None else None

    def prefetch_photos(self, products):
        """Одним запросом подгружает фото тех товаров, которых ещё нет в кэше."""
        if Image is None:
            return
        wanted = {p["id"]: p.get("image_ver") for p in products
                  if p.get("image_ver") and (p["id"], p["image_ver"]) not in self._pil}
        if not wanted:
            return
        for pid, (ver, data) in self.db.get_images(list(wanted)).items():
            img = self._decode(data)
            if img is not None:
                self._remember((pid, ver), img)
                self._remember((pid, wanted[pid]), img)

    def photo_for(self, product, w, h):
        """PhotoImage с фото товара нужного размера или None, если фото нет."""
        ver = product.get("image_ver")
        if ver is None or Image is None:
            return None
        key = (product["id"], ver, w, h)
        photo = self._photos.get(key)
        if photo is None:
            if (product["id"], ver) not in self._pil:
                self.prefetch_photos([product])
            img = self._pil.get((product["id"], ver))
            if img is None:
                return None
            if len(self._photos) > 300:
                self._photos.clear()
            photo = self._photos[key] = self._fit_photo(img, w, h)
        return photo

    def is_admin(self):
        """Роль проверяется заново по базе: права могли поменяться, пока приложение было открыто."""
        if self.user is None:
            return False
        fresh = self.db.get_user(self.user["id"])
        return bool(fresh and fresh["role"] == "admin")

    def choose_photo_file(self, parent=None):
        path = filedialog.askopenfilename(
            parent=parent or self, title="Выберите фото товара",
            initialdir=self._photo_dir or os.path.expanduser("~"),
            filetypes=[("Изображения", PHOTO_GLOB), ("Все файлы", "*.*")])
        if not path:
            return None
        self._photo_dir = os.path.dirname(path)
        return path

    def read_photo(self, path, parent):
        """Готовит файл к сохранению; при ошибке сообщает о ней и возвращает None."""
        for w in (self, parent):
            w.configure(cursor="watch")
        parent.update_idletasks()
        try:
            return prepare_image(path)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=parent)
            return None
        finally:
            for w in (self, parent):
                w.configure(cursor="")

    def change_product_photo(self, product):
        """Быстрая смена фото прямо с карточки в каталоге (только администратор)."""
        if not self.is_admin():
            self.toast("Менять фото может только администратор", ok=False)
            return
        path = self.choose_photo_file()
        if not path:
            return
        data = self.read_photo(path, self)
        if data is None:
            return
        try:
            self.db.set_product_image(product["id"], data)
        except mysql.connector.IntegrityError:
            self.toast("Этот товар уже удалён", ok=False)
        else:
            self.toast("Фото обновлено")
        self.refresh_catalog()

    def tile_pill(self, canvas, text, command, w, h):
        """Кнопка-«таблетка» в правом нижнем углу плитки (для администратора)."""
        pw = len(text) * 7 + 24
        x2, y2 = w - 10, h - 10
        canvas.create_rectangle(x2 - pw, y2 - 24, x2, y2, fill="#16181D", outline="", tags="pill")
        canvas.create_text(x2 - pw / 2, y2 - 12, text=text, fill="#FFFFFF", font=self.f(9, "bold"), tags="pill")
        canvas.tag_bind("pill", "<Button-1>", lambda e: command())
        canvas.tag_bind("pill", "<Enter>", lambda e: canvas.configure(cursor="hand2"))
        canvas.tag_bind("pill", "<Leave>", lambda e: canvas.configure(cursor=""))

    def tile(self, parent, product, w, h, size):
        emoji, light, dark = CATEGORY_STYLE.get(product["category"], ("🏅", "#EEEEEE", "#2A2A2A"))
        canvas = tk.Canvas(parent, width=w, height=h, bd=0, highlightthickness=0,
                           bg=light if self.theme_name == "light" else dark)
        photo = self.photo_for(product, w, h)
        if photo is not None:
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas._photo = photo  # Tk не хранит ссылку на картинку — держим её сами
        elif USE_EMOJI:
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
        h = min(h, max(420, self.winfo_screenheight() - 110))  # на невысоких экранах окно не вылезает за край
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
        if self.db is None:
            self.show_connect()
        elif self.user is None:
            self.show_auth()
        else:
            self.show_shop()

    def on_close(self):
        if self.db is not None:
            self.db.close()
        self.destroy()

    # ----- экран подключения к MySQL
    def show_connect(self, error=None):
        t = self.t
        self.clear()
        root = tk.Frame(self, bg=t["bg"])
        root.pack(fill="both", expand=True)
        tk.Frame(root, bg=t["accent"], height=4).pack(fill="x", side="top")
        card = tk.Frame(root, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"],
                        padx=40, pady=34)
        card.place(relx=0.5, rely=0.5, anchor="center")

        logo = tk.Frame(card, bg=t["surface"])
        logo.pack(anchor="w")
        tk.Label(logo, text="SPORT", font=self.f(18, "bold italic"), fg=t["accent"], bg=t["surface"]).pack(side="left")
        tk.Label(logo, text="STORE", font=self.f(18, "bold italic"), fg=t["text"], bg=t["surface"]).pack(side="left", padx=(5, 0))
        tk.Label(card, text="Подключение к базе данных", font=self.f(18, "bold"), fg=t["text"],
                 bg=t["surface"]).pack(anchor="w", pady=(18, 0))
        tk.Label(card, text="Укажите данные вашего сервера MySQL. Если базы с таким именем ещё нет, "
                            "приложение создаст её и все таблицы само.",
                 font=self.f(10), fg=t["muted"], bg=t["surface"], wraplength=400, justify="left"
                 ).pack(anchor="w", pady=(4, 20))

        cfg = self.config_file.mysql()
        host_v, port_v = tk.StringVar(value=cfg["host"]), tk.StringVar(value=str(cfg["port"]))
        user_v, pass_v = tk.StringVar(value=cfg["user"]), tk.StringVar(value=cfg["password"])
        db_v = tk.StringVar(value=cfg["database"])

        def label(parent, text):
            tk.Label(parent, text=text, font=self.f(9, "bold"), fg=t["text"], bg=t["surface"]).pack(anchor="w")

        row = tk.Frame(card, bg=t["surface"])
        row.pack(fill="x")
        left = tk.Frame(row, bg=t["surface"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right = tk.Frame(row, bg=t["surface"], width=110)
        right.pack(side="left", padx=(8, 0))
        label(left, "Сервер")
        f, host_entry = self.field(left, host_v)
        f.pack(fill="x", pady=(5, 14))
        label(right, "Порт")
        f, _ = self.field(right, port_v)
        f.pack(fill="x", pady=(5, 14))
        label(card, "Пользователь")
        f, _ = self.field(card, user_v)
        f.pack(fill="x", pady=(5, 14))
        label(card, "Пароль")
        f, pass_entry = self.field(card, pass_v, show="•")
        f.pack(fill="x", pady=(5, 14))
        label(card, "База данных")
        f, db_entry = self.field(card, db_v)
        f.pack(fill="x", pady=(5, 14))

        status = tk.Label(card, text=error or "", font=self.f(9), fg=t["danger"], bg=t["surface"],
                          wraplength=400, justify="left", anchor="w")
        status.pack(fill="x", pady=(0, 8))

        def connect(_event=None):
            values = {"host": host_v.get().strip() or "127.0.0.1", "user": user_v.get().strip(),
                      "password": pass_v.get(), "database": db_v.get().strip()}
            try:
                values["port"] = int(port_v.get().strip())
            except ValueError:
                status.config(text="Порт должен быть числом (обычно 3306)", fg=t["danger"])
                return
            status.config(text="Подключаюсь…", fg=t["muted"])
            self.update_idletasks()
            try:
                db = Database(values)
            except mysql.connector.Error as exc:
                status.config(text=friendly_db_error(exc, values), fg=t["danger"])
                return
            except ValueError as exc:
                status.config(text=str(exc), fg=t["danger"])
                return
            self.db = db
            for key, value in values.items():
                self.config_file.set("mysql", key, value)
            self.config_file.save()
            self.render()

        self.button(card, "Подключиться", connect, size=11, pady=11).pack(fill="x")
        for entry in (host_entry, pass_entry, db_entry):
            entry.bind("<Return>", connect)
        pass_entry.focus_set() if cfg["host"] and cfg["user"] else host_entry.focus_set()

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
        self.prefetch_photos(items)
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
        if admin:
            self.tile_pill(tile, "Сменить фото" if p.get("image_ver") else "Добавить фото",
                           lambda pr=p: self.change_product_photo(pr), CARD_W - 2, 150)

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
            self.prefetch_photos([p for p, _ in items])
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
            created = o["created_at"]
            when = (created if isinstance(created, datetime)
                    else datetime.strptime(str(created)[:16], "%Y-%m-%d %H:%M")).strftime("%d.%m.%Y %H:%M")
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
        d = self.dialog("Новый товар" if product is None else "Редактирование товара", 460, 660)
        box = tk.Frame(d, bg=t["bg"], padx=28, pady=24)
        box.pack(fill="both", expand=True)
        btns = tk.Frame(box, bg=t["bg"])  # упаковываем первыми: на невысоком экране обрежется содержимое, а не кнопки
        btns.pack(side="bottom", fill="x")
        tk.Label(box, text="Новый товар" if product is None else "Изменить товар",
                 font=self.f(18, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w", pady=(0, 14))

        name_v = tk.StringVar(value=product["name"] if product else "")
        price_v = tk.StringVar(value=str(product["price"]) if product else "")
        stock_v = tk.StringVar(value=str(product["stock"]) if product else "10")
        emoji_v = tk.StringVar(value=product["emoji"] if product else "")
        cat_v = tk.StringVar(value=product["category"] if product else CATEGORIES[0])
        photo = {"data": None, "remove": False}  # выбранное, но ещё не сохранённое фото / пометка «убрать»

        def label(text):
            tk.Label(box, text=text, font=self.f(9, "bold"), fg=t["text"], bg=t["bg"]).pack(anchor="w")

        # ----- фото
        label("Фото товара")
        photo_row = tk.Frame(box, bg=t["bg"])
        photo_row.pack(fill="x", pady=(6, 14))
        preview_holder = tk.Frame(photo_row, bg=t["bg"])
        preview_holder.pack(side="left")
        side = tk.Frame(photo_row, bg=t["bg"])
        side.pack(side="left", fill="both", expand=True, padx=(16, 0))
        tk.Label(side, text="JPG, PNG, WEBP, BMP или GIF до 20 МБ.\nФото сожмётся автоматически.",
                 font=self.f(9), fg=t["muted"], bg=t["bg"], justify="left", anchor="w").pack(fill="x")
        photo_buttons = tk.Frame(side, bg=t["bg"])
        photo_buttons.pack(fill="x", pady=(10, 0))

        def has_photo():
            if photo["data"] is not None:
                return True
            return bool(product and product.get("image_ver") and not photo["remove"])

        def render_photo():
            for w in preview_holder.winfo_children() + photo_buttons.winfo_children():
                w.destroy()
            stand_in = {"id": 0, "category": cat_v.get(), "name": name_v.get().strip() or "?",
                        "emoji": emoji_v.get().strip(), "image_ver": None}
            if photo["data"] is not None:
                canvas = self.tile(preview_holder, stand_in, 168, 112, 36)
                pic = self.photo_from_bytes(photo["data"], 168, 112)
                if pic is not None:
                    canvas.create_image(0, 0, image=pic, anchor="nw")
                    canvas._photo = pic
            elif product is not None and product.get("image_ver") and not photo["remove"]:
                canvas = self.tile(preview_holder, product, 168, 112, 36)
            else:
                canvas = self.tile(preview_holder, stand_in, 168, 112, 36)
            canvas.configure(highlightthickness=1, highlightbackground=t["border"])
            canvas.pack()
            self.button(photo_buttons, "Заменить фото…" if has_photo() else "Выбрать фото…", choose,
                        "secondary", size=9, pady=7).pack(anchor="w")
            if has_photo():
                self.button(photo_buttons, "Убрать фото", remove, "danger", size=9, pady=7
                            ).pack(anchor="w", pady=(6, 0))

        def choose():
            path = self.choose_photo_file(parent=d)
            if not path:
                return
            data = self.read_photo(path, d)
            if data is None:
                return
            err.config(text="")
            photo["data"], photo["remove"] = data, False
            render_photo()

        def remove():
            photo["data"], photo["remove"] = None, True
            render_photo()

        # ----- основные поля
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
        label("Значок-эмодзи (показывается, пока нет фото)")
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
                price = int(price_v.get().replace(" ", "").replace(" ", ""))
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
            if not self.is_admin():
                err.config(text="Недостаточно прав: менять товары может только администратор")
                return
            product_id = self.db.save_product(product["id"] if product else None, name, cat_v.get(), price,
                                              stock, emoji_v.get().strip()[:4])
            photo_error = None
            try:
                if photo["data"] is not None:
                    self.db.set_product_image(product_id, photo["data"])
                elif photo["remove"]:
                    self.db.remove_product_image(product_id)
            except mysql.connector.Error as exc:
                photo_error = friendly_db_error(exc)
            d.destroy()
            self.refresh_catalog()
            if photo_error:
                messagebox.showwarning(APP_NAME, "Товар сохранён, но фото загрузить не удалось:\n" + photo_error,
                                       parent=self)
            else:
                self.toast("Товар добавлен" if product is None else "Изменения сохранены")

        self.button(btns, "Отмена", d.destroy, "secondary", pady=10).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.button(btns, "Сохранить", save, "primary", pady=10).pack(side="left", fill="x", expand=True, padx=(6, 0))
        render_photo()
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
    if mysql is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "Не установлен драйвер MySQL.\n\nВыполните в терминале:\n    pip install -r requirements.txt\n\n"
            "и запустите приложение снова.")
        return
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
