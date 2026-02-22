"""Опциональный модуль RBAC.

В текущем решении проверка прав реализована в app.py (декоратор check_rights),
но этот файл оставлен валидным, чтобы в проекте не было битого Python-кода.
"""

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
