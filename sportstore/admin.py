"""Управление товарами и фото — только для администратора (роль проверяется по базе на каждый запрос)."""

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .auth import admin_required, safe_next
from .constants import CATEGORIES
from .ctx import get_db, wants_json
from .images import PhotoError, prepare_image

bp = Blueprint("admin", __name__, url_prefix="/admin")


def parse_product_form(form):
    """Проверяет поля формы товара. Возвращает (значения, список ошибок)."""
    errors = []
    name = form.get("name", "").strip()
    category = form.get("category", "")
    emoji = form.get("emoji", "").strip()
    if not 2 <= len(name) <= 80:
        errors.append("Название: от 2 до 80 символов")
    if category not in CATEGORIES:
        errors.append("Выберите категорию из списка")
    try:
        price = int(form.get("price", "").replace(" ", "").replace(" ", ""))
        stock = int(form.get("stock", "").strip())
    except ValueError:
        price = stock = None
        errors.append("Цена и остаток должны быть целыми числами")
    if price is not None:
        if not 0 < price <= 100_000_000:
            errors.append("Цена должна быть больше нуля (не больше 100 000 000 ₽)")
        if not 0 <= stock <= 1_000_000:
            errors.append("Остаток: от 0 до 1 000 000")
    if len(emoji) > 4:
        errors.append("Значок: не больше 4 символов")
    return dict(name=name, category=category, price=price, stock=stock, emoji=emoji), errors


def read_photo():
    """Файл из формы -> байты JPEG; (None, None) если файл не выбран; (None, текст) при ошибке."""
    file = request.files.get("photo")
    if file is None or not file.filename:
        return None, None
    try:
        return prepare_image(file.stream), None
    except PhotoError as exc:
        return None, str(exc)


def _form(product, values=None, errors=None, status=200):
    shown = dict(product or {})
    shown.update(values or {})
    return render_template("admin/product_form.html", product=product, values=shown, errors=errors or []), status


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    if request.method == "GET":
        return _form(None, {"stock": 10, "category": CATEGORIES[0]})
    values, errors = parse_product_form(request.form)
    photo, photo_error = read_photo()
    if photo_error:
        errors.append(photo_error)
    if errors:
        return _form(None, request.form.to_dict() | {k: v for k, v in values.items() if v is not None}, errors, 422)
    db = get_db()
    pid = db.save_product(None, values["name"], values["category"], values["price"], values["stock"],
                          values["emoji"])
    if photo:
        db.set_product_image(pid, photo)
    flash("Товар добавлен", "ok")
    return redirect(url_for("shop.index"))


@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(pid):
    db = get_db()
    product = db.get_product(pid)
    if product is None:
        abort(404)
    if request.method == "GET":
        return _form(product)
    values, errors = parse_product_form(request.form)
    photo, photo_error = read_photo()
    if photo_error:
        errors.append(photo_error)
    if errors:
        return _form(product, request.form.to_dict() | {k: v for k, v in values.items() if v is not None},
                     errors, 422)
    db.save_product(pid, values["name"], values["category"], values["price"], values["stock"], values["emoji"])
    if photo:
        db.set_product_image(pid, photo)
    elif request.form.get("remove_photo") == "1":
        db.remove_product_image(pid)
    flash("Изменения сохранены", "ok")
    return redirect(safe_next(request.args.get("next")) or url_for("shop.index"))


@bp.post("/products/<int:pid>/delete")
@admin_required
def product_delete(pid):
    if get_db().get_product(pid) is None:
        abort(404)
    get_db().delete_product(pid)
    flash("Товар удалён", "ok")
    return redirect(url_for("shop.index"))


@bp.post("/products/<int:pid>/photo")
@admin_required
def photo_set(pid):
    """Быстрая смена фото прямо с карточки в каталоге."""
    if get_db().get_product(pid) is None:
        abort(404)
    photo, error = read_photo()
    if error or not photo:
        message = error or "Выберите файл с фото"
        if wants_json():
            return jsonify(ok=False, message=message), 422
        flash(message, "error")
    else:
        get_db().set_product_image(pid, photo)
        flash("Фото обновлено", "ok")
    return redirect(safe_next(request.form.get("next")) or url_for("shop.index"))


@bp.post("/products/<int:pid>/photo/delete")
@admin_required
def photo_delete(pid):
    if get_db().get_product(pid) is None:
        abort(404)
    get_db().remove_product_image(pid)
    flash("Фото удалено", "ok")
    return redirect(safe_next(request.form.get("next")) or url_for("shop.index"))


# --------------------------------------------------------------------------- бюджет организации

MAX_MONEY = 1_000_000_000


def parse_amount(raw, what="Сумма"):
    """Целое число рублей от 1 до MAX_MONEY. Возвращает (число, ошибка)."""
    try:
        value = int((raw or "").replace(" ", "").replace(" ", ""))
    except ValueError:
        return None, f"{what}: введите целое число рублей"
    if not 0 < value <= MAX_MONEY:
        return None, f"{what}: от 1 до {MAX_MONEY:,}".replace(",", " ") + " ₽"
    return value, None


def _budget_page():
    db = get_db()
    return render_template("admin/budget.html", balance=db.budget_balance(), entries=db.budget_entries(),
                           products=db.catalog(sort="name"))


@bp.get("/budget")
@admin_required
def budget():
    return _budget_page()


@bp.post("/budget/deposit")
@admin_required
def budget_deposit():
    amount, error = parse_amount(request.form.get("amount"))
    note = request.form.get("note", "").strip()[:200] or "Пополнение бюджета"
    if error:
        flash(error, "error")
        return redirect(url_for("admin.budget"))
    get_db().budget_change(amount, "deposit", note, g.user["id"])
    flash("Бюджет пополнен", "ok")
    return redirect(url_for("admin.budget"))


@bp.post("/budget/spend")
@admin_required
def budget_spend():
    amount, error = parse_amount(request.form.get("amount"))
    note = request.form.get("note", "").strip()[:200]
    if not error and len(note) < 3:
        error = "Укажите, на что тратится бюджет (от 3 символов)"
    try:
        if error:
            raise ValueError(error)
        get_db().budget_change(-amount, "expense", note, g.user["id"])
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Расход записан", "ok")
    return redirect(url_for("admin.budget"))


@bp.post("/budget/restock")
@admin_required
def budget_restock():
    """Закупка товара: списывает qty × цена закупки из бюджета и добавляет qty на склад."""
    db = get_db()
    try:
        pid = int(request.form.get("product_id", ""))
        qty = int(request.form.get("qty", "").strip())
        if not 0 < qty <= 100_000:
            raise ValueError("Количество: от 1 до 100 000 шт.")
        unit, error = parse_amount(request.form.get("unit_cost"), "Цена закупки за штуку")
        if error:
            raise ValueError(error)
        product = db.get_product(pid)
        if product is None:
            raise ValueError("Товар не найден")
        cost = unit * qty
        if cost > MAX_MONEY:
            raise ValueError("Слишком большая сумма закупки")
        db.budget_change(-cost, "restock", f"Закупка: {product['name']} × {qty} по {unit} ₽", g.user["id"],
                         product_id=pid, qty=qty)
    except ValueError as exc:
        text = str(exc)
        flash("Выберите товар и введите количество числом" if text.startswith("invalid literal") else text, "error")
    else:
        flash(f"Закуплено {qty} шт. на {cost} ₽, остаток на складе обновлён", "ok")
    return redirect(url_for("admin.budget"))
