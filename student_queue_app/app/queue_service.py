from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func

from .extensions import db
from .models import GradeRecord, QueueEntry, QueueSession, User

VISIBLE_QUEUE_STATUSES = {"waiting", "checking"}


def normalize_positions(session_id: int) -> None:
    entries = (
        QueueEntry.query.filter(QueueEntry.session_id == session_id, QueueEntry.status.in_(VISIBLE_QUEUE_STATUSES))
        .order_by(QueueEntry.position.asc(), QueueEntry.created_at.asc())
        .all()
    )
    for index, entry in enumerate(entries, start=1):
        entry.position = index


def next_position(session_id: int) -> int:
    max_pos = (
        db.session.query(func.max(QueueEntry.position))
        .filter(QueueEntry.session_id == session_id, QueueEntry.status.in_(VISIBLE_QUEUE_STATUSES))
        .scalar()
    )
    return int(max_pos or 0) + 1


def passed_count(student_id: int, subject_id: int) -> int:
    return GradeRecord.query.filter_by(student_id=student_id, subject_id=subject_id).count()


def clean_expired_unconfirmed(session: QueueSession) -> int:
    """Отменяет неподтвержденные записи после начала занятия.

    В учебной версии это простая контроллерная логика вместо отдельного фонового воркера.
    """
    now = datetime.now(timezone.utc)
    if session.starts_at and session.starts_at <= now:
        expired = QueueEntry.query.filter_by(session_id=session.id, is_confirmed=False, status="waiting").all()
        for entry in expired:
            entry.status = "cancelled"
        if expired:
            normalize_positions(session.id)
        return len(expired)
    return 0


def serialize_session(session: QueueSession) -> dict[str, Any]:
    entries = (
        QueueEntry.query.filter(QueueEntry.session_id == session.id, QueueEntry.status.in_(VISIBLE_QUEUE_STATUSES))
        .order_by(QueueEntry.position.asc(), QueueEntry.created_at.asc())
        .all()
    )
    rows = []
    for entry in entries:
        rows.append(
            {
                "id": entry.id,
                "position": entry.position,
                "student_id": entry.student_id,
                "student_name": entry.student.full_name,
                "lab_number": entry.lab_number,
                "work_count": entry.work_count,
                "passed_count": passed_count(entry.student_id, session.subject_id),
                "preference": entry.preference_title,
                "estimated_minutes": entry.estimated_minutes,
                "status": entry.status,
                "status_title": entry.status_title,
                "is_confirmed": entry.is_confirmed,
                "note": entry.note or "",
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
        )
    return {
        "type": "snapshot",
        "session": {
            "id": session.id,
            "title": session.title,
            "subject": session.subject.name,
            "group": session.group.name,
            "starts_at": session.starts_at.isoformat() if session.starts_at else None,
            "is_active": session.is_active,
        },
        "entries": rows,
    }


def call_entry(entry: QueueEntry) -> None:
    QueueEntry.query.filter_by(session_id=entry.session_id, status="checking").update({"status": "waiting"})
    entry.status = "checking"
    entry.is_confirmed = True


def move_entry(entry: QueueEntry, direction: str) -> bool:
    if entry.status not in VISIBLE_QUEUE_STATUSES:
        return False

    normalize_positions(entry.session_id)
    db.session.flush()
    order = (
        QueueEntry.query.filter(QueueEntry.session_id == entry.session_id, QueueEntry.status.in_(VISIBLE_QUEUE_STATUSES))
        .order_by(QueueEntry.position.asc(), QueueEntry.created_at.asc())
        .all()
    )
    index = order.index(entry)
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(order):
        return False

    other = order[target_index]
    entry.position, other.position = other.position, entry.position
    return True


def get_available_students_for_admin() -> list[User]:
    return User.query.filter(User.role.in_(["student", "admin"])).order_by(User.full_name.asc()).all()
