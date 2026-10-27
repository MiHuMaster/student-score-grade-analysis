from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date

from app.config import CORE_RULE_VERSION, SUBJECTS
from app.services.importer import build_exam_key
from app.services.demo_cleanup import clear_demo_data


def _get_or_create(connection: sqlite3.Connection, table: str, values: dict) -> int:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    where = " AND ".join(f"{column}=?" for column in values)
    row = connection.execute(
        f"SELECT id FROM {table} WHERE {where}", tuple(values.values())
    ).fetchone()
    return int(row["id"])


def _clip(value: float, low: float, high: float) -> float:
    return round(min(high, max(low, value)), 1)


def seed_demo_data(connection: sqlite3.Connection) -> None:
    rng = random.Random(20260828)
    grade_name = "高2027届"
    grade_id = _get_or_create(connection, "grades", {"name": grade_name})
    schools = [
        ("测试中学", "01", "物理"),
        ("测试中学", "02", "物理"),
        ("测试中学", "03", "历史"),
        ("测试中学", "04", "历史"),
    ]
    class_rows = []
    for school_name, class_name, track in schools:
        organization_id = _get_or_create(
            connection,
            "organizations",
            {"name": school_name, "province": "重庆"},
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO classes(
              organization_id, grade_id, class_name, track, planned_size, control_target
            ) VALUES (?, ?, ?, ?, 30, ?)
            """,
            (organization_id, grade_id, class_name, track, 15 if track == "物理" else 12),
        )
        class_id = connection.execute(
            """
            SELECT id FROM classes
            WHERE organization_id=? AND grade_id=? AND class_name=? AND track=?
            """,
            (organization_id, grade_id, class_name, track),
        ).fetchone()["id"]
        class_rows.append((organization_id, class_id, class_name, track))

    exams = [
        ("高二下第一次月考", date(2026, 3, 18), -14),
        ("高二下期中考试", date(2026, 4, 23), 0),
        ("高二下第二次月考", date(2026, 5, 28), 10),
    ]
    exam_rows = []
    for exam_name, exam_date, difficulty_shift in exams:
        exam_key = build_exam_key(grade_name, exam_name, exam_date)
        connection.execute(
            """
            INSERT OR IGNORE INTO exams(
              exam_key, grade_id, name, exam_date, school_year_term, exam_type, total_max_score
            ) VALUES (?, ?, ?, ?, '2025-2026学年下学期', '常规考试', 750)
            """,
            (exam_key, grade_id, exam_name, exam_date.isoformat()),
        )
        exam_id = connection.execute(
            "SELECT id FROM exams WHERE exam_key=?", (exam_key,)
        ).fetchone()["id"]
        exam_rows.append((exam_id, exam_key, difficulty_shift))
        for track in ("物理", "历史"):
            for line_type, base in (("特控", 500), ("211", 570), ("985", 630)):
                line_value = base + (3 if track == "历史" else 0)
                connection.execute(
                    """
                    INSERT INTO score_lines(
                      exam_id, track, line_type, subject_code, line_value, source, rule_version
                    ) VALUES (?, ?, ?, '__TOTAL__', ?, 'demo', ?)
                    ON CONFLICT(exam_id, track, line_type, subject_code)
                    DO UPDATE SET line_value=excluded.line_value
                    """,
                    (exam_id, track, line_type, line_value, CORE_RULE_VERSION),
                )
        for definition in SUBJECTS.values():
            for track in ("物理", "历史"):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO exam_subjects(
                      exam_id, subject_code, track, max_score, score_mode
                    ) VALUES (?, ?, ?, ?, 'raw_or_scaled')
                    """,
                    (exam_id, definition.code, track, definition.default_max_score),
                )

    for class_index, (organization_id, class_id, class_name, track) in enumerate(class_rows):
        class_target = 15 if track == "物理" else 12
        for exam_id, _exam_key, _shift in exam_rows:
            connection.execute(
                """
                INSERT INTO class_targets(exam_id, class_id, line_type, target_count, source)
                VALUES (?, ?, '特控', ?, 'demo')
                ON CONFLICT(exam_id, class_id, line_type)
                DO UPDATE SET target_count=excluded.target_count
                """,
                (exam_id, class_id, class_target),
            )
        for student_index in range(30):
            serial = class_index * 30 + student_index + 1
            student_no = f"DEMO{serial:04d}"
            name = f"演示学生{serial:03d}"
            connection.execute(
                "INSERT OR IGNORE INTO students(student_no, name) VALUES (?, ?)",
                (student_no, name),
            )
            student_id = connection.execute(
                "SELECT id FROM students WHERE student_no=?", (student_no,)
            ).fetchone()["id"]
            ability = rng.gauss(0, 1) + (0.25 if class_name in {"01", "03"} else -0.1)
            if track == "物理":
                elective_pool = ["chemistry", "biology", "politics", "geography"]
            else:
                elective_pool = ["politics", "geography", "biology", "chemistry"]
            elective_codes = rng.sample(elective_pool, 2)
            primary_code = "physics" if track == "物理" else "history"
            subject_codes = ["chinese", "math", "english", primary_code, *elective_codes]
            for exam_index, (exam_id, _exam_key, difficulty_shift) in enumerate(exam_rows):
                if rng.random() < 0.025 and exam_index != 2:
                    continue
                improvement = exam_index * rng.gauss(5.0, 5.5)
                scores: dict[str, float] = {}
                for code in subject_codes:
                    maximum = SUBJECTS[code].default_max_score
                    base_rate = 0.66 + ability * 0.09 + difficulty_shift / 750 + improvement / 750
                    subject_noise = rng.gauss(0, 0.075)
                    if code == "math":
                        subject_noise += ability * 0.025
                    scores[code] = _clip((base_rate + subject_noise) * maximum, 0, maximum)
                effective_total = round(sum(scores.values()), 1)
                raw_total = round(effective_total - rng.choice([0, 2, 4, 6]), 1)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO student_exam_enrollments(
                      student_id, exam_id, organization_id, grade_id, class_id, track,
                      elective_subjects_json, student_type, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo')
                    """,
                    (
                        student_id,
                        exam_id,
                        organization_id,
                        grade_id,
                        class_id,
                        track,
                        json.dumps(elective_codes, ensure_ascii=False),
                        "普通生",
                    ),
                )
                enrollment_id = connection.execute(
                    "SELECT id FROM student_exam_enrollments WHERE student_id=? AND exam_id=?",
                    (student_id, exam_id),
                ).fetchone()["id"]
                connection.execute(
                    """
                    INSERT INTO exam_results(
                      exam_id, student_id, enrollment_id, raw_total, scaled_total,
                      effective_total, total_source, attendance_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'scaled', 'normal')
                    ON CONFLICT(exam_id, student_id) DO UPDATE SET
                      enrollment_id=excluded.enrollment_id,
                      raw_total=excluded.raw_total,
                      scaled_total=excluded.scaled_total,
                      effective_total=excluded.effective_total,
                      total_source='scaled',
                      attendance_status='normal',
                      updated_at=CURRENT_TIMESTAMP
                    """,
                    (exam_id, student_id, enrollment_id, raw_total, effective_total, effective_total),
                )
                result_id = connection.execute(
                    "SELECT id FROM exam_results WHERE exam_id=? AND student_id=?",
                    (exam_id, student_id),
                ).fetchone()["id"]
                for code, score in scores.items():
                    scaled = score if SUBJECTS[code].category == "elective" else None
                    connection.execute(
                        """
                        INSERT INTO subject_scores(
                          exam_result_id, subject_code, raw_score, scaled_score, effective_score
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(exam_result_id, subject_code) DO UPDATE SET
                          raw_score=excluded.raw_score,
                          scaled_score=excluded.scaled_score,
                          effective_score=excluded.effective_score
                        """,
                        (result_id, code, score, scaled, score),
                    )
    connection.execute(
        "INSERT INTO operation_logs(action, target_type, summary) VALUES ('seed_demo', 'database', '写入可重复的匿名演示数据')"
    )
    connection.commit()
