import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lab4.db")
APP_BASENAME = os.path.basename(BASE_DIR).lower()
IS_LAB5_MODE = "lab5" in APP_BASENAME

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

LOGIN_RE = re.compile(r"^[A-Za-z0-9]{5,}$")
# Разрешённые символы пароля по ТЗ
PASSWORD_ALLOWED_RE = re.compile(
    r'^[A-Za-zА-Яа-яЁё0-9~!?@#$%^&*_\-+()\[\]{}><\\/|"\'.,:;]+$'
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config["DB_PATH"] = DB_PATH
    app.config["IS_LAB5_MODE"] = IS_LAB5_MODE
    app.config["RIGHTS"] = RIGHTS

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
                name TEXT NOT NULL UNIQUE,
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

        # seed roles
        existing = {row["name"] for row in db.execute("SELECT name FROM roles").fetchall()}
        if "admin" not in existing:
            db.execute(
                "INSERT INTO roles(name, description) VALUES (?, ?)",
                ("admin", "Администратор"),
            )
        if "user" not in existing:
            db.execute(
                "INSERT INTO roles(name, description) VALUES (?, ?)",
                ("user", "Пользователь"),
            )
        db.commit()

    _db_inited = {"ok": False}

    @app.before_request
    def before_every_request():
        if not _db_inited["ok"]:
            init_db()
            _db_inited["ok"] = True

        if request.method == "GET":
            path = request.path or "/"
            if not (
                path.startswith("/static")
                or path.startswith("/.well-known")
                or path == "/favicon.ico"
            ):
                db = get_db()
                db.execute(
                    "INSERT INTO visit_logs(path, user_id, created_at) VALUES (?, ?, ?)",
                    (
                        path[:100],
                        session.get("user_id"),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                db.commit()

    # ---------------- helpers ----------------
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

    def get_user_by_id(user_id: int):
        db = get_db()
        return db.execute(
            """
            SELECT u.*, r.name AS role_name, r.description AS role_desc
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()

    def full_name(row) -> str:
        if not row:
            return ""
        parts = [
            (row["last_name"] or "").strip() if "last_name" in row.keys() else "",
            (row["first_name"] or "").strip() if "first_name" in row.keys() else "",
            (row["middle_name"] or "").strip() if "middle_name" in row.keys() else "",
        ]
        parts = [p for p in parts if p]
        if parts:
            return " ".join(parts)
        return (row["login"] or "").strip() if "login" in row.keys() else ""

    def role_title(row) -> str:
        if not row:
            return "—"
        desc = row["role_desc"] if "role_desc" in row.keys() else None
        if desc:
            return desc
        name = row["role_name"] if "role_name" in row.keys() else None
        return name or "—"

    def has_right(user, right: str) -> bool:
        if not user:
            return False
        role_name = user["role_name"] or ""
        return right in RIGHTS.get(role_name, set())

    def can_view_profile(actor, target_id: int) -> bool:
        if not IS_LAB5_MODE:
            return True  # LR4: просмотр доступен всем пользователям
        if not actor:
            return False
        if has_right(actor, "users.view"):
            return True
        return int(actor["id"]) == int(target_id) and has_right(actor, "users.view_self")

    def can_edit_profile(actor, target_id: int) -> bool:
        if not actor:
            return False
        if not IS_LAB5_MODE:
            return True  # LR4: любой аутентифицированный
        if has_right(actor, "users.edit"):
            return True
        return int(actor["id"]) == int(target_id) and has_right(actor, "users.edit_self")

    def can_delete_profile(actor, target_id: int) -> bool:
        if not actor:
            return False
        if int(actor["id"]) == int(target_id):
            return False
        if not IS_LAB5_MODE:
            return True
        return has_right(actor, "users.delete")

    def can_create_user(actor) -> bool:
        if not actor:
            return False
        if not IS_LAB5_MODE:
            return True
        return has_right(actor, "users.create")

    def login_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not get_current_user():
                flash("Пожалуйста, войдите в систему.", "warning")
                return redirect(url_for("login", next=request.path))
            return view_func(*args, **kwargs)

        return wrapper

    def check_rights(right: str):
        @wraps(check_rights)
        def decorator(view_func):
            @wraps(view_func)
            def wrapper(*args, **kwargs):
                user = get_current_user()
                if not user:
                    flash("Пожалуйста, войдите в систему.", "warning")
                    return redirect(url_for("login", next=request.path))

                target_id = kwargs.get("user_id")
                if right == "users.view":
                    if can_view_profile(user, int(target_id)):
                        return view_func(*args, **kwargs)
                elif right == "users.edit":
                    if can_edit_profile(user, int(target_id)):
                        return view_func(*args, **kwargs)
                elif right == "visitlogs.view_all":
                    if has_right(user, "visitlogs.view_all") or has_right(user, "visitlogs.view_self"):
                        return view_func(*args, **kwargs)
                else:
                    if has_right(user, right):
                        return view_func(*args, **kwargs)

                flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                return redirect(url_for("index"))

            return wrapper

        return decorator

    def validate_login(login_value: str):
        if not login_value:
            return "Поле не может быть пустым."
        if not LOGIN_RE.fullmatch(login_value):
            return "Логин: только латинские буквы/цифры, минимум 5 символов."
        return None

    def validate_required_name(label: str, value: str):
        if not (value or "").strip():
            return f"Поле «{label}» не может быть пустым."
        return None

    def validate_password(password: str):
        if password == "":
            return "Поле не может быть пустым."
        if " " in password:
            return "Пароль не должен содержать пробелы."
        length = len(password)
        if length < 8:
            return "Пароль должен содержать не менее 8 символов."
        if length > 128:
            return "Пароль должен содержать не более 128 символов."
        if not PASSWORD_ALLOWED_RE.fullmatch(password):
            return "Пароль содержит недопустимые символы."
        if not any(ch.isdigit() for ch in password):
            return "Пароль должен содержать хотя бы одну цифру."
        letters = [ch for ch in password if ch.isalpha()]
        if not letters:
            return "Пароль должен содержать буквы."
        if not any(ch.islower() for ch in letters):
            return "Пароль должен содержать хотя бы одну строчную букву."
        if not any(ch.isupper() for ch in letters):
            return "Пароль должен содержать хотя бы одну заглавную букву."
        return None

    def build_user_form_data(src=None):
        src = src or {}
        return {
            "login": (src.get("login") or "").strip(),
            "password": "",
            "last_name": (src.get("last_name") or "").strip(),
            "first_name": (src.get("first_name") or "").strip(),
            "middle_name": (src.get("middle_name") or "").strip(),
            "role_id": str(src.get("role_id") or "").strip(),
        }

    @app.context_processor
    def inject_context():
        actor = get_current_user()

        def can_view_user(target):
            return can_view_profile(actor, int(target["id"]))

        def can_edit_user(target):
            return can_edit_profile(actor, int(target["id"]))

        def can_delete_user(target):
            return can_delete_profile(actor, int(target["id"]))

        return {
            "current_user": actor,
            "app_title": "Лабораторная работа №5" if IS_LAB5_MODE else "Лабораторная работа №4",
            "is_lab5_mode": IS_LAB5_MODE,
            "full_name": full_name,
            "role_title": role_title,
            "can_right": lambda r: has_right(actor, r),
            "can_view_user": can_view_user,
            "can_edit_user": can_edit_user,
            "can_delete_user": can_delete_user,
            "can_create_user": can_create_user(actor),
        }

    # ---------------- routes ----------------
    @app.route("/")
    def index():
        db = get_db()
        users = db.execute(
            """
            SELECT u.*, r.name AS role_name, r.description AS role_desc
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            ORDER BY u.id ASC
            """
        ).fetchall()
        return render_template("index.html", users=users)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            login_value = (request.form.get("login") or "").strip()
            password = request.form.get("password") or ""
            db = get_db()
            user = db.execute(
                """
                SELECT u.*, r.name AS role_name, r.description AS role_desc
                FROM users u
                LEFT JOIN roles r ON r.id = u.role_id
                WHERE u.login = ?
                """,
                (login_value,),
            ).fetchone()

            if not user or not check_password_hash(user["password_hash"], password):
                flash("Неверный логин или пароль.", "danger")
                return render_template("login.html", form={"login": login_value})

            session["user_id"] = user["id"]
            flash("Вы успешно вошли в систему.", "success")
            nxt = request.args.get("next") or request.form.get("next")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("index"))

        return render_template("login.html", form={"login": ""})

    @app.route("/logout")
    def logout():
        session.pop("user_id", None)
        flash("Вы вышли из системы.", "info")
        return redirect(url_for("index"))

    @app.route("/users/create", methods=["GET", "POST"])
    @login_required
    def user_create():
        actor = get_current_user()
        if not can_create_user(actor):
            flash("У вас недостаточно прав для доступа к данной странице.", "danger")
            return redirect(url_for("index"))

        db = get_db()
        roles = db.execute("SELECT * FROM roles ORDER BY id").fetchall()

        if request.method == "GET":
            return render_template(
                "user_form.html",
                mode="create",
                form=build_user_form_data(),
                errors={},
                roles=roles,
                role_disabled=False,
            )

        form = build_user_form_data(request.form)
        errors = {
            "login": validate_login(form["login"]),
            "password": validate_password(request.form.get("password") or ""),
            "last_name": validate_required_name("Фамилия", form["last_name"]),
            "first_name": validate_required_name("Имя", form["first_name"]),
        }
        errors = {k: v for k, v in errors.items() if v}

        role_id_db = None
        if form["role_id"]:
            try:
                role_id_db = int(form["role_id"])
            except ValueError:
                errors["role_id"] = "Некорректная роль."

        if errors:
            flash("Исправьте ошибки в форме.", "danger")
            return render_template(
                "user_form.html",
                mode="create",
                form=form,
                errors=errors,
                roles=roles,
                role_disabled=False,
            )

        try:
            db.execute(
                """
                INSERT INTO users(login, password_hash, last_name, first_name, middle_name, role_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    form["login"],
                    generate_password_hash(request.form.get("password") or ""),
                    form["last_name"],
                    form["first_name"],
                    form["middle_name"] or None,
                    role_id_db,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Не удалось сохранить пользователя: логин уже занят.", "danger")
            errors["login"] = "Логин уже используется."
            return render_template(
                "user_form.html",
                mode="create",
                form=form,
                errors=errors,
                roles=roles,
                role_disabled=False,
            )

        flash("Пользователь успешно создан.", "success")
        return redirect(url_for("index"))

    @app.route("/users/<int:user_id>")
    def user_view(user_id: int):
        target = get_user_by_id(user_id)
        if not target:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        actor = get_current_user()
        if not can_view_profile(actor, user_id):
            if actor is None and not IS_LAB5_MODE:
                pass
            elif actor is None:
                flash("Пожалуйста, войдите в систему.", "warning")
                return redirect(url_for("login", next=request.path))
            else:
                flash("У вас недостаточно прав для доступа к данной странице.", "danger")
                return redirect(url_for("index"))

        return render_template("user_view.html", user=target)

    @app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    @check_rights("users.edit")
    def user_edit(user_id: int):
        db = get_db()
        target = get_user_by_id(user_id)
        if not target:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        actor = get_current_user()
        is_admin = has_right(actor, "users.edit") if IS_LAB5_MODE else True
        role_disabled = not is_admin
        roles = db.execute("SELECT * FROM roles ORDER BY id").fetchall()

        if request.method == "GET":
            form = build_user_form_data(
                {
                    "login": target["login"],
                    "last_name": target["last_name"] or "",
                    "first_name": target["first_name"] or "",
                    "middle_name": target["middle_name"] or "",
                    "role_id": target["role_id"] or "",
                }
            )
            return render_template(
                "user_form.html",
                mode="edit",
                user=target,
                form=form,
                errors={},
                roles=roles,
                role_disabled=role_disabled,
            )

        form = build_user_form_data(request.form)
        # логин и пароль в форме редактирования не используются по ТЗ
        form["login"] = target["login"]

        errors = {
            "last_name": validate_required_name("Фамилия", form["last_name"]),
            "first_name": validate_required_name("Имя", form["first_name"]),
        }
        errors = {k: v for k, v in errors.items() if v}

        role_id_db = target["role_id"]
        if is_admin:
            if form["role_id"]:
                try:
                    role_id_db = int(form["role_id"])
                except ValueError:
                    errors["role_id"] = "Некорректная роль."
            else:
                role_id_db = None

        if errors:
            flash("Исправьте ошибки в форме.", "danger")
            return render_template(
                "user_form.html",
                mode="edit",
                user=target,
                form=form,
                errors=errors,
                roles=roles,
                role_disabled=role_disabled,
            )

        try:
            db.execute(
                """
                UPDATE users
                SET last_name = ?, first_name = ?, middle_name = ?, role_id = ?
                WHERE id = ?
                """,
                (
                    form["last_name"],
                    form["first_name"],
                    form["middle_name"] or None,
                    role_id_db,
                    user_id,
                ),
            )
            db.commit()
        except sqlite3.DatabaseError:
            flash("Не удалось обновить данные пользователя.", "danger")
            return render_template(
                "user_form.html",
                mode="edit",
                user=target,
                form=form,
                errors={},
                roles=roles,
                role_disabled=role_disabled,
            )

        flash("Данные пользователя успешно обновлены.", "success")
        return redirect(url_for("user_view", user_id=user_id))

    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    def user_delete(user_id: int):
        actor = get_current_user()
        if not can_delete_profile(actor, user_id):
            flash("У вас недостаточно прав для доступа к данной странице.", "danger")
            return redirect(url_for("index"))

        db = get_db()
        target = get_user_by_id(user_id)
        if not target:
            flash("Пользователь не найден.", "warning")
            return redirect(url_for("index"))

        try:
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
        except sqlite3.DatabaseError:
            flash("Не удалось удалить пользователя.", "danger")
            return redirect(url_for("index"))

        flash("Пользователь успешно удалён.", "success")
        return redirect(url_for("index"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        actor = get_current_user()
        errors = {}

        if request.method == "POST":
            old_password = request.form.get("old_password") or ""
            new_password = request.form.get("new_password") or ""
            new_password2 = request.form.get("new_password2") or ""

            db = get_db()
            row = db.execute("SELECT * FROM users WHERE id = ?", (actor["id"],)).fetchone()
            if not check_password_hash(row["password_hash"], old_password):
                errors["old_password"] = "Неверно указан старый пароль."

            pwd_error = validate_password(new_password)
            if pwd_error:
                errors["new_password"] = pwd_error

            if new_password != new_password2:
                errors["new_password2"] = "Пароли не совпадают."

            if errors:
                flash("Не удалось изменить пароль. Исправьте ошибки формы.", "danger")
                return render_template("change_password.html", errors=errors)

            try:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_password), actor["id"]),
                )
                db.commit()
            except sqlite3.DatabaseError:
                flash("Ошибка при сохранении нового пароля.", "danger")
                return render_template("change_password.html", errors={})

            flash("Пароль успешно изменён.", "success")
            return redirect(url_for("index"))

        return render_template("change_password.html", errors=errors)

    from reports import reports_bp

    app.register_blueprint(reports_bp, url_prefix="/visit-logs")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9400, debug=True)
