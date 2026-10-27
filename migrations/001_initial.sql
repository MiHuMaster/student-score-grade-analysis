CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    province TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    grade_id INTEGER NOT NULL REFERENCES grades(id),
    class_name TEXT NOT NULL,
    track TEXT NOT NULL CHECK(track IN ('物理', '历史')),
    planned_size INTEGER,
    control_target INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT,
    UNIQUE(organization_id, grade_id, class_name, track)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    student_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY,
    exam_key TEXT NOT NULL UNIQUE,
    grade_id INTEGER NOT NULL REFERENCES grades(id),
    name TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    school_year_term TEXT,
    exam_type TEXT,
    total_max_score REAL NOT NULL DEFAULT 750,
    data_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT,
    UNIQUE(grade_id, name, exam_date)
);

CREATE TABLE IF NOT EXISTS subjects (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    default_max_score REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_subjects (
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    subject_code TEXT NOT NULL REFERENCES subjects(code),
    track TEXT NOT NULL CHECK(track IN ('物理', '历史')),
    max_score REAL NOT NULL,
    score_mode TEXT NOT NULL DEFAULT 'raw_or_scaled',
    PRIMARY KEY(exam_id, subject_code, track)
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    batch_key TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_size INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'previewed',
    row_count INTEGER NOT NULL DEFAULT 0,
    valid_row_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_batches_hash
ON import_batches(source_sha256);

CREATE TABLE IF NOT EXISTS import_issues (
    id INTEGER PRIMARY KEY,
    import_batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK(severity IN ('error', 'warning')),
    sheet_name TEXT,
    row_number INTEGER,
    field_name TEXT,
    raw_value TEXT,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    suggestion TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_issues_batch
ON import_issues(import_batch_id, severity);

CREATE TABLE IF NOT EXISTS student_exam_enrollments (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    grade_id INTEGER NOT NULL REFERENCES grades(id),
    class_id INTEGER NOT NULL REFERENCES classes(id),
    track TEXT NOT NULL CHECK(track IN ('物理', '历史')),
    elective_subjects_json TEXT NOT NULL DEFAULT '[]',
    student_type TEXT NOT NULL DEFAULT '普通生',
    source TEXT NOT NULL DEFAULT 'import',
    UNIQUE(student_id, exam_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_exam_scope
ON student_exam_enrollments(exam_id, organization_id, class_id, track);

CREATE TABLE IF NOT EXISTS exam_results (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id),
    enrollment_id INTEGER NOT NULL REFERENCES student_exam_enrollments(id) ON DELETE CASCADE,
    raw_total REAL,
    scaled_total REAL,
    effective_total REAL,
    total_source TEXT NOT NULL CHECK(total_source IN ('scaled', 'raw', 'derived', 'missing')),
    network_rank_raw INTEGER,
    network_rank_scaled INTEGER,
    attendance_status TEXT NOT NULL DEFAULT 'normal',
    import_batch_id INTEGER REFERENCES import_batches(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_results_exam_total
ON exam_results(exam_id, attendance_status, effective_total DESC);

CREATE TABLE IF NOT EXISTS subject_scores (
    id INTEGER PRIMARY KEY,
    exam_result_id INTEGER NOT NULL REFERENCES exam_results(id) ON DELETE CASCADE,
    subject_code TEXT NOT NULL REFERENCES subjects(code),
    raw_score REAL,
    grade_level TEXT,
    scaled_score REAL,
    effective_score REAL,
    network_rank_raw INTEGER,
    network_rank_scaled INTEGER,
    UNIQUE(exam_result_id, subject_code)
);

CREATE INDEX IF NOT EXISTS idx_subject_scores_subject
ON subject_scores(subject_code, exam_result_id);

CREATE TABLE IF NOT EXISTS score_lines (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    track TEXT NOT NULL CHECK(track IN ('物理', '历史')),
    line_type TEXT NOT NULL CHECK(line_type IN ('特控', '211', '985', '本科')),
    subject_code TEXT NOT NULL DEFAULT '__TOTAL__',
    line_value REAL NOT NULL,
    source TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_id, track, line_type, subject_code)
);

CREATE INDEX IF NOT EXISTS idx_score_lines_lookup
ON score_lines(exam_id, track, line_type, subject_code);

CREATE TABLE IF NOT EXISTS class_targets (
    id INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    line_type TEXT NOT NULL DEFAULT '特控',
    target_count INTEGER,
    source TEXT NOT NULL DEFAULT 'import',
    UNIQUE(exam_id, class_id, line_type)
);

CREATE TABLE IF NOT EXISTS field_mappings (
    id INTEGER PRIMARY KEY,
    source_signature TEXT NOT NULL,
    template_version TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_signature, template_version)
);

CREATE TABLE IF NOT EXISTS rule_versions (
    id INTEGER PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_snapshots (
    id INTEGER PRIMARY KEY,
    cache_key TEXT NOT NULL UNIQUE,
    exam_scope_json TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    data_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    invalidated_at TEXT
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
