from functools import wraps
from flask import flash, redirect, url_for, current_app
from flask_login import current_user
import sqlite3

ROLE_ADMIN = "Администратор"
ROLE_USER = "Пользователь"

RIGHTS = {
    ROLE_ADMIN: {
        "users_create",
        "users_edit",
        "users_view",
        "users_delete",
        "visitlog_view_all",   # Lab5-2
        "visitlog_view_self",  # Lab5-2
    },
    ROLE_USER: {
        "profile_view_self",
        "profile_edit_self",
        "visitlog_view_self",  # Lab5-2
    },
}

def _db_path():
    # если у тебя где-то в app.py есть app.config["DB_PATH"], будет супер
    # иначе оставляем дефолт как у тебя сейчас
    return current_app.config.get("DB_PATH", "/var/www/viklip/labs/lab4/lab4.db")

def get_role_name_by_id(role_id: int | None) -> str | None:
    if role_id is None:
        return None
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
    row = con.execute("SELECT description FROM roles WHERE id = ?", (role_id,)).fetchone()
    return row["description"] if row else None
    finally:
        con.close()

def get_current_role() -> str | None:
    if not current_user or not getattr(current_user, "is_authenticated", False):
        return None
    rid = getattr(current_user, "role_id", None)
    return get_role_name_by_id(rid)

def check_rights(required_right: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            role_name = get_current_role()
            if not role_name or required_right not in RIGHTS.get(role_name, set()):
                flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                return redirect(url_for("index"))  # если главная у тебя иначе называется — скажешь
            return view_func(*args, **kwargs)
        return wrapper
    return decorator
