from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

import click
from flask import Flask, current_app, g

from .config import CORE_RULE_VERSION, SUBJECTS


def connect_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_database(current_app.config["DATABASE"])
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def _migration_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "migrations"
    return sorted(root.glob("*.sql"))


def _identity_text(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def _priority1_identity_key(student_number: object, name: object) -> str:
    return f"regular|{_identity_text(student_number)}|{_identity_text(name)}"


def run_priority1_data_migration(connection: sqlite3.Connection) -> dict[str, int]:
    """Merge safe legacy identities and remove only fully unreferenced grades.

    `students.student_no` remains the unique internal compatibility key; the real
    school number stays in `display_student_no`. Any same-exam collision aborts
    and rolls back the complete data migration instead of overwriting facts.
    """
    marker = CORE_RULE_VERSION
    required_actions = {
        "student_identity_migration",
        "orphan_grades_cleanup",
    }
    completed = {
        row["action"] for row in connection.execute(
            """SELECT action FROM operation_logs
               WHERE target_type='data_migration' AND target_id=?
                 AND action IN (
                   'student_identity_migration',
                   'orphan_grades_cleanup'
                 )""",
            (marker,),
        ).fetchall()
    }
    if completed == required_actions:
        return {"merged_students": 0, "orphan_grades": 0}

    try:
        connection.execute("BEGIN IMMEDIATE")
        students = connection.execute(
            """SELECT id, student_no, display_student_no, name, archived_at
               FROM students"""
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for student in students:
            display_number = student["display_student_no"]
            if not display_number:
                internal_number = str(student["student_no"] or "")
                if internal_number.startswith("regular|"):
                    continue
                display_number = internal_number
            if not _identity_text(display_number) or not _identity_text(student["name"]):
                continue
            groups[_priority1_identity_key(display_number, student["name"])].append(student)

        conflicts: list[dict] = []
        for identity_key, group in groups.items():
            if len(group) < 2:
                continue
            student_ids = [student["id"] for student in group]
            placeholders = ",".join("?" for _ in student_ids)
            overlaps = connection.execute(
                f"""SELECT exam_id, GROUP_CONCAT(DISTINCT student_id) AS student_ids
                    FROM student_exam_enrollments
                    WHERE student_id IN ({placeholders})
                    GROUP BY exam_id HAVING COUNT(DISTINCT student_id)>1""",
                student_ids,
            ).fetchall()
            if overlaps:
                conflicts.append(
                    {
                        "identity_key": identity_key,
                        "student_ids": student_ids,
                        "exam_ids": [row["exam_id"] for row in overlaps],
                    }
                )
        if conflicts:
            raise RuntimeError(
                "学生身份迁移发现同场考试冲突，已停止且未修改数据："
                + json.dumps(conflicts, ensure_ascii=False)
            )

        eligible_ids = [student["id"] for group in groups.values() for student in group]
        for student_id in eligible_ids:
            temporary_key = f"priority1-temp|{student_id}"
            connection.execute(
                "UPDATE students SET student_no=?, identity_key=? WHERE id=?",
                (temporary_key, temporary_key, student_id),
            )

        merged_students = 0
        for identity_key, group in groups.items():
            ordered = sorted(group, key=lambda row: (row["archived_at"] is not None, row["id"]))
            canonical_id = ordered[0]["id"]
            for duplicate in ordered[1:]:
                connection.execute(
                    "UPDATE exam_results SET student_id=? WHERE student_id=?",
                    (canonical_id, duplicate["id"]),
                )
                connection.execute(
                    "UPDATE student_exam_enrollments SET student_id=? WHERE student_id=?",
                    (canonical_id, duplicate["id"]),
                )
                connection.execute("DELETE FROM students WHERE id=?", (duplicate["id"],))
                merged_students += 1
            connection.execute(
                "UPDATE students SET student_no=?, identity_key=? WHERE id=?",
                (identity_key, identity_key, canonical_id),
            )

        orphan_rows = connection.execute(
            """SELECT g.id FROM grades g
               WHERE NOT EXISTS (SELECT 1 FROM exams e WHERE e.grade_id=g.id)
                 AND NOT EXISTS (SELECT 1 FROM classes c WHERE c.grade_id=g.id)
                 AND NOT EXISTS (
                   SELECT 1 FROM student_exam_enrollments se WHERE se.grade_id=g.id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM base_students bs WHERE bs.grade_name=g.name
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM base_school_classes bc WHERE bc.grade_name=g.name
                 )"""
        ).fetchall()
        connection.executemany(
            "DELETE FROM grades WHERE id=?", [(row["id"],) for row in orphan_rows]
        )

        if "student_identity_migration" not in completed:
            connection.execute(
                """INSERT INTO operation_logs(action, target_type, target_id, summary)
                   VALUES ('student_identity_migration', 'data_migration', ?, ?)""",
                (marker, json.dumps({"merged_students": merged_students}, ensure_ascii=False)),
            )
        if "orphan_grades_cleanup" not in completed:
            connection.execute(
                """INSERT INTO operation_logs(action, target_type, target_id, summary)
                   VALUES ('orphan_grades_cleanup', 'data_migration', ?, ?)""",
                (marker, json.dumps({"deleted_grades": len(orphan_rows)}, ensure_ascii=False)),
            )
        connection.commit()
        return {
            "merged_students": merged_students,
            "orphan_grades": len(orphan_rows),
        }
    except Exception:
        connection.rollback()
        raise


def run_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for migration in _migration_files():
        version = migration.stem.split("_", 1)[0]
        if version in applied:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
        )
        connection.commit()
    connection.commit()
    run_priority1_data_migration(connection)


def seed_reference_data(connection: sqlite3.Connection) -> None:
    for definition in SUBJECTS.values():
        connection.execute(
            """
            INSERT INTO subjects(code, name, category, default_max_score)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
              name=excluded.name,
              category=excluded.category,
              default_max_score=excluded.default_max_score
            """,
            (
                definition.code,
                definition.name,
                definition.category,
                definition.default_max_score,
            ),
        )
    connection.execute("UPDATE rule_versions SET is_active=0 WHERE version<>?", (CORE_RULE_VERSION,))
    connection.execute(
        """
        INSERT INTO rule_versions(version, name, is_active, rules_json)
        VALUES (?, '核心业务规则', 1, ?)
        ON CONFLICT(version) DO UPDATE SET
          is_active=1,
          name=excluded.name,
          rules_json=excluded.rules_json
        """,
        (
            CORE_RULE_VERSION,
            json.dumps(
                {
                    "student_identity": "student_no+name",
                    "exam_identity": "grade+name+date",
                    "effective_total": "scaled_or_complete_six_subject_sum",
                    "critical_windows": [40, 60, 90],
                    "population_standard_deviation": True,
                },
                ensure_ascii=False,
            ),
        ),
    )
    connection.commit()


def init_app_database() -> None:
    connection = get_db()
    run_migrations(connection)
    seed_reference_data(connection)


@click.command("init-db")
def init_db_command() -> None:
    init_app_database()
    click.echo("数据库迁移完成。")


@click.command("seed-demo")
def seed_demo_command() -> None:
    from .services.demo import seed_demo_data

    seed_demo_data(get_db())
    click.echo("演示数据已写入。")


@click.command("clear-demo")
def clear_demo_command() -> None:
    from .services.demo import clear_demo_data

    counts = clear_demo_data(get_db())
    click.echo(
        "演示数据已清除："
        f"{counts['exams']} 场考试、{counts['students']} 名学生、"
        f"{counts['results']} 条成绩。上传批次和原始文件均已保留。"
    )


def register_cli(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(clear_demo_command)
