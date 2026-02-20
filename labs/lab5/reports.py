import csv
import io
import sqlite3
from datetime import datetime

from flask import (
    Blueprint, g, request, render_template,
    session, redirect, url_for, flash, Response
)

reports_bp = Blueprint("visitlogs", __name__)

DB_PATH = "lab4.db"  # рядом с app.py


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    return db.execute("""
        SELECT u.*, r.name AS role_name
        FROM users u
        LEFT JOIN roles r ON r.id = u.role_id
        WHERE u.id=?
    """, (uid,)).fetchone()


def is_admin(u) -> bool:
    return bool(u and u["role_name"] == "admin")


def fmt_dt(s: str) -> str:
    # ожидаем "YYYY-MM-DD HH:MM:SS"
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return s


def full_name(row) -> str:
    if not row:
        return "Неаутентифицированный пользователь"
    ln = (row["last_name"] or "").strip()
    fn = (row["first_name"] or "").strip()
    mn = (row["middle_name"] or "").strip()
    parts = [p for p in [ln, fn, mn] if p]
    return " ".join(parts) if parts else row["login"]


def require_login():
    if not current_user():
        flash("Пожалуйста, войдите в систему.", "warning")
        return redirect(url_for("login", next="/lab4" + request.path))
    return None


@reports_bp.route("/", methods=["GET"])
def logs_index():
    r = require_login()
    if r:
        return r

    db = get_db()
    u = current_user()

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 10))
    if per_page not in (5, 10, 20, 50):
        per_page = 10
    offset = (page - 1) * per_page

    # admin видит всё, user — только свои записи
    if is_admin(u):
        total = db.execute("SELECT COUNT(*) AS c FROM visit_logs").fetchone()["c"]
        rows = db.execute("""
            SELECT vl.*, u.login, u.last_name, u.first_name, u.middle_name
            FROM visit_logs vl
            LEFT JOIN users u ON u.id = vl.user_id
            ORDER BY vl.created_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        can_reports = True
    else:
        total = db.execute("SELECT COUNT(*) AS c FROM visit_logs WHERE user_id=?", (u["id"],)).fetchone()["c"]
        rows = db.execute("""
            SELECT vl.*, u.login, u.last_name, u.first_name, u.middle_name
            FROM visit_logs vl
            LEFT JOIN users u ON u.id = vl.user_id
            WHERE vl.user_id=?
            ORDER BY vl.created_at DESC
            LIMIT ? OFFSET ?
        """, (u["id"], per_page, offset)).fetchall()
        can_reports = False  # отчёты — только админу (по ТЗ это логично)

    # подготовим данные для шаблона
    logs = []
    for i, row in enumerate(rows, start=1 + offset):
        logs.append({
            "n": i,
            "user": full_name(row) if row["user_id"] else "Неаутентифицированный пользователь",
            "path": row["path"],
            "dt": fmt_dt(row["created_at"]),
        })

    pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "visit_logs/index.html",
        logs=logs,
        page=page,
        pages=pages,
        per_page=per_page,
        can_reports=can_reports,
    )


@reports_bp.route("/report/pages", methods=["GET"])
def report_pages():
    r = require_login()
    if r:
        return r
    if not is_admin(current_user()):
        flash("У вас недостаточно прав для доступа к данной странице.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    rows = db.execute("""
        SELECT path, COUNT(*) AS cnt
        FROM visit_logs
        GROUP BY path
        ORDER BY cnt DESC
    """).fetchall()

    data = [{"n": i + 1, "page": r["path"], "cnt": r["cnt"]} for i, r in enumerate(rows)]
    return render_template("visit_logs/report_pages.html", rows=data)


@reports_bp.route("/report/users", methods=["GET"])
def report_users():
    r = require_login()
    if r:
        return r
    if not is_admin(current_user()):
        flash("У вас недостаточно прав для доступа к данной странице.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    rows = db.execute("""
        SELECT
          COALESCE(u.id, 0) AS uid,
          u.login, u.last_name, u.first_name, u.middle_name,
          COUNT(*) AS cnt
        FROM visit_logs vl
        LEFT JOIN users u ON u.id = vl.user_id
        GROUP BY uid
        ORDER BY cnt DESC
    """).fetchall()

    out = []
    for i, r in enumerate(rows):
        user_label = "Неаутентифицированный пользователь" if r["uid"] == 0 else full_name(r)
        out.append({"n": i + 1, "user": user_label, "cnt": r["cnt"]})
    return render_template("visit_logs/report_users.html", rows=out)


@reports_bp.route("/export/pages.csv", methods=["GET"])
def export_pages_csv():
    r = require_login()
    if r:
        return r
    if not is_admin(current_user()):
        flash("У вас недостаточно прав для доступа к данной странице.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    rows = db.execute("""
        SELECT path, COUNT(*) AS cnt
        FROM visit_logs
        GROUP BY path
        ORDER BY cnt DESC
    """).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["№", "Страница", "Количество посещений"])
    for i, r in enumerate(rows, start=1):
        w.writerow([i, r["path"], r["cnt"]])

    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report_pages.csv"}
    )


@reports_bp.route("/export/users.csv", methods=["GET"])
def export_users_csv():
    r = require_login()
    if r:
        return r
    if not is_admin(current_user()):
        flash("У вас недостаточно прав для доступа к данной странице.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    rows = db.execute("""
        SELECT
          COALESCE(u.id, 0) AS uid,
          u.login, u.last_name, u.first_name, u.middle_name,
          COUNT(*) AS cnt
        FROM visit_logs vl
        LEFT JOIN users u ON u.id = vl.user_id
        GROUP BY uid
        ORDER BY cnt DESC
    """).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["№", "Пользователь", "Количество посещений"])
    for i, r in enumerate(rows, start=1):
        user_label = "Неаутентифицированный пользователь" if r["uid"] == 0 else full_name(r)
        w.writerow([i, user_label, r["cnt"]])

    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report_users.csv"}
    )
