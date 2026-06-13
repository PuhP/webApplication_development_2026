from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import QueueEntry, QueueSession, StudyGroup, Subject, User
from .queue_service import next_position


def _user(email: str, full_name: str, password: str, role: str, group: StudyGroup | None = None) -> User:
    existing = User.query.filter_by(email=email).first()
    if existing:
        return existing
    user = User(email=email, full_name=full_name, role=role, group=group)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def init_database(seed_demo: bool = True, recreate: bool = False) -> None:
    if recreate:
        db.drop_all()
        print("[DB] Все таблицы удалены.")
    db.create_all()
    print("[DB] Схема создана.")
    if seed_demo:
        seed_demo_data()


def seed_demo_data() -> None:
    try:
        group = StudyGroup.query.filter_by(name="241-326").first()
        if not group:
            group = StudyGroup(name="241-326")
            db.session.add(group)
            db.session.flush()

        admin = _user("admin@example.com", "Алексеева Мария Сергеевна", "admin1234", "admin", group)
        teacher = _user("teacher@example.com", "Кружалов Алексей Сергеевич", "teacher1234", "teacher", None)
        student = _user("student@example.com", "Иванов Иван Иванович", "student1234", "student", group)
        student2 = _user("petrova@example.com", "Петрова Анна Дмитриевна", "student1234", "student", group)
        student3 = _user("sidorov@example.com", "Сидоров Павел Олегович", "student1234", "student", group)

        subject = Subject.query.filter_by(name="Разработка веб-приложений", group_id=group.id).first()
        if not subject:
            subject = Subject(
                name="Разработка веб-приложений",
                teacher=teacher,
                group=group,
                lab_count=8,
                minutes_per_lab=20,
            )
            db.session.add(subject)
            db.session.flush()

        session = QueueSession.query.filter_by(subject_id=subject.id, group_id=group.id, is_active=True).first()
        if not session:
            session = QueueSession(
                title="Защита лабораторных работ",
                subject=subject,
                group=group,
                starts_at=datetime.now(timezone.utc) + timedelta(hours=2),
                is_active=True,
            )
            db.session.add(session)
            db.session.flush()

        if not QueueEntry.query.filter_by(session_id=session.id).first():
            demo_entries = [
                (student,  3, 1, "any",   20, True),
                (student2, 2, 2, "early", 15, True),
                (student3, 4, 1, "later", 12, False),
            ]
            for demo_student, lab, count, pref, minutes, confirmed in demo_entries:
                entry = QueueEntry(
                    session=session,
                    student=demo_student,
                    lab_number=lab,
                    work_count=count,
                    time_preference=pref,
                    estimated_minutes=minutes,
                    is_confirmed=confirmed,
                    position=next_position(session.id),
                    status="waiting",
                )
                db.session.add(entry)
                db.session.flush()

        db.session.commit()
        print("[DB] Демо-данные загружены.")
        print("[DB] Логины для входа:")
        print("       admin@example.com    / admin1234   (Администратор)")
        print("       teacher@example.com  / teacher1234 (Преподаватель)")
        print("       student@example.com  / student1234 (Студент)")
    except IntegrityError:
        db.session.rollback()
        print("[DB] Демо-данные уже существуют, пропуск.")
