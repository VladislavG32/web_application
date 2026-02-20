from flask import Flask, render_template, request
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
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/lab2")

@app.get("/")
def index():
    return render_template("index.html")

@app.route("/inspect", methods=["GET", "POST"])
def inspect():
    data = {
        "method": request.method,
        "url": request.url,
        "path": request.path,
        "full_path": request.full_path,
        "remote_addr": request.remote_addr,
        "args": dict(request.args),
        "form": dict(request.form),
        "headers": dict(request.headers),
        "cookies": request.cookies,
    }
    return render_template("inspect.html", data=data)

from typing import Dict, List, Tuple

def validate_form(form) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    returns: (clean_data, errors)
    """
    errors: Dict[str, str] = {}
    data: Dict[str, str] = {}

    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    age_raw = (form.get("age") or "").strip()

    if len(name) < 2:
        errors["name"] = "Имя должно быть не короче 2 символов."
    else:
        data["name"] = name

    if "@" not in email or email.startswith("@") or email.endswith("@"):
        errors["email"] = "Введите корректный email."
    else:
        data["email"] = email

    try:
        age = int(age_raw)
        if not (1 <= age <= 120):
            errors["age"] = "Возраст должен быть в диапазоне 1..120."
        else:
            data["age"] = str(age)
    except ValueError:
        errors["age"] = "Возраст должен быть числом."

    return data, errors


@app.route("/form", methods=["GET", "POST"])
def form_view():
    errors = {}
    data = {"name": "", "email": "", "age": ""}

    if request.method == "POST":
        data, errors = validate_form(request.form)
        # если есть ошибки — вернём форму с подсветкой
        if errors:
            # чтобы не терять то, что человек ввёл
            data = {
                "name": (request.form.get("name") or ""),
                "email": (request.form.get("email") or ""),
                "age": (request.form.get("age") or ""),
            }
            return render_template("form.html", data=data, errors=errors, ok=False)

        # успех
        return render_template("form.html", data=data, errors={}, ok=True)

    return render_template("form.html", data=data, errors=errors, ok=False)
