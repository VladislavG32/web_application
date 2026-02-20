import sqlite3
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, abort
from werkzeug.middleware.proxy_fix import ProxyFix

DB_PATH = Path(__file__).with_name("notes.db")

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
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/lab3")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


@app.get("/")
def index():
    conn = get_db()
    notes = conn.execute("SELECT id, title, created_at FROM notes ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("index.html", notes=notes)


@app.route("/create", methods=["GET", "POST"])
def create():
    errors = {}
    title = ""
    text = ""

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        text = (request.form.get("text") or "").strip()

        if len(title) < 3:
            errors["title"] = "Заголовок должен быть минимум 3 символа."
        if len(text) < 5:
            errors["text"] = "Текст должен быть минимум 5 символов."

        if not errors:
            conn = get_db()
            conn.execute(
                "INSERT INTO notes(title, text, created_at) VALUES (?, ?, ?)",
                (title, text, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()
            return redirect(url_for("index"))

    return render_template("create.html", errors=errors, title=title, text=text)


@app.get("/notes/<int:note_id>")
def view(note_id: int):
    conn = get_db()
    note = conn.execute(
        "SELECT id, title, text, created_at FROM notes WHERE id = ?",
        (note_id,)
    ).fetchone()
    conn.close()

    if not note:
        abort(404)

    return render_template("view.html", note=note)


@app.route("/notes/<int:note_id>/edit", methods=["GET", "POST"])
def edit(note_id: int):
    conn = get_db()
    note = conn.execute(
        "SELECT id, title, text, created_at FROM notes WHERE id = ?",
        (note_id,)
    ).fetchone()

    if not note:
        conn.close()
        abort(404)

    errors = {}
    title = note["title"]
    text = note["text"]

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        text = (request.form.get("text") or "").strip()

        if len(title) < 3:
            errors["title"] = "Заголовок должен быть минимум 3 символа."
        if len(text) < 5:
            errors["text"] = "Текст должен быть минимум 5 символов."

        if not errors:
            conn.execute(
                "UPDATE notes SET title = ?, text = ? WHERE id = ?",
                (title, text, note_id)
            )
            conn.commit()
            conn.close()
            return redirect(url_for("view", note_id=note_id))

    conn.close()
    return render_template("edit.html", note_id=note_id, errors=errors, title=title, text=text)


@app.post("/notes/<int:note_id>/delete")
def delete(note_id: int):
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))
