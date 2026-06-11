import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'queue_app.sqlite3'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "app" / "uploads"))
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    TEACHER_INVITE_CODE = os.getenv("TEACHER_INVITE_CODE", "teacher2026")
    ADMIN_INVITE_CODE = os.getenv("ADMIN_INVITE_CODE", "admin2026")
