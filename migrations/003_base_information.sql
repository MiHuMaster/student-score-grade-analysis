CREATE TABLE IF NOT EXISTS base_school_classes (
    id INTEGER PRIMARY KEY,
    province TEXT,
    school_name TEXT NOT NULL,
    grade_name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    planned_size INTEGER,
    control_target INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(school_name, grade_name, class_name)
);

CREATE TABLE IF NOT EXISTS base_students (
    id INTEGER PRIMARY KEY,
    school_name TEXT NOT NULL,
    grade_name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    student_name TEXT NOT NULL,
    student_no TEXT NOT NULL,
    subject_tag TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(school_name, grade_name, class_name, student_no)
);

CREATE INDEX IF NOT EXISTS idx_base_students_match
ON base_students(student_no, class_name, student_name);
