from flask import Flask, render_template, request, redirect, url_for, session
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.middleware.proxy_fix import ProxyFix


class PrefixMiddleware:
    def __init__(self, app, prefix=""):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", self.prefix)
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(prefix):
                environ["PATH_INFO"] = path_info[len(prefix):] or "/"
        return self.app(environ, start_response)


app = Flask(__name__)
app.config["SECRET_KEY"] = "lab3-secret-key-change-if-you-want"

# Для работы за nginx/reverse proxy + /lab3 prefix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/lab3")

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
AUTH_REQUIRED_MESSAGE = "Для доступа к запрашиваемой странице необходимо пройти процедуру аутентификации."
login_manager.login_view = "login"  # куда редиректить неавторизованного
login_manager.login_message = AUTH_REQUIRED_MESSAGE
login_manager.login_message_category = "error"


class User(UserMixin):
    def __init__(self, user_id: str, username: str):
        self.id = user_id
        self.username = username


# "База" пользователей по ТЗ (один пользователь)
USERS = {
    "user": {
        "id": "1",
        "username": "user",
        "password": "qwerty",
    }
}


@login_manager.user_loader
def load_user(user_id):
    # Ищем пользователя по id
    for u in USERS.values():
        if u["id"] == str(user_id):
            return User(u["id"], u["username"])
    return None


@login_manager.unauthorized_handler
def unauthorized():
    next_url = request.path
    return redirect(url_for("login", next=next_url, auth_required=1))


@app.route("/")
def index():
    # Счётчик посещений в session
    visits = session.get("visits_count", 0) + 1
    session["visits_count"] = visits
    return render_template("index.html", visits=visits)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "GET" and request.args.get("auth_required") == "1":
        error = AUTH_REQUIRED_MESSAGE

    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        remember = request.form.get("remember") == "on"

        user_data = USERS.get(username)
        if not user_data or user_data["password"] != password:
            error = "Неверный логин или пароль."
        else:
            user = User(user_data["id"], user_data["username"])
            login_user(user, remember=remember)

            next_url = request.args.get("next")
            # Простой безопасный вариант: только внутренний путь
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("index"))

    return render_template("login.html", error=error)


@app.route("/secret")
@login_required
def secret():
    return render_template("secret.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9300, debug=True)
