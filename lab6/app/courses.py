from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import db, Course, Category, User, Review
from tools import CoursesFilter, ImageSaver

bp = Blueprint('courses', __name__, url_prefix='/courses')

COURSE_PARAMS = [
    'author_id', 'name', 'category_id', 'short_desc', 'full_desc'
]

REVIEW_SORT_OPTIONS = {
    'newest': 'По новизне',
    'positive': 'Сначала положительные',
    'negative': 'Сначала отрицательные',
}

REVIEW_RATING_CHOICES = [
    (5, 'отлично'),
    (4, 'хорошо'),
    (3, 'удовлетворительно'),
    (2, 'неудовлетворительно'),
    (1, 'плохо'),
    (0, 'ужасно'),
]


def params():
    return {p: (request.form.get(p) or '').strip() for p in COURSE_PARAMS}


def search_params():
    return {
        'name': request.args.get('name'),
        'category_ids': [x for x in request.args.getlist('category_ids') if x],
    }


def _review_order(sort_key: str):
    if sort_key == 'positive':
        return (Review.rating.desc(), Review.created_at.desc(), Review.id.desc())
    if sort_key == 'negative':
        return (Review.rating.asc(), Review.created_at.desc(), Review.id.desc())
    return (Review.created_at.desc(), Review.id.desc())


def _get_sort_key():
    value = (request.args.get('sort') or 'newest').strip()
    return value if value in REVIEW_SORT_OPTIONS else 'newest'


def _find_user_review(course_id: int, user_id: int | None):
    if not user_id:
        return None
    stmt = (
        db.select(Review)
        .where(Review.course_id == course_id, Review.user_id == user_id)
        .options(joinedload(Review.user))
    )
    return db.session.execute(stmt).scalar_one_or_none()


def _last_reviews(course_id: int, limit: int = 5):
    stmt = (
        db.select(Review)
        .where(Review.course_id == course_id)
        .options(joinedload(Review.user))
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit)
    )
    return db.session.execute(stmt).scalars().all()


def _safe_next_url(default_url: str):
    next_url = (request.form.get('next_url') or '').strip()
    if not next_url:
        return default_url
    parsed = urlparse(next_url)
    # Разрешаем только относительные ссылки внутри приложения
    if parsed.scheme or parsed.netloc:
        return default_url
    if not next_url.startswith('/'):
        return default_url
    return next_url


@bp.route('/')
def index():
    courses = CoursesFilter(**search_params()).perform()
    pagination = db.paginate(courses)
    courses = pagination.items
    categories = db.session.execute(db.select(Category)).scalars()
    return render_template(
        'courses/index.html',
        courses=courses,
        categories=categories,
        pagination=pagination,
        search_params=search_params(),
    )


@bp.route('/new')
@login_required
def new():
    course = Course()
    categories = db.session.execute(db.select(Category)).scalars()
    users = db.session.execute(db.select(User)).scalars()
    return render_template(
        'courses/new.html',
        categories=categories,
        users=users,
        course=course,
    )


@bp.route('/create', methods=['POST'])
@login_required
def create():
    f = request.files.get('background_img')
    img = None
    course = Course()
    try:
        if f and f.filename:
            img = ImageSaver(f).save()

        image_id = img.id if img else None
        if not image_id:
            from models import Image
            default_img = db.session.execute(db.select(Image).limit(1)).scalar_one_or_none()
            if default_img:
                image_id = default_img.id

        if not image_id:
            fallback_image = db.session.query(Image).first()
            if fallback_image is None:
                flash('Невозможно создать курс без изображения: сначала загрузите хотя бы одно изображение.', 'danger')
                return redirect(request.url)
            image_id = fallback_image.id

        course = Course(**params(), background_image_id=image_id)

        db.session.add(course)
        db.session.commit()
    except IntegrityError as err:
        flash(
            'Возникла ошибка при записи данных в БД. '
            f'Проверьте корректность введённых данных. ({err})',
            'danger'
        )
        db.session.rollback()
        categories = db.session.execute(db.select(Category)).scalars()
        users = db.session.execute(db.select(User)).scalars()
        return render_template(
            'courses/new.html',
            categories=categories,
            users=users,
            course=course,
        )

    flash(f'Курс {course.name} был успешно добавлен!', 'success')
    return redirect(url_for('courses.index'))



@bp.route('/my')
@login_required
def my_courses():
    courses = (db.session.query(Course)
               .filter(Course.author_id == current_user.id)
               .options(joinedload(Course.author), joinedload(Course.category))
               .order_by(Course.id.desc())
               .all())
    return render_template('courses/my.html', courses=courses)


@bp.route('/<int:course_id>/delete', methods=['POST'])
@login_required
def delete(course_id):
    course = db.session.get(Course, course_id)
    if course is None:
        flash('Курс не найден.', 'danger')
        return redirect(url_for('courses.index'))

    if current_user.id != course.author_id:
        flash('Удалять курс может только его автор.', 'danger')
        return redirect(url_for('courses.show', course_id=course.id))

    try:
        # Сначала удаляем связанные отзывы (если есть)
        reviews = db.session.execute(
            db.select(Review).where(Review.course_id == course.id)
        ).scalars().all()
        for rv in reviews:
            db.session.delete(rv)

        db.session.delete(course)
        db.session.commit()
        flash('Курс удалён.', 'success')
        return redirect(url_for('courses.my_courses'))
    except Exception as e:
        db.session.rollback()
        flash(f'Не удалось удалить курс. ({e})', 'danger')
        return redirect(url_for('courses.show', course_id=course.id))


@bp.route('/<int:course_id>')
def show(course_id):
    course = db.get_or_404(Course, course_id)
    my_review = None
    if current_user.is_authenticated:
        my_review = _find_user_review(course_id, current_user.id)

    return render_template(
        'courses/show.html',
        course=course,
        last_reviews=_last_reviews(course_id),
        my_review=my_review,
        rating_choices=REVIEW_RATING_CHOICES,
    )


@bp.route('/<int:course_id>/reviews')
def reviews(course_id):
    course = db.get_or_404(Course, course_id)
    sort_key = _get_sort_key()

    stmt = (
        db.select(Review)
        .where(Review.course_id == course_id)
        .options(joinedload(Review.user))
        .order_by(*_review_order(sort_key))
    )

    pagination = db.paginate(stmt)
    reviews_items = pagination.items

    my_review = None
    if current_user.is_authenticated:
        my_review = _find_user_review(course_id, current_user.id)

    return render_template(
        'courses/reviews.html',
        course=course,
        reviews=reviews_items,
        pagination=pagination,
        current_sort=sort_key,
        sort_options=REVIEW_SORT_OPTIONS,
        my_review=my_review,
        rating_choices=REVIEW_RATING_CHOICES,
    )


@bp.route('/<int:course_id>/reviews/create', methods=['POST'])
@login_required
def create_review(course_id):
    course = db.get_or_404(Course, course_id)
    default_redirect = url_for('courses.show', course_id=course_id)
    redirect_to = _safe_next_url(default_redirect)

    existing_review = _find_user_review(course_id, current_user.id)
    if existing_review is not None:
        flash('Вы уже оставили отзыв для этого курса.', 'warning')
        return redirect(redirect_to)

    text = (request.form.get('text') or '').strip()
    rating_raw = (request.form.get('rating') or '').strip()

    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = None

    if not text:
        flash('Текст отзыва не должен быть пустым.', 'danger')
        return redirect(redirect_to)

    if rating is None or rating < 0 or rating > 5:
        flash('Оценка должна быть числом от 0 до 5.', 'danger')
        return redirect(redirect_to)

    review = Review(
        rating=rating,
        text=text,
        course_id=course_id,
        user_id=current_user.id,
        created_at=datetime.utcnow(),
    )

    try:
        db.session.add(review)
        course.rating_sum = (course.rating_sum or 0) + rating
        course.rating_num = (course.rating_num or 0) + 1
        db.session.commit()
    except IntegrityError as err:
        db.session.rollback()
        flash(f'Ошибка при сохранении отзыва. ({err})', 'danger')
        return redirect(redirect_to)

    flash('Отзыв добавлен!', 'success')
    return redirect(redirect_to)
