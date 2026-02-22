from flask import Flask, render_template, request, make_response, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import re
from typing import Optional, Tuple


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
app.config["SECRET_KEY"] = "lab2-dev-key"
# app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/lab2")

# Разрешены: цифры, пробелы, (), -, ., +
_ALLOWED_PHONE_CHARS_RE = re.compile(r"^[\d\s\-\+\(\)\.]*$")


def request_meta():
    """Короткая сводка по запросу для вывода в шаблонах."""
    return {
        "method": request.method,
        "url": request.url,
        "path": request.path,
        "full_path": request.full_path,
        "remote_addr": request.remote_addr,
    }


def validate_and_format_phone(raw_phone: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (formatted_phone, error_message)

    Правила по ТЗ:
    - 10-11 цифр
    - если начинается с +7 или 8 -> должно быть 11 цифр
    - иначе -> 10 цифр
    - допустимые доп. символы: пробелы, (), -, ., +
    - формат вывода: 8-***-***-**-**
    """
    value = (raw_phone or "").strip()

    # 1) Проверка допустимых символов
    if not _ALLOWED_PHONE_CHARS_RE.fullmatch(value):
        return None, "Недопустимый ввод. В номере телефона встречаются недопустимые символы."

    digits = re.sub(r"\D", "", value)

    # 2) Проверка количества цифр
    if value.startswith("+7") or value.startswith("8"):
        expected_digits = 11
    else:
        expected_digits = 10

    if len(digits) != expected_digits:
        return None, "Недопустимый ввод. Неверное количество цифр."

    # 3) Нормализация к 8XXXXXXXXXX
    if expected_digits == 10:
        digits = "8" + digits
    else:
        # expected_digits == 11
        if digits.startswith("7"):
            digits = "8" + digits[1:]
        elif not digits.startswith("8"):
            # На всякий случай (экзотический ввод, но по ТЗ доп.проверки не нужны)
            digits = "8" + digits[-10:]

    # 4) Форматирование: 8-***-***-**-**
    formatted = f"{digits[0]}-{digits[1:4]}-{digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return formatted, None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/request/args")
def request_args_page():
    data = dict(request.args)
    return render_template(
        "inspect.html",
        title="Параметры URL (request.args)",
        lead="На этой странице отображаются параметры URL (query string).",
        payload_title="request.args",
        payload=data,
        meta=request_meta(),
    )


@app.get("/request/headers")
def request_headers_page():
    data = dict(request.headers)
    return render_template(
        "inspect.html",
        title="Заголовки запроса (request.headers)",
        lead="На этой странице отображаются заголовки текущего HTTP-запроса.",
        payload_title="request.headers",
        payload=data,
        meta=request_meta(),
    )


@app.get("/request/cookies")
def request_cookies_page():
    data = dict(request.cookies)
    return render_template(
        "inspect.html",
        title="Cookie (request.cookies)",
        lead="На этой странице отображаются cookie, пришедшие в запросе.",
        payload_title="request.cookies",
        payload=data,
        meta=request_meta(),
    )


@app.get("/request/cookies/set-demo")
def set_demo_cookie():
    resp = make_response(redirect(url_for("request_cookies_page")))
    resp.set_cookie("lab2_demo", "hello_cookie", max_age=24 * 60 * 60)
    return resp


@app.route("/auth", methods=["GET", "POST"])
def auth():
    submitted = False
    form_data = {"login": "", "password": ""}
    form_params = {}

    if request.method == "POST":
        submitted = True
        form_data["login"] = (request.form.get("login") or "").strip()
        form_data["password"] = request.form.get("password") or ""
        form_params = dict(request.form)

    return render_template(
        "auth.html",
        submitted=submitted,
        form_data=form_data,
        form_params=form_params,
        meta=request_meta(),
    )


@app.route("/phone", methods=["GET", "POST"])
@app.route("/form", methods=["GET", "POST"])  # оставил совместимость со старой ссылкой
def phone_form():
    phone_input = ""
    phone_formatted = ""
    error = None
    checked = False

    if request.method == "POST":
        checked = True
        phone_input = (request.form.get("phone") or "").strip()
        phone_formatted, error = validate_and_format_phone(phone_input)

    return render_template(
        "form.html",
        phone_input=phone_input,
        phone_formatted=phone_formatted,
        error=error,
        checked=checked,
        meta=request_meta(),
    )


# Дополнительная удобная страница (необязательно по ТЗ, но полезно)
@app.route("/inspect", methods=["GET", "POST"])
def inspect_all():
    data = {
        "args": dict(request.args),
        "headers": dict(request.headers),
        "cookies": dict(request.cookies),
        "form": dict(request.form),
    }
    return render_template(
        "inspect.html",
        title="Сводная страница запроса (/inspect)",
        lead="Сводный вывод параметров URL, заголовков, cookie и параметров формы.",
        payload_title="request data",
        payload=data,
        meta=request_meta(),
    )


if __name__ == "__main__":
    app.run(debug=True)
