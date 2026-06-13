from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from .extensions import db
from .models import StudyGroup, User


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    groups = StudyGroup.query.order_by(StudyGroup.name.asc()).all()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        invite_code = request.form.get("invite_code", "").strip()
        group_id = request.form.get("group_id") or None

        if role not in {"student", "teacher", "admin"}:
            flash("Некорректная роль.", "danger")
            return redirect(url_for("auth.register"))
        if role == "teacher" and invite_code != current_app.config["TEACHER_INVITE_CODE"]:
            flash("Неверный код преподавателя.", "danger")
            return redirect(url_for("auth.register"))
        if role == "admin" and invite_code != current_app.config["ADMIN_INVITE_CODE"]:
            flash("Неверный код администратора.", "danger")
            return redirect(url_for("auth.register"))
        if not full_name or not email or len(password) < 6:
            flash("Заполните ФИО, email и пароль длиной от 6 символов.", "danger")
            return redirect(url_for("auth.register"))
        if User.query.filter(func.lower(User.email) == email).first():
            flash("Пользователь с таким email уже существует.", "danger")
            return redirect(url_for("auth.register"))

        user = User(full_name=full_name, email=email, phone=phone, role=role, group_id=group_id if role != "teacher" else None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Регистрация выполнена успешно.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", groups=groups)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            flash("Вы вошли в систему.", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.dashboard"))
        flash("Неверный email или пароль.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("main.index"))
