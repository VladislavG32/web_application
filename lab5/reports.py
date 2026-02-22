import csv
import io
import sqlite3
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

reports_bp = Blueprint("visitlogs", __name__)


def get_db():
    if "db" not in g:
        db_path = current_app.config["DB_PATH"]
        g.db = sqlite3.connect(db_path, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


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


def has_right(user, right: str) -> bool:
    if not user:
        return False
    rights = current_app.config.get("RIGHTS", {})
    return right in rights.get(user["role_name"] or "", set())


def full_name(row) -> str:
    if not row:
        return "Неаутентифицированный пользователь"
    parts = [
        (row["last_name"] or "").strip(),
        (row["first_name"] or "").strip(),
        (row["middle_name"] or "").strip(),
    ]
    parts = [p for p in parts if p]
    return " ".join(parts) if parts else (row["login"] or "Неаутентифицированный пользователь")


def role_title(row) -> str:
    if not row:
        return "—"
    return row["role_desc"] or row["role_name"] or "—"


def fmt_dt(dt_value: str) -> str:
    try:
        return datetime.strptime(dt_value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return dt_value


def require_login_or_redirect():
    if get_current_user() is None:
        flash("Пожалуйста, войдите в систему.", "warning")
        return redirect(url_for("login", next=request.path))
    return None


def require_logs_access():
    user = get_current_user()
    if not user:
        return False, redirect(url_for("login", next=request.path))
    if has_right(user, "visitlogs.view_all") or has_right(user, "visitlogs.view_self"):
        return True, None
    flash("У вас недостаточно прав для доступа к данной странице.", "danger")
    return False, redirect(url_for("index"))


def require_admin_report(report_right: str):
    user = get_current_user()
    if not user:
        flash("Пожалуйста, войдите в систему.", "warning")
        return False, redirect(url_for("login", next=request.path))
    if has_right(user, report_right):
        return True, None
    flash("У вас недостаточно прав для доступа к данной странице.", "danger")
    return False, redirect(url_for("index"))


@reports_bp.route("/")
def logs_index():
    ok, response = require_logs_access()
    if not ok:
        return response

    db = get_db()
    user = get_current_user()

    page = request.args.get("page", default=1, type=int) or 1
    per_page = request.args.get("per_page", default=10, type=int) or 10
    if per_page not in (5, 10, 20, 50):
        per_page = 10
    if page < 1:
        page = 1
    offset = (page - 1) * per_page

    if has_right(user, "visitlogs.view_all"):
        total = db.execute("SELECT COUNT(*) AS c FROM visit_logs").fetchone()["c"]
        rows = db.execute(
            """
            SELECT vl.*, u.login, u.last_name, u.first_name, u.middle_name
            FROM visit_logs vl
            LEFT JOIN users u ON u.id = vl.user_id
            ORDER BY vl.created_at DESC, vl.id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ).fetchall()
    else:
        total = db.execute(
            "SELECT COUNT(*) AS c FROM visit_logs WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["c"]
        rows = db.execute(
            """
            SELECT vl.*, u.login, u.last_name, u.first_name, u.middle_name
            FROM visit_logs vl
            LEFT JOIN users u ON u.id = vl.user_id
            WHERE vl.user_id = ?
            ORDER BY vl.created_at DESC, vl.id DESC
            LIMIT ? OFFSET ?
            """,
            (user["id"], per_page, offset),
        ).fetchall()

    items = []
    for i, row in enumerate(rows, start=offset + 1):
        items.append(
            {
                "n": i,
                "user": "Неаутентифицированный пользователь" if row["user_id"] is None else full_name(row),
                "path": row["path"],
                "created_at": fmt_dt(row["created_at"]),
            }
        )

    pages_count = max(1, (total + per_page - 1) // per_page)
    if page > pages_count:
        page = pages_count

    return render_template(
        "visit_logs/index.html",
        logs=items,
        page=page,
        pages_count=pages_count,
        per_page=per_page,
        total=total,
        can_reports=has_right(user, "reports.pages") or has_right(user, "reports.users"),
        current_role_title=role_title(user),
    )


@reports_bp.route("/report/pages")
def report_pages():
    ok, response = require_admin_report("reports.pages")
    if not ok:
        return response

    rows = get_db().execute(
        """
        SELECT path, COUNT(*) AS visits_count
        FROM visit_logs
        GROUP BY path
        ORDER BY visits_count DESC, path ASC
        """
    ).fetchall()

    items = [{"n": i, "page": row["path"], "cnt": row["visits_count"]} for i, row in enumerate(rows, start=1)]
    return render_template("visit_logs/report_pages.html", rows=items)


@reports_bp.route("/report/users")
def report_users():
    ok, response = require_admin_report("reports.users")
    if not ok:
        return response

    rows = get_db().execute(
        """
        SELECT
            COALESCE(u.id, 0) AS uid,
            u.login, u.last_name, u.first_name, u.middle_name,
            COUNT(*) AS visits_count
        FROM visit_logs vl
        LEFT JOIN users u ON u.id = vl.user_id
        GROUP BY COALESCE(u.id, 0), u.login, u.last_name, u.first_name, u.middle_name
        ORDER BY visits_count DESC, uid ASC
        """
    ).fetchall()

    out = []
    for i, row in enumerate(rows, start=1):
        if row["uid"] == 0:
            user_label = "Неаутентифицированный пользователь"
        else:
            user_label = full_name(row)
        out.append({"n": i, "user": user_label, "cnt": row["visits_count"]})
    return render_template("visit_logs/report_users.html", rows=out)


@reports_bp.route("/export/pages.csv")
def export_pages_csv():
    ok, response = require_admin_report("reports.export")
    if not ok:
        return response

    rows = get_db().execute(
        """
        SELECT path, COUNT(*) AS visits_count
        FROM visit_logs
        GROUP BY path
        ORDER BY visits_count DESC, path ASC
        """
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(["№", "Страница", "Количество посещений"])
    for i, row in enumerate(rows, start=1):
        writer.writerow([i, row["path"], row["visits_count"]])

    data = buf.getvalue().encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report_pages.csv"},
    )


@reports_bp.route("/export/users.csv")
def export_users_csv():
    ok, response = require_admin_report("reports.export")
    if not ok:
        return response

    rows = get_db().execute(
        """
        SELECT
            COALESCE(u.id, 0) AS uid,
            u.login, u.last_name, u.first_name, u.middle_name,
            COUNT(*) AS visits_count
        FROM visit_logs vl
        LEFT JOIN users u ON u.id = vl.user_id
        GROUP BY COALESCE(u.id, 0), u.login, u.last_name, u.first_name, u.middle_name
        ORDER BY visits_count DESC, uid ASC
        """
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow(["№", "Пользователь", "Количество посещений"])
    for i, row in enumerate(rows, start=1):
        if row["uid"] == 0:
            user_label = "Неаутентифицированный пользователь"
        else:
            user_label = full_name(row)
        writer.writerow([i, user_label, row["visits_count"]])

    data = buf.getvalue().encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report_users.csv"},
    )
