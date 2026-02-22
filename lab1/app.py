from flask import Flask, render_template, request, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.config["SECRET_KEY"] = "lab1-dev-key"
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

POSTS = {
    1: {
        "title": "Заголовок поста",
        "author": "Toni Hernandez",
        "author_avatar": "images/avatar.jpg",
        "date": "22.08.2020",
        "image": "images/2d2ab7df-cdbc-48a8-a936-35bba702def5.jpg",
        "text": (
            "Report first view. Wide research already difficult he point weight. Whatever food shoulder quite beat investment. "
            "Job behind way build prove both through quickly. Fund whether challenge entire no. Trouble somebody seat center cultural someone.\n\n"
            "Environmental many nature prove heavy. Life surface door only about measure choice front. "
            "So since fish student purpose. By thus buy drive. Born practice later glass.\n\n"
            "Hope subject care half agreement south than. Join shake candidate man. Strong general form name who water feeling."
        ),
        "comments": [
            {
                "author": "Stephanie Franklin",
                "avatar": "images/avatar.jpg",
                "text": "Leave whom discussion possible win. Performance Democrat fund that short hit song. Others something care make again series they ability.",
                "replies": [
                    {
                        "author": "Toni Hernandez",
                        "avatar": "images/avatar.jpg",
                        "text": "Спасибо за комментарий!"
                    }
                ]
            },
            {
                "author": "Andrew Mcconnell",
                "avatar": "images/avatar.jpg",
                "text": "Data now less religious. Action argue surface memory decision. Education move everybody.",
                "replies": []
            }
        ],
    },
    2: {
        "title": "Закат над водой",
        "author": "Vlad Ostapenko",
        "author_avatar": "images/avatar.jpg",
        "date": "20.02.2026",
        "image": "images/6e12f3de-d5fd-4ebb-855b-8cbc485278b7.jpg",
        "text": (
            "Пост с изображением из архива lab1_images. Здесь демонстрируется использование данных из задания.\n\n"
            "На странице выводятся заголовок, автор, дата публикации, изображение, текст и блок комментариев."
        ),
        "comments": [],
    },
    3: {
        "title": "Ночная трасса",
        "author": "Vlad Ostapenko",
        "author_avatar": "images/avatar.jpg",
        "date": "20.02.2026",
        "image": "images/cab5b7f2-774e-4884-a200-0c0180fa777f.jpg",
        "text": (
            "Ещё один пример поста для списка. Картинка тоже берётся из архива.\n\n"
            "Этот пост нужен для демонстрации списка постов и перехода на страницу отдельного поста."
        ),
        "comments": [],
    },
}


@app.get("/")
def index():
    return render_template("index.html", posts=POSTS)


@app.route("/posts/<int:post_id>", methods=["GET", "POST"])
def post(post_id: int):
    item = POSTS.get(post_id)
    if not item:
        return "Post not found", 404

    if request.method == "POST":
        text = (request.form.get("comment_text") or "").strip()
        if text:
            item["comments"].append(
                {
                    "author": "Вы",
                    "avatar": "images/avatar.jpg",
                    "text": text,
                    "replies": []
                }
            )
        return redirect(url_for("post", post_id=post_id))

    return render_template("post.html", post=item, post_id=post_id)


@app.get("/task")
def task():
    return render_template(
        "simple_page.html",
        title="Задание",
        content=(
            "Лабораторная работа №1: разработка Flask-приложения с использованием шаблонов Jinja2.\n\n"
            "Необходимо реализовать:\n"
            "• базовый шаблон сайта с навигацией;\n"
            "• список постов;\n"
            "• страницу отдельного поста;\n"
            "• вывод заголовка, автора, даты, изображения и текста поста;\n"
            "• форму добавления комментария;\n"
            "• вывод комментариев и ответов на комментарии;\n"
            "• footer с ФИО и номером группы.\n\n"
            "В данной работе реализованы страницы «Главная», «Задание», «Об авторе», "
            "страница поста, форма комментария и шаблоны Jinja2."
        )
    )


@app.get("/about")
def about():
    return render_template(
        "simple_page.html",
        title="Об авторе",
        content=(
            "Остапенко Владислав Русланович\n"
            "Группа: 241-3211\n\n"
            "В рамках лабораторной работы №1 разработано Flask-приложение с шаблонами Jinja2.\n"
            "Реализованы список постов, страница отдельного поста, форма добавления комментария, "
            "вывод комментариев и ответов на них, а также навигация по разделам сайта.\n\n"
            "Использованные технологии: Python, Flask, Jinja2, HTML, CSS."
        )
    )


if __name__ == "__main__":
    app.run(debug=True)