from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from .extensions import db
from .models import Attendance, GradeRecord, QueueEntry, QueueSession, StudyGroup, Subject, User, WorkUpload
from .queue_service import clean_expired_unconfirmed, move_entry, next_position, normalize_positions, passed_count, call_entry
from .realtime import broadcast_session_update
from .security import can_manage_queue, role_required


main_bp = Blueprint("main", __name__)


def _parse_datetime_local(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


# Проверяем, что преподаватель — владелец очереди.
# Администратор может управлять любой очередью.
def _can_manage_session(session: QueueSession) -> bool:
    if current_user.role == "admin":
        return True
    if current_user.role == "teacher":
        return session.subject.teacher_id == current_user.id
    return False


def _available_sessions():
    query = QueueSession.query.join(Subject).join(StudyGroup).order_by(QueueSession.is_active.desc(), QueueSession.starts_at.desc())
    if current_user.role == "student" and current_user.group_id:
        query = query.filter(QueueSession.group_id == current_user.group_id)
    elif current_user.role == "admin" and current_user.group_id:
        query = query.filter(QueueSession.group_id == current_user.group_id)
    elif current_user.role == "teacher":
        query = query.filter(or_(Subject.teacher_id == current_user.id, Subject.teacher_id.is_(None)))
    return query.all()


def _base_journal_query():
    """Единая база запроса для страницы журнала и CSV-экспорта."""
    query = (
        GradeRecord.query
        .join(User, GradeRecord.student_id == User.id)
        .join(Subject, GradeRecord.subject_id == Subject.id)
        .outerjoin(StudyGroup, User.group_id == StudyGroup.id)
    )

    # Преподаватель видит свои дисциплины и дисциплины без назначенного преподавателя.
    # Администратор видит весь журнал.
    if current_user.role == "teacher":
        query = query.filter(or_(Subject.teacher_id == current_user.id, Subject.teacher_id.is_(None)))

    return query


def _apply_journal_filters(query, subject_id: int | None, group_id: int | None):
    if subject_id:
        query = query.filter(GradeRecord.subject_id == subject_id)
    if group_id:
        query = query.filter(User.group_id == group_id)
    return query


def _make_csv_response(filename: str, rows: list[list[str | int]]) -> Response:
    """Формирует CSV, который нормально открывается в Excel с русским текстом.

    Важные детали:
    - BOM (\ufeff) помогает Excel распознать UTF-8;
    - строка sep=; явно говорит Excel, что разделитель — точка с запятой;
    - CRLF делает переносы строк совместимыми с Windows/Excel.
    """
    output = StringIO(newline="")
    output.write("sep=;\r\n")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerows(rows)
    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    sessions = _available_sessions()
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    user_entries = []
    if current_user.role == "student":
        user_entries = (
            QueueEntry.query.filter_by(student_id=current_user.id)
            .filter(QueueEntry.status.in_(["waiting", "checking"]))
            .order_by(QueueEntry.created_at.desc())
            .all()
        )
    return render_template("dashboard.html", sessions=sessions, subjects=subjects, user_entries=user_entries)


@main_bp.route("/sessions/<int:session_id>")
@login_required
def session_detail(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    removed = clean_expired_unconfirmed(session)
    if removed:
        db.session.commit()
        broadcast_session_update(session.id)
        flash(f"Автоматически отменено неподтвержденных записей: {removed}.", "warning")

    active_entry = None
    if current_user.role == "student":
        active_entry = QueueEntry.query.filter(
            QueueEntry.session_id == session.id,
            QueueEntry.student_id == current_user.id,
            QueueEntry.status.in_(["waiting", "checking"]),
        ).first()
    return render_template("session_detail.html", session=session, active_entry=active_entry, passed_count=passed_count)


@main_bp.route("/sessions/<int:session_id>/join", methods=["POST"])
@login_required
def join_queue(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    if current_user.role not in {"student", "admin"}:
        abort(403)
    if current_user.group_id != session.group_id and current_user.role != "admin":
        abort(403)

    existing = QueueEntry.query.filter(
        QueueEntry.session_id == session.id,
        QueueEntry.student_id == current_user.id,
        QueueEntry.status.in_(["waiting", "checking"]),
    ).first()
    if existing:
        flash("Вы уже записаны в эту очередь.", "warning")
        return redirect(url_for("main.session_detail", session_id=session.id))

    subject = session.subject
    max_lab = subject.lab_count

    try:
        lab_number = int(request.form.get("lab_number", "1"))
    except (ValueError, TypeError):
        lab_number = 1
    if lab_number < 1 or lab_number > max_lab:
        flash(f"Номер лабораторной должен быть от 1 до {max_lab}.", "danger")
        return redirect(url_for("main.session_detail", session_id=session.id))

    try:
        work_count = int(request.form.get("work_count", "1"))
    except (ValueError, TypeError):
        work_count = 1
    work_count = _clamp(work_count, 1, max_lab - lab_number + 1)

    try:
        estimated_minutes = int(request.form.get("estimated_minutes", "10"))
    except (ValueError, TypeError):
        estimated_minutes = subject.minutes_per_lab
    estimated_minutes = _clamp(estimated_minutes, 1, 180)

    time_preference = request.form.get("time_preference", "any")
    if time_preference not in {"early", "later", "any"}:
        time_preference = "any"

    entry = QueueEntry(
        session=session,
        student=current_user,
        lab_number=lab_number,
        work_count=work_count,
        estimated_minutes=estimated_minutes,
        time_preference=time_preference,
        note=request.form.get("note", "").strip() or None,
        position=next_position(session.id),
        status="waiting",
    )
    db.session.add(entry)
    db.session.commit()
    broadcast_session_update(session.id)
    flash("Вы добавлены в очередь.", "success")
    return redirect(url_for("main.session_detail", session_id=session.id))


@main_bp.route("/entries/<int:entry_id>/leave", methods=["POST"])
@login_required
def leave_queue(entry_id: int):
    entry = QueueEntry.query.get_or_404(entry_id)
    # Студент может выйти только сам. Преподаватель — только из своей очереди.
    if entry.student_id != current_user.id:
        if not can_manage_queue(current_user):
            abort(403)
        if not _can_manage_session(entry.session):
            flash("Вы можете управлять только своими очередями.", "danger")
            return redirect(url_for("main.session_detail", session_id=entry.session_id))
    entry.status = "cancelled"
    normalize_positions(entry.session_id)
    db.session.commit()
    broadcast_session_update(entry.session_id)
    flash("Запись отменена.", "info")
    return redirect(url_for("main.session_detail", session_id=entry.session_id))


@main_bp.route("/entries/<int:entry_id>/confirm", methods=["POST"])
@login_required
def confirm_entry(entry_id: int):
    entry = QueueEntry.query.get_or_404(entry_id)
    if entry.student_id != current_user.id and not can_manage_queue(current_user):
        abort(403)
    entry.is_confirmed = True
    attendance = Attendance.query.filter_by(student_id=entry.student_id, session_id=entry.session_id).first()
    if not attendance:
        attendance = Attendance(student_id=entry.student_id, session_id=entry.session_id, is_present=True, marked_by_id=current_user.id)
        db.session.add(attendance)
    else:
        attendance.is_present = True
        attendance.marked_by_id = current_user.id
    db.session.commit()
    broadcast_session_update(entry.session_id)
    flash("Присутствие подтверждено.", "success")
    return redirect(url_for("main.session_detail", session_id=entry.session_id))


@main_bp.route("/entries/<int:entry_id>/move/<direction>", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def move_queue_entry(entry_id: int, direction: str):
    entry = QueueEntry.query.get_or_404(entry_id)
    if not _can_manage_session(entry.session):
        flash("Вы можете управлять только своими очередями.", "danger")
        return redirect(url_for("main.session_detail", session_id=entry.session_id))
    if direction not in {"up", "down"}:
        abort(404)
    if move_entry(entry, direction):
        db.session.commit()
        broadcast_session_update(entry.session_id)
    return redirect(url_for("main.session_detail", session_id=entry.session_id))


@main_bp.route("/entries/<int:entry_id>/call", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def call_queue_entry(entry_id: int):
    entry = QueueEntry.query.get_or_404(entry_id)
    if not _can_manage_session(entry.session):
        flash("Вы можете управлять только своими очередями.", "danger")
        return redirect(url_for("main.session_detail", session_id=entry.session_id))
    call_entry(entry)
    db.session.commit()
    broadcast_session_update(entry.session_id)
    flash(f"Вызван студент: {entry.student.full_name}.", "success")
    return redirect(url_for("main.session_detail", session_id=entry.session_id))


@main_bp.route("/entries/<int:entry_id>/pass", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def pass_queue_entry(entry_id: int):
    entry = QueueEntry.query.get_or_404(entry_id)
    if not _can_manage_session(entry.session):
        flash("Вы можете управлять только своими очередями.", "danger")
        return redirect(url_for("main.session_detail", session_id=entry.session_id))
    grade = request.form.get("grade", "зачтено").strip() or "зачтено"
    comment = request.form.get("comment", "").strip() or None

    existing_grade = GradeRecord.query.filter_by(
        student_id=entry.student_id,
        subject_id=entry.session.subject_id,
        lab_number=entry.lab_number,
    ).first()
    if existing_grade:
        existing_grade.grade = grade
        existing_grade.comment = comment
        existing_grade.teacher_id = current_user.id
    else:
        db.session.add(
            GradeRecord(
                student_id=entry.student_id,
                subject_id=entry.session.subject_id,
                lab_number=entry.lab_number,
                grade=grade,
                teacher_id=current_user.id,
                comment=comment,
            )
        )

    attendance = Attendance.query.filter_by(student_id=entry.student_id, session_id=entry.session_id).first()
    if not attendance:
        db.session.add(Attendance(student_id=entry.student_id, session_id=entry.session_id, is_present=True, marked_by_id=current_user.id))
    else:
        attendance.is_present = True
        attendance.marked_by_id = current_user.id

    entry.status = "passed"
    entry.is_confirmed = True
    normalize_positions(entry.session_id)
    db.session.commit()
    broadcast_session_update(entry.session_id)
    flash("Результат зафиксирован, студент удалён из активной очереди.", "success")
    return redirect(url_for("main.session_detail", session_id=entry.session_id))


@main_bp.route("/sessions/<int:session_id>/call-next", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def call_next(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    if not _can_manage_session(session):
        flash("Вы можете управлять только своими очередями.", "danger")
        return redirect(url_for("main.session_detail", session_id=session.id))
    entry = (
        QueueEntry.query.filter_by(session_id=session.id, status="waiting")
        .order_by(QueueEntry.position.asc(), QueueEntry.created_at.asc())
        .first()
    )
    if entry:
        call_entry(entry)
        db.session.commit()
        broadcast_session_update(session.id)
        flash(f"Вызван следующий студент: {entry.student.full_name}.", "success")
    else:
        flash("В очереди нет ожидающих студентов.", "info")
    return redirect(url_for("main.session_detail", session_id=session.id))


@main_bp.route("/teacher/sessions", methods=["GET", "POST"])
@login_required
@role_required("teacher", "admin")
def teacher_sessions():
    groups = StudyGroup.query.order_by(StudyGroup.name.asc()).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    teachers = User.query.filter_by(role="teacher").order_by(User.full_name.asc()).all()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "subject":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Введите название дисциплины.", "danger")
                return redirect(url_for("main.teacher_sessions"))
            try:
                lab_count = int(request.form.get("lab_count", "10"))
            except (ValueError, TypeError):
                lab_count = 10
            if lab_count < 1 or lab_count > 30:
                flash("Количество лабораторных должно быть от 1 до 30.", "danger")
                return redirect(url_for("main.teacher_sessions"))
            try:
                minutes_per_lab = int(request.form.get("minutes_per_lab", "15"))
            except (ValueError, TypeError):
                minutes_per_lab = 15
            if minutes_per_lab < 1 or minutes_per_lab > 120:
                flash("Время на лабораторную должно быть от 1 до 120 минут.", "danger")
                return redirect(url_for("main.teacher_sessions"))
            group = StudyGroup.query.get_or_404(int(request.form.get("group_id")))
            teacher_id = request.form.get("teacher_id") or current_user.id
            subject = Subject(
                name=name,
                group=group,
                teacher_id=int(teacher_id),
                lab_count=lab_count,
                minutes_per_lab=minutes_per_lab,
            )
            db.session.add(subject)
            db.session.commit()
            flash("Дисциплина создана.", "success")
        elif action == "session":
            subject = Subject.query.get_or_404(int(request.form.get("subject_id")))
            try:
                starts_at = _parse_datetime_local(request.form.get("starts_at"))
            except (ValueError, TypeError):
                flash("Неверный формат даты и времени.", "danger")
                return redirect(url_for("main.teacher_sessions"))
            starts_at_aware = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
            if starts_at_aware < datetime.now(timezone.utc):
                flash("Дата начала очереди не может быть в прошлом.", "danger")
                return redirect(url_for("main.teacher_sessions"))
            title = request.form.get("title", "Защита лабораторных работ").strip() or "Защита лабораторных работ"
            session = QueueSession(
                subject=subject,
                group_id=subject.group_id,
                title=title,
                starts_at=starts_at,
                is_active=True,
            )
            db.session.add(session)
            db.session.commit()
            flash("Очередь создана.", "success")
        return redirect(url_for("main.teacher_sessions"))

    sessions = QueueSession.query.order_by(QueueSession.starts_at.desc()).all()
    return render_template("teacher_sessions.html", groups=groups, subjects=subjects, teachers=teachers, sessions=sessions)


@main_bp.route("/sessions/<int:session_id>/toggle", methods=["POST"])
@login_required
@role_required("teacher", "admin")
def toggle_session(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    if not _can_manage_session(session):
        flash("Вы можете управлять только своими очередями.", "danger")
        return redirect(url_for("main.teacher_sessions"))
    session.is_active = not session.is_active
    session.ended_at = datetime.now(timezone.utc) if not session.is_active else None
    db.session.commit()
    broadcast_session_update(session.id)
    flash("Статус очереди изменён.", "success")
    return redirect(url_for("main.teacher_sessions"))


@main_bp.route("/teacher/journal")
@login_required
@role_required("teacher", "admin")
def journal():
    subject_id = request.args.get("subject_id", type=int)
    group_id = request.args.get("group_id", type=int)

    query = _apply_journal_filters(_base_journal_query(), subject_id=subject_id, group_id=group_id)
    records = query.order_by(StudyGroup.name.asc(), User.full_name.asc(), Subject.name.asc(), GradeRecord.lab_number.asc()).all()

    subjects_query = Subject.query.order_by(Subject.name.asc())
    if current_user.role == "teacher":
        subjects_query = subjects_query.filter(or_(Subject.teacher_id == current_user.id, Subject.teacher_id.is_(None)))
    if group_id:
        subjects_query = subjects_query.filter(Subject.group_id == group_id)

    subjects = subjects_query.all()
    groups = StudyGroup.query.order_by(StudyGroup.name.asc()).all()

    return render_template(
        "journal.html",
        records=records,
        subjects=subjects,
        groups=groups,
        subject_id=subject_id,
        group_id=group_id,
    )


@main_bp.route("/admin/groups", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_groups():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name and not StudyGroup.query.filter_by(name=name).first():
            db.session.add(StudyGroup(name=name))
            db.session.commit()
            flash("Группа создана.", "success")
        else:
            flash("Группа уже существует или название пустое.", "warning")
        return redirect(url_for("main.admin_groups"))
    groups = StudyGroup.query.order_by(StudyGroup.name.asc()).all()
    return render_template("admin_groups.html", groups=groups)


@main_bp.route("/admin/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_users():
    groups = StudyGroup.query.order_by(StudyGroup.name.asc()).all()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "student")
        password = request.form.get("password", "student1234")
        group_id = request.form.get("group_id") or None
        if not email or not full_name or role not in {"student", "teacher", "admin"}:
            flash("Проверьте данные пользователя.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже существует.", "warning")
        else:
            user = User(email=email, full_name=full_name, role=role, group_id=group_id if role != "teacher" else None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Пользователь создан.", "success")
        return redirect(url_for("main.admin_users"))

    users = User.query.order_by(User.role.asc(), User.full_name.asc()).all()
    return render_template("admin_users.html", users=users, groups=groups)


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    if request.method == "POST":
        subject_id = request.form.get("subject_id", type=int)
        lab_number = request.form.get("lab_number", type=int)
        file = request.files.get("work_file")
        if not subject_id or not lab_number or not file or not file.filename:
            flash("Выберите дисциплину, номер работы и файл.", "danger")
            return redirect(url_for("main.profile"))
        subject_obj = Subject.query.get(subject_id)
        if not subject_obj:
            flash("Выбранная дисциплина не найдена.", "danger")
            return redirect(url_for("main.profile"))
        if lab_number < 1 or lab_number > subject_obj.lab_count:
            flash(f"Номер лабораторной должен быть от 1 до {subject_obj.lab_count}.", "danger")
            return redirect(url_for("main.profile"))
        original = secure_filename(file.filename)
        safe_name = f"{current_user.id}_{uuid4().hex}_{original}"
        upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / safe_name
        file.save(upload_path)
        db.session.add(
            WorkUpload(
                student_id=current_user.id,
                subject_id=subject_id,
                lab_number=lab_number,
                filename=safe_name,
                original_filename=original,
                comment=request.form.get("comment", "").strip() or None,
            )
        )
        db.session.commit()
        flash("Работа загружена.", "success")
        return redirect(url_for("main.profile"))

    uploads = WorkUpload.query.filter_by(student_id=current_user.id).order_by(WorkUpload.uploaded_at.desc()).all()
    grades = GradeRecord.query.filter_by(student_id=current_user.id).order_by(GradeRecord.date_passed.desc()).all()
    subject_lab_counts = {s.id: s.lab_count for s in subjects}
    return render_template("profile.html", subjects=subjects, uploads=uploads, grades=grades, subject_lab_counts=subject_lab_counts)


@main_bp.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename: str):
    upload = WorkUpload.query.filter_by(filename=filename).first_or_404()
    if upload.student_id != current_user.id and not can_manage_queue(current_user):
        abort(403)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@main_bp.route("/reports/journal.csv")
@login_required
@role_required("teacher", "admin")
def journal_report_csv():
    subject_id = request.args.get("subject_id", type=int)
    group_id = request.args.get("group_id", type=int)

    records = (
        _apply_journal_filters(_base_journal_query(), subject_id=subject_id, group_id=group_id)
        .order_by(StudyGroup.name.asc(), User.full_name.asc(), Subject.name.asc(), GradeRecord.lab_number.asc())
        .all()
    )

    rows: list[list[str | int]] = [["Студент", "Группа", "Предмет", "Лабораторная", "Оценка", "Дата", "Комментарий"]]
    for record in records:
        rows.append([
            record.student.full_name,
            record.student.group.name if record.student.group else "",
            record.subject.name,
            record.lab_number,
            record.grade,
            record.date_passed.strftime("%d.%m.%Y"),
            record.comment or "",
        ])

    return _make_csv_response("journal.csv", rows)


@main_bp.route("/reports/queue/<int:session_id>.csv")
@login_required
def queue_report_csv(session_id: int):
    session = QueueSession.query.get_or_404(session_id)

    rows: list[list[str | int]] = [["Позиция", "Студент", "Лабораторная", "Кол-во работ", "Предпочтение", "Время", "Подтвержден", "Статус"]]
    for entry in session.entries:
        rows.append([
            entry.position,
            entry.student.full_name,
            entry.lab_number,
            entry.work_count,
            entry.preference_title,
            entry.estimated_minutes,
            "да" if entry.is_confirmed else "нет",
            entry.status_title,
        ])

    return _make_csv_response(f"queue_{session.id}.csv", rows)
