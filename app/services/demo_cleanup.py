"""Delete explicitly marked demo records without importing the demo generator."""
import sqlite3


def clear_demo_data(connection: sqlite3.Connection) -> dict[str, int]:
    """只清除匿名演示记录，保留导入批次、上传文件和所有 import 数据。"""
    demo_enrollments = connection.execute(
        """
        SELECT id, student_id, exam_id, class_id, organization_id, grade_id
        FROM student_exam_enrollments
        WHERE source='demo'
        """
    ).fetchall()
    exam_ids = {row["exam_id"] for row in demo_enrollments}
    class_ids = {row["class_id"] for row in demo_enrollments}
    organization_ids = {row["organization_id"] for row in demo_enrollments}
    grade_ids = {row["grade_id"] for row in demo_enrollments}
    student_ids = {row["student_id"] for row in demo_enrollments}

    def placeholders(values: set[int]) -> str:
        return ",".join("?" for _ in values)

    counts = {
        "results": 0,
        "enrollments": len(demo_enrollments),
        "students": 0,
        "exams": 0,
        "classes": 0,
        "organizations": 0,
        "grades": 0,
    }
    try:
        connection.execute("BEGIN IMMEDIATE")
        if demo_enrollments:
            enrollment_ids = {row["id"] for row in demo_enrollments}
            counts["results"] = connection.execute(
                f"SELECT COUNT(*) AS count FROM exam_results WHERE enrollment_id IN ({placeholders(enrollment_ids)})",
                tuple(enrollment_ids),
            ).fetchone()["count"]
            connection.execute(
                f"DELETE FROM exam_results WHERE enrollment_id IN ({placeholders(enrollment_ids)})",
                tuple(enrollment_ids),
            )
            connection.execute(
                f"DELETE FROM student_exam_enrollments WHERE id IN ({placeholders(enrollment_ids)})",
                tuple(enrollment_ids),
            )

        connection.execute("DELETE FROM class_targets WHERE source='demo'")
        connection.execute("DELETE FROM score_lines WHERE source='demo'")

        if exam_ids:
            cursor = connection.execute(
                f"""
                DELETE FROM exams
                WHERE id IN ({placeholders(exam_ids)})
                  AND NOT EXISTS (SELECT 1 FROM exam_results er WHERE er.exam_id=exams.id)
                  AND NOT EXISTS (SELECT 1 FROM student_exam_enrollments se WHERE se.exam_id=exams.id)
                """,
                tuple(exam_ids),
            )
            counts["exams"] = cursor.rowcount
        if student_ids:
            cursor = connection.execute(
                f"""
                DELETE FROM students
                WHERE id IN ({placeholders(student_ids)})
                  AND student_no LIKE 'DEMO%'
                  AND NOT EXISTS (SELECT 1 FROM exam_results er WHERE er.student_id=students.id)
                  AND NOT EXISTS (SELECT 1 FROM student_exam_enrollments se WHERE se.student_id=students.id)
                """,
                tuple(student_ids),
            )
            counts["students"] = cursor.rowcount
        if class_ids:
            cursor = connection.execute(
                f"""
                DELETE FROM classes
                WHERE id IN ({placeholders(class_ids)})
                  AND NOT EXISTS (SELECT 1 FROM student_exam_enrollments se WHERE se.class_id=classes.id)
                  AND NOT EXISTS (SELECT 1 FROM class_targets ct WHERE ct.class_id=classes.id)
                """,
                tuple(class_ids),
            )
            counts["classes"] = cursor.rowcount
        if organization_ids:
            cursor = connection.execute(
                f"""
                DELETE FROM organizations
                WHERE id IN ({placeholders(organization_ids)})
                  AND NOT EXISTS (SELECT 1 FROM classes c WHERE c.organization_id=organizations.id)
                  AND NOT EXISTS (SELECT 1 FROM student_exam_enrollments se WHERE se.organization_id=organizations.id)
                """,
                tuple(organization_ids),
            )
            counts["organizations"] = cursor.rowcount
        if grade_ids:
            cursor = connection.execute(
                f"""
                DELETE FROM grades
                WHERE id IN ({placeholders(grade_ids)})
                  AND NOT EXISTS (SELECT 1 FROM exams e WHERE e.grade_id=grades.id)
                  AND NOT EXISTS (SELECT 1 FROM classes c WHERE c.grade_id=grades.id)
                  AND NOT EXISTS (SELECT 1 FROM student_exam_enrollments se WHERE se.grade_id=grades.id)
                """,
                tuple(grade_ids),
            )
            counts["grades"] = cursor.rowcount
        connection.execute("DELETE FROM operation_logs WHERE action='seed_demo'")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return counts
