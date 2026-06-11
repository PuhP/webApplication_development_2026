from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudyGroup(db.Model):
    __tablename__ = "study_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    students = db.relationship("User", back_populates="group", foreign_keys="User.group_id")
    subjects = db.relationship("Subject", back_populates="group", cascade="all, delete-orphan")
    sessions = db.relationship("QueueSession", back_populates="group", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<StudyGroup {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(32))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="student", index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    group = db.relationship("StudyGroup", back_populates="students", foreign_keys=[group_id])
    taught_subjects = db.relationship("Subject", back_populates="teacher", foreign_keys="Subject.teacher_id")
    queue_entries = db.relationship("QueueEntry", back_populates="student", foreign_keys="QueueEntry.student_id")
    grades = db.relationship("GradeRecord", back_populates="student", foreign_keys="GradeRecord.student_id")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_manager(self) -> bool:
        return self.role in {"teacher", "admin"}

    @property
    def role_title(self) -> str:
        return {"student": "Студент", "teacher": "Преподаватель", "admin": "Администратор"}.get(self.role, self.role)

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    teacher = db.relationship("User", back_populates="taught_subjects", foreign_keys=[teacher_id])
    group = db.relationship("StudyGroup", back_populates="subjects")
    sessions = db.relationship("QueueSession", back_populates="subject", cascade="all, delete-orphan")
    grades = db.relationship("GradeRecord", back_populates="subject", cascade="all, delete-orphan")
    uploads = db.relationship("WorkUpload", back_populates="subject", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("name", "group_id", name="uq_subject_name_group"),)

    def __repr__(self) -> str:
        return f"<Subject {self.name}>"


class QueueSession(db.Model):
    __tablename__ = "queue_sessions"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(255), nullable=False, default="Очередь на защиту")
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at = db.Column(db.DateTime(timezone=True))

    subject = db.relationship("Subject", back_populates="sessions")
    group = db.relationship("StudyGroup", back_populates="sessions")
    entries = db.relationship(
        "QueueEntry",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="QueueEntry.position.asc(), QueueEntry.created_at.asc()",
    )
    attendance = db.relationship("Attendance", back_populates="session", cascade="all, delete-orphan")

    @property
    def status_title(self) -> str:
        if self.is_active:
            return "Активна"
        return "Завершена"

    def __repr__(self) -> str:
        return f"<QueueSession {self.id} {self.title}>"


class QueueEntry(db.Model):
    __tablename__ = "queue_entries"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("queue_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lab_number = db.Column(db.Integer, nullable=False)
    work_count = db.Column(db.Integer, nullable=False, default=1)
    time_preference = db.Column(db.String(16), nullable=False, default="any")
    estimated_minutes = db.Column(db.Integer, nullable=False, default=10)
    position = db.Column(db.Integer, nullable=False, default=1, index=True)
    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="waiting", index=True)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    session = db.relationship("QueueSession", back_populates="entries")
    student = db.relationship("User", back_populates="queue_entries", foreign_keys=[student_id])


    @property
    def status_title(self) -> str:
        return {
            "waiting": "Ожидает",
            "checking": "Сдаёт",
            "passed": "Сдал",
            "cancelled": "Отменено",
        }.get(self.status, self.status)

    @property
    def preference_title(self) -> str:
        return {"early": "Раньше", "later": "Позже", "any": "Без разницы"}.get(self.time_preference, self.time_preference)


class GradeRecord(db.Model):
    __tablename__ = "grade_records"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    lab_number = db.Column(db.Integer, nullable=False)
    grade = db.Column(db.String(32), nullable=False)
    date_passed = db.Column(db.Date, default=lambda: utcnow().date(), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    student = db.relationship("User", back_populates="grades", foreign_keys=[student_id])
    teacher = db.relationship("User", foreign_keys=[teacher_id])
    subject = db.relationship("Subject", back_populates="grades")

    __table_args__ = (db.UniqueConstraint("student_id", "subject_id", "lab_number", name="uq_grade_student_subject_lab"),)


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("queue_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    is_present = db.Column(db.Boolean, default=False, nullable=False)
    date = db.Column(db.Date, default=lambda: utcnow().date(), nullable=False)
    marked_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    student = db.relationship("User", foreign_keys=[student_id])
    marked_by = db.relationship("User", foreign_keys=[marked_by_id])
    session = db.relationship("QueueSession", back_populates="attendance")

    __table_args__ = (db.UniqueConstraint("student_id", "session_id", name="uq_attendance_student_session"),)


class WorkUpload(db.Model):
    __tablename__ = "work_uploads"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    lab_number = db.Column(db.Integer, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    comment = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    student = db.relationship("User", foreign_keys=[student_id])
    subject = db.relationship("Subject", back_populates="uploads")
