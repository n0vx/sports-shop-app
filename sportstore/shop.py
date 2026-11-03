"""Каталог, фото, корзина, заказы, профиль и настройки оформления."""

from flask import (Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)

from .auth import current_url, login_required, safe_next
from .constants import (BONUS_RATE, CATEGORIES, MAX_BONUS_SHARE, MAX_CART_QTY, SORTS)
from .context import current_appearance
from .ctx import get_db, wants_json
from .db import image_token
from .theme import DEFAULT_ACCENT, DEFAULT_THEME, accent_vars, valid_accent, valid_theme

bp = Blueprint("shop", __name__)


# --------------------------------------------------------------------------- каталог

@bp.get("/")
def index():
    category = request.args.get("cat", "")
    category = category if category in CATEGORIES else None
    query = request.args.get("q", "").strip()[:80]
    sort = request.args.get("sort", "popular")
    sort = sort if sort in dict(SORTS) else "popular"
    products = get_db().catalog(category, query, sort)
    return render_template("shop/index.html", products=products, cat=category, q=query, sort=sort)


@bp.get("/product/<int:pid>/photo")
def product_photo(pid):
    row = get_db().get_image(pid)
    if row is None:
        abort(404)
    ver, data = row
    token = image_token(ver)
    resp = Response(data, mimetype="image/jpeg")
    resp.set_etag(token)
    # версия в адресе (?v=...) меняется при замене фото, поэтому такое фото можно кэшировать «навсегда»
    resp.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if request.args.get("v") == token
                                     else "no-cache")
    return resp.make_conditional(request)


# --------------------------------------------------------------------------- корзина

def read_cart():
    cart = {}
    for key, qty in (session.get("cart") or {}).items():
        try:
            pid, qty = int(key), int(qty)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            cart[pid] = min(qty, MAX_CART_QTY)
    return cart


def write_cart(cart):
    session["cart"] = {str(pid): qty for pid, qty in cart.items() if qty > 0}


def cart_lines():
    """Строки корзины с актуальными ценами; исчезнувшие и закончившиеся товары убираются, количество
    ограничивается остатком. Возвращает (строки, сумма, сколько позиций убрано)."""
    cart = read_cart()
    products = get_db().products_by_ids(cart)
    lines, total, removed = [], 0, 0
    for pid, qty in list(cart.items()):
        p = products.get(pid)
        if p is None or p["stock"] <= 0:
            del cart[pid]
            removed += 1
            continue
        qty = cart[pid] = min(qty, p["stock"])
        lines.append({"p": p, "qty": qty, "sum": p["price"] * qty})
        total += p["price"] * qty
    if cart != read_cart():
        write_cart(cart)
    return lines, total, removed


def bonus_plan(total, balance, use_bonus):
    max_spend = min(balance, int(total * MAX_BONUS_SHARE))
    spend = max_spend if use_bonus and max_spend > 0 else 0
    paid = total - spend
    return {"max_spend": max_spend, "spend": spend, "paid": paid, "earned": int(paid * BONUS_RATE)}


def respond(ok, message, status=200, **extra):
    """JSON для fetch-запросов, иначе всплывающее сообщение и возврат на страницу."""
    if wants_json():
        return jsonify(ok=ok, message=message, count=sum(read_cart().values()), **extra), status
    flash(message, "ok" if ok else "error")
    return redirect(safe_next(request.form.get("next")) or url_for("shop.index"))


@bp.post("/cart/add/<int:pid>")
def cart_add(pid):
    p = get_db().get_product(pid)
    if p is None:
        return respond(False, "Этот товар больше не продаётся", 404)
    cart = read_cart()
    if cart.get(pid, 0) + 1 > p["stock"]:
        return respond(False, "Больше нет в наличии" if p["stock"] == 0 else
                       f"Больше нет в наличии (на складе {p['stock']} шт.)", 409)
    cart[pid] = min(cart.get(pid, 0) + 1, MAX_CART_QTY)
    write_cart(cart)
    return respond(True, "Добавлено в корзину")


@bp.post("/cart/update/<int:pid>")
def cart_update(pid):
    cart = read_cart()
    if pid not in cart:
        return redirect(url_for("shop.cart"))
    try:
        qty = int(request.form.get("qty", "1"))
    except ValueError:
        qty = cart[pid]
    p = get_db().get_product(pid)
    if qty <= 0 or p is None:
        cart.pop(pid, None)
    else:
        cart[pid] = min(qty, p["stock"], MAX_CART_QTY)
        if qty > p["stock"]:
            flash(f"На складе только {p['stock']} шт.", "error")
    write_cart(cart)
    return redirect(url_for("shop.cart", bonus=request.form.get("bonus") or None))


@bp.post("/cart/remove/<int:pid>")
def cart_remove(pid):
    cart = read_cart()
    cart.pop(pid, None)
    write_cart(cart)
    return redirect(url_for("shop.cart", bonus=request.form.get("bonus") or None))


@bp.get("/cart")
def cart():
    lines, total, removed = cart_lines()
    if removed:
        flash("Некоторые товары закончились или сняты с продажи — мы убрали их из корзины", "info")
    balance = g.user["bonuses"] if g.user else 0
    use_bonus = request.args.get("bonus") == "1"
    plan = bonus_plan(total, balance, use_bonus)
    return render_template("shop/cart.html", lines=lines, total=total, balance=balance,
                           use_bonus=use_bonus and plan["spend"] > 0, **plan)


@bp.post("/cart/checkout")
@login_required
def checkout():
    cart = read_cart()
    try:
        result = get_db().checkout(g.user["id"], cart, request.form.get("use_bonus") == "1")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("shop.cart"))
    write_cart({})
    return redirect(url_for("shop.order", oid=result["order_id"]))


# --------------------------------------------------------------------------- заказы и профиль

@bp.get("/orders/<int:oid>")
@login_required
def order(oid):
    found = get_db().get_order(oid, g.user["id"])
    if found is None:
        abort(404)
    return render_template("shop/order.html", order=found)


@bp.get("/profile")
@login_required
def profile():
    return render_template("shop/profile.html", orders=get_db().orders(g.user["id"]))


# --------------------------------------------------------------------------- оформление

@bp.post("/appearance")
def appearance():
    data = request.get_json(silent=True) or request.form
    theme, accent = current_appearance()
    if data.get("reset"):
        theme, accent = DEFAULT_THEME, DEFAULT_ACCENT
    else:
        theme = valid_theme(data.get("theme")) or theme
        accent = valid_accent(data.get("accent")) or accent
        if not (valid_theme(data.get("theme")) or valid_accent(data.get("accent"))):
            return jsonify(ok=False, message="Некорректные настройки"), 400
    session["theme"], session["accent"] = theme, accent
    if g.user:
        get_db().set_user_appearance(g.user["id"], theme, accent)
    if wants_json():
        return jsonify(ok=True, theme=theme, accent=accent, vars=accent_vars(theme, accent))
    return redirect(safe_next(request.form.get("next")) or url_for("shop.index"))
