-- Ordinary student numbers may be reused, so this lookup index is intentionally non-unique.
CREATE INDEX IF NOT EXISTS idx_students_display_number_name
ON students(display_student_no, name);
