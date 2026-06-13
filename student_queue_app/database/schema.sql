-- PostgreSQL-схема для учебного веб-приложения управления очередями студентов.
-- Приложение также умеет создавать эту схему автоматически через SQLAlchemy.

CREATE TABLE IF NOT EXISTS study_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(32),
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'teacher', 'admin')),
    group_id INTEGER REFERENCES study_groups(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);

CREATE TABLE IF NOT EXISTS subjects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_subject_name_group UNIQUE (name, group_id)
);

CREATE TABLE IF NOT EXISTS queue_sessions (
    id SERIAL PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL DEFAULT 'Очередь на защиту',
    starts_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS queue_entries (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES queue_sessions(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lab_number INTEGER NOT NULL CHECK (lab_number > 0),
    work_count INTEGER NOT NULL DEFAULT 1 CHECK (work_count > 0),
    time_preference VARCHAR(16) NOT NULL DEFAULT 'any' CHECK (time_preference IN ('early', 'later', 'any')),
    estimated_minutes INTEGER NOT NULL DEFAULT 10 CHECK (estimated_minutes > 0),
    position INTEGER NOT NULL DEFAULT 1,
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'checking', 'passed', 'cancelled')),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_queue_entries_session_id ON queue_entries (session_id);
CREATE INDEX IF NOT EXISTS ix_queue_entries_student_id ON queue_entries (student_id);
CREATE INDEX IF NOT EXISTS ix_queue_entries_position ON queue_entries (position);
CREATE INDEX IF NOT EXISTS ix_queue_entries_status ON queue_entries (status);

CREATE TABLE IF NOT EXISTS grade_records (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    lab_number INTEGER NOT NULL CHECK (lab_number > 0),
    grade VARCHAR(32) NOT NULL,
    date_passed DATE NOT NULL DEFAULT CURRENT_DATE,
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_grade_student_subject_lab UNIQUE (student_id, subject_id, lab_number)
);

CREATE INDEX IF NOT EXISTS ix_grade_records_student_id ON grade_records (student_id);
CREATE INDEX IF NOT EXISTS ix_grade_records_subject_id ON grade_records (subject_id);

CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES queue_sessions(id) ON DELETE CASCADE,
    is_present BOOLEAN NOT NULL DEFAULT FALSE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    marked_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_attendance_student_session UNIQUE (student_id, session_id)
);

CREATE INDEX IF NOT EXISTS ix_attendance_student_id ON attendance (student_id);
CREATE INDEX IF NOT EXISTS ix_attendance_session_id ON attendance (session_id);

CREATE TABLE IF NOT EXISTS work_uploads (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    lab_number INTEGER NOT NULL CHECK (lab_number > 0),
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    comment TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_work_uploads_student_id ON work_uploads (student_id);
CREATE INDEX IF NOT EXISTS ix_work_uploads_subject_id ON work_uploads (subject_id);
