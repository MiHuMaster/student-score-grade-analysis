CREATE TABLE IF NOT EXISTS base_class_targets (
    id INTEGER PRIMARY KEY,
    base_class_id INTEGER NOT NULL REFERENCES base_school_classes(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,
    target_order INTEGER NOT NULL DEFAULT 0,
    target_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(base_class_id, target_name)
);

CREATE TABLE IF NOT EXISTS class_stage_targets (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,
    target_order INTEGER NOT NULL DEFAULT 0,
    target_count INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'import',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(class_id, target_name)
);

INSERT OR IGNORE INTO base_class_targets(base_class_id, target_name, target_order, target_count)
SELECT id, '特控', 0, control_target
FROM base_school_classes
WHERE control_target IS NOT NULL;

INSERT OR IGNORE INTO class_stage_targets(class_id, target_name, target_order, target_count, source)
SELECT id, '特控', 0, control_target, 'legacy'
FROM classes
WHERE control_target IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_base_class_targets_class_order
ON base_class_targets(base_class_id, target_order, target_name);

CREATE INDEX IF NOT EXISTS idx_class_stage_targets_class_order
ON class_stage_targets(class_id, target_order, target_name);
