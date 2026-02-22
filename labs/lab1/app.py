from flask import Flask, render_template
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

# чтобы корректно определялись host/proto за nginx
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
# чтобы url_for() добавлял /lab1
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/lab1")

POSTS = {
    1: {
        "title": "Первый пост",
        "author": "Админ",
        "date": "2026-02-19",
        "text": "Это пример текста поста для Lab1. Здесь может быть несколько абзацев.\n\nВторой абзац текста."
    },
    2: {
        "title": "Второй пост",
        "author": "DevOps",
        "date": "2026-02-20",
        "text": "Ещё один пример поста."
    }
}

@app.get("/")
def index():
    return render_template("index.html", posts=POSTS)

@app.get("/posts/<int:post_id>")
def post(post_id: int):
    post = POSTS.get(post_id)
    if not post:
        return "Post not found", 404
    return render_template("post.html", post=post)
