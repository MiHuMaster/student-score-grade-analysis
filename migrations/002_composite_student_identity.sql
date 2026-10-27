ALTER TABLE students ADD COLUMN display_student_no TEXT;
ALTER TABLE students ADD COLUMN identity_key TEXT;
ALTER TABLE students ADD COLUMN student_type TEXT NOT NULL DEFAULT '普通生';

UPDATE students
SET display_student_no = student_no,
    identity_key = 'legacy|' || student_no
WHERE display_student_no IS NULL OR identity_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_students_identity_key
ON students(identity_key);

CREATE INDEX IF NOT EXISTS idx_students_display_student_no
ON students(display_student_no);
