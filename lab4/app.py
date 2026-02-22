import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, render_template, request, redirect, url_for,
    flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# ====== Настройки ======
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lab4.db")

# Права (доп. функционал Lab5, оставлено для совместимости)
RIGHTS = {
    "admin": {
        "users.create",
        "users.edit",
        "users.view",
        "users.delete",
        "visitlogs.view_all",
        "reports.pages",
        "reports.users",
        "reports.export",
    },
    "user": {
        "users.edit_self",
        "users.view_self",
        "visitlogs.view_self",
    },
}

ALLOWED_PASSWORD_SPECIALS = set("~!?@#$%^&*_-+()[]{}></\\|\"'.,:;")
LOGIN_RE = re.compile(r"^[A-Za-z0-9]{5,}$")


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # Чтобы Flask корректно видел X-Forwarded-Prefix (например, /lab4)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # --- DB helpers ---
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                last_name TEXT,
                first_name TEXT NOT NULL,
                middle_name TEXT,
                role_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(role_id) REFERENCES roles(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS visit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path VARCHAR(100) NOT NULL,
                user_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )

        cur = db.execute("SELECT COUNT(*) AS c FROM roles")
        if cur.fetchone()["c"] == 0:
            db.execute("INSERT INTO roles(name, description) VALUES (?,?)", ("admin", "Администратор"))
            db.execute("INSERT INTO roles(name, description) VALUES (?,?)", ("user", "Пользователь"))

        db.commit()

    # Инициализация БД (упрощённо — при первом запросе)
    _db_inited = {"ok": False}

    @app.before_request
    def _before_request():
        if not _db_inited["ok"]:
            init_db()
            _db_inited["ok"] = True

        # Журнал посещений (доп. функционал)
        path = request.path or "/"
        if request.method == "GET":
            if not (path.startswith("/static") or path.startswith("/.well-known")):
                db = get_db()
                uid = session.get("user_id")
                db.execute(
                    "INSERT INTO visit_logs(path, user_id, created_at) VALUES (?,?,?)",
                    (path, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                db.commit()

    # ====== Auth / current user ======
    def get_current_user():
        uid = session.get("user_id")
        if not uid:
            return None
        db = get_db()
        return db.execute(
            """
            SELECT u.*, r.name AS role_name, r.description AS role_desc
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            WHERE u.id = ?
            """,
            (uid,),
        ).fetchone()

    def full_name(user_row):
        if not user_row:
            return ""
        ln = (user_row["last_name"] or "").strip()
        fn = (user_row["first_name"] or "").strip()
        mn = (user_row["middle_name"] or "").strip()
        parts = [p for p in [ln, fn, mn] if p]
        return " ".join(parts) if parts else user_row["login"]

    def role_rights(role_name: str) -> set:
        return RIGHTS.get(role_name or "", set())

    def has_right(user, right: str) -> bool:
        if not user:
            return False
        return right in role_rights(user["role_name"])

    def _next_url_current_page():
        # Корректно работает и локально, и под X-Forwarded-Prefix
        return (request.script_root or "") + request.path

    def login_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not get_current_user():
                flash("Пожалуйста, войдите в систему.", "warning")
                return redirect(url_for("login", next=_next_url_current_page()))
            return view_func(*args, **kwargs)

        return wrapper

    def check_rights(right: str):
        # Оставлено для доп. маршрутов (Lab5/отчёты)
        def decorator(view_func):
            @wraps(view_func)
            def wrapper(*args, **kwargs):
                user = get_current_user()
                if not user:
                    flash("Пожалуйста, войдите в систему.", "warning")
                    return redirect(url_for("login", next=_next_url_current_page()))

                if right == "users.edit":
                    if has_right(user, "users.edit"):
                        return view_func(*args, **kwargs)
                    target_id = kwargs.get("user_id")
                    if target_id is not None and int(target_id) == int(user["id"]) and has_right(user, "users.edit_self"):
                        return view_func(*args, **kwargs)
                    flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                    return redirect(url_for("index"))

                if right == "users.view":
                    if has_right(user, "users.view"):
                        return view_func(*args, **kwargs)
                    target_id = kwargs.get("user_id")
                    if target_id is not None and int(target_id) == int(user["id"]) and has_right(user, "users.view_self"):
                        return view_func(*args, **kwargs)
                    flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                    return redirect(url_for("index"))

                if not has_right(user, right):
                    if right == "visitlogs.view_all" and has_right(user, "visitlogs.view_self"):
                        return view_func(*args, **kwargs)
                    flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                    return redirect(url_for("index"))

                return view_func(*args, **kwargs)

            return wrapper

        return decorator

    @app.context_processor
    def inject_helpers():
        user = get_current_user()

        def can(right: str) -> bool:
            return has_right(user, right)

        return {
            "current_user": user,
            "full_name": full_name,
            "can": can,
        }

    # ====== Валидация ======
    def validate_login(login_value: str) -> str | None:
        if not login_value:
            return "Поле не может быть пустым."
        if not LOGIN_RE.fullmatch(login_value):
            return "Логин должен содержать только латинские буквы и цифры, минимум 5 символов."
        return None

    def validate_password(password: str) -> list[str]:
        errors: list[str] = []

        if not password:
            return ["Поле не может быть пустым."]

        if len(password) < 8:
            errors.append("Пароль должен содержать не менее 8 символов.")
        if len(password) > 128:
            errors.append("Пароль должен содержать не более 128 символов.")
        if any(ch.isspace() for ch in password):
            errors.append("Пароль не должен содержать пробелы.")

        has_digit = any("0" <= ch <= "9" for ch in password)
        if not has_digit:
            errors.append("Пароль должен содержать хотя бы одну цифру.")

        has_upper = False
        has_lower = False

        for ch in password:
            if "0" <= ch <= "9":
                continue
            if ch in ALLOWED_PASSWORD_SPECIALS:
                continue

            # Разрешаем только латиницу/кириллицу (включая Ё/ё)
            if re.fullmatch(r"[A-Za-zА-Яа-яЁё]", ch):
                if ch.isalpha():
                    if ch.lower() != ch and ch.upper() == ch:
                        has_upper = True
                    if ch.upper() != ch and ch.lower() == ch:
                        has_lower = True
                continue

            errors.append(
                "Пароль содержит недопустимые символы. Разрешены латинские/кириллические буквы, цифры и специальные символы из задания."
            )
            break

        if not has_upper:
            errors.append("Пароль должен содержать хотя бы одну заглавную букву.")
        if not has_lower:
            errors.append("Пароль должен содержать хотя бы одну строчную букву.")

        return errors

    def validate_user_payload(form, *, create_mode: bool = True):
        data = {
            "login": (form.get("login") or "").strip(),
            "password": form.get("password") or "",
            "last_name": (form.get("last_name") or "").strip(),
            "first_name": (form.get("first_name") or "").strip(),
            "middle_name": (form.get("middle_name") or "").strip(),
            "role_id": (form.get("role_id") or "").strip(),
        }
        errors: dict[str, str] = {}

        if not data["last_name"]:
            errors["last_name"] = "Поле не может быть пустым."
        if not data["first_name"]:
            errors["first_name"] = "Поле не может быть пустым."

        if create_mode:
            login_error = validate_login(data["login"])
            if login_error:
                errors["login"] = login_error

            pw_errors = validate_password(data["password"])
            if pw_errors:
                errors["password"] = pw_errors[0]

        # role_id опционален; если выбран, должен быть целым
        if data["role_id"]:
            try:
                int(data["role_id"])
            except ValueError:
                errors["role_id"] = "Некорректное значение роли."

        return data, errors

    def build_users_list():
        db = get_db()
        return db.execute(
            """
            SELECT u.*, r.name AS role_name, r.description AS role_desc
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            ORDER BY u.id ASC
            """
        ).fetchall()

    # ====== Routes ======
    @app.route("/")
    def index():
        users = build_users_list()
        return render_template("index.html", users=users)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        db = get_db()

        if request.method == "POST":
            login_ = (request.form.get("login") or "").strip()
            password = request.form.get("password") or ""

            user = db.execute(
                """
                SELECT u.*, r.name AS role_name
                FROM users u
                LEFT JOIN roles r ON r.id = u.role_id
                WHERE u.login = ?
                """,
                (login_,),
            ).fetchone()

            if not user or not check_password_hash(user["password_hash"], password):
                flash("Неверный логин или пароль.", "danger")
                return render_template("login.html")

            session["user_id"] = user["id"]
            flash("Вы успешно вошли в систему.", "success")

            nxt = request.args.get("next")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("index"))

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.pop("user_id", None)
        flash("Вы вышли из системы.", "info")
        return redirect(url_for("index"))

    @app.route("/users/create", methods=["GET", "POST"])
    @login_required
    def user_create():
        db = get_db()
        roles = db.execute("SELECT * FROM roles ORDER BY id").fetchall()

        if request.method == "POST":
            form_data, errors = validate_user_payload(request.form, create_mode=True)

            if errors:
                flash("Исправьте ошибки в форме.", "danger")
                return render_template(
                    "user_form.html",
                    roles=roles,
                    mode="create",
                    errors=errors,
                    form=form_data,
                )

            try:
                db.execute(
                    """
                    INSERT INTO users(login, password_hash, last_name, first_name, middle_name, role_id, created_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        form_data["login"],
                        generate_password_hash(form_data["password"]),
                        form_data["last_name"],
                        form_data["first_name"],
                        form_data["middle_name"] or None,
                        int(form_data["role_id"]) if form_data["role_id"] else None,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                db.commit()
                flash("Пользователь успешно создан.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                errors["login"] = "Этот логин уже занят."
                flash("Не удалось создать пользователя.", "danger")
                return render_template(
                    "user_form.html",
                    roles=roles,
                    mode="create",
                    errors=errors,
                    form=form_data,
                )
            except Exception:
                flash("Произошла ошибка при сохранении пользователя.", "danger")
                return render_template(
                    "user_form.html",
                    roles=roles,
                    mode="create",
                    errors=errors,
                    form=form_data,
                )

        return render_template("user_form.html", roles=roles, mode="create", errors={}, form={})

    @app.route("/users/<int:user_id>")
    def user_view(user_id: int):
        db = get_db()
        user = db.execute(
            """
            SELECT u.*, r.name AS role_name, r.description AS role_desc
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()

        if not user:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        return render_template("user_view.html", user=user)

    @app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def user_edit(user_id: int):
        db = get_db()
        roles = db.execute("SELECT * FROM roles ORDER BY id").fetchall()

        target = db.execute(
            """
            SELECT u.*, r.name AS role_name
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()

        if not target:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        if request.method == "POST":
            form_data, errors = validate_user_payload(request.form, create_mode=False)

            if errors:
                flash("Исправьте ошибки в форме.", "danger")
                return render_template(
                    "user_form.html",
                    roles=roles,
                    mode="edit",
                    user=target,
                    errors=errors,
                    form=form_data,
                )

            try:
                db.execute(
                    """
                    UPDATE users
                    SET last_name=?, first_name=?, middle_name=?, role_id=?
                    WHERE id=?
                    """,
                    (
                        form_data["last_name"],
                        form_data["first_name"],
                        form_data["middle_name"] or None,
                        int(form_data["role_id"]) if form_data["role_id"] else None,
                        user_id,
                    ),
                )
                db.commit()
                flash("Данные пользователя успешно обновлены.", "success")
                return redirect(url_for("index"))
            except Exception:
                flash("Произошла ошибка при обновлении пользователя.", "danger")
                return render_template(
                    "user_form.html",
                    roles=roles,
                    mode="edit",
                    user=target,
                    errors=errors,
                    form=form_data,
                )

        return render_template("user_form.html", roles=roles, mode="edit", user=target, errors={}, form={})

    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    def user_delete(user_id: int):
        db = get_db()

        if session.get("user_id") == user_id:
            flash("Нельзя удалить текущего авторизованного пользователя.", "danger")
            return redirect(url_for("index"))

        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        try:
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            flash("Пользователь успешно удалён.", "success")
        except Exception:
            flash("Произошла ошибка при удалении пользователя.", "danger")

        return redirect(url_for("index"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        db = get_db()
        user = get_current_user()
        errors: dict[str, str] = {}

        if request.method == "POST":
            old = request.form.get("old_password") or ""
            new1 = request.form.get("new_password") or ""
            new2 = request.form.get("new_password2") or ""

            row = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if not old:
                errors["old_password"] = "Поле не может быть пустым."
            elif not check_password_hash(row["password_hash"], old):
                errors["old_password"] = "Старый пароль введён неверно."

            pw_errors = validate_password(new1)
            if pw_errors:
                errors["new_password"] = pw_errors[0]

            if not new2:
                errors["new_password2"] = "Поле не может быть пустым."
            elif new1 != new2:
                errors["new_password2"] = "Пароли не совпадают."

            if errors:
                flash("Не удалось изменить пароль. Исправьте ошибки в форме.", "danger")
                return render_template("change_password.html", errors=errors)

            try:
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new1), user["id"]),
                )
                db.commit()
                flash("Пароль успешно изменён.", "success")
                return redirect(url_for("index"))
            except Exception:
                flash("Произошла ошибка при изменении пароля.", "danger")
                return render_template("change_password.html", errors=errors)

        return render_template("change_password.html", errors=errors)

    # ====== Blueprint отчётов (доп. Lab5) ======
    try:
        from reports import reports_bp

        app.register_blueprint(reports_bp, url_prefix="/visit-logs")
    except Exception:
        # Для ЛР4 отчёты не обязательны; не падаем, если файла нет/сломался.
        pass

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9400, debug=True)
