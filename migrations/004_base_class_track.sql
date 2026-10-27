ALTER TABLE base_school_classes ADD COLUMN track TEXT;

CREATE INDEX IF NOT EXISTS idx_base_school_classes_grade_track
ON base_school_classes(grade_name, track, school_name, class_name);
