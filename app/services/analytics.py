from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from statistics import fmean, pstdev

from app.config import (
    CORE_RULE_VERSION,
    CRITICAL_BOUNDARY,
    DEFAULT_CRITICAL_WINDOW,
    FIXED_BAND_BOUNDARY,
    LINE_BAND_BOUNDARY,
    LINE_TYPES,
    SUBJECTS,
    TOTAL_LINE_TYPES,
)


LINE_BAND_DISPLAY_LABELS = (
    "0-线下90分", "线下90分-线下40分", "线下40分-特控线",
    "特控线-211线", "211线-985线", "985线以上",
)


@dataclass(frozen=True)
class Scope:
    exam_key: str
    track: str | None = None
    organization_id: int | None = None
    class_id: int | None = None


def list_exams(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT e.exam_key, e.name, e.exam_date, g.name AS grade,
               e.total_max_score, e.data_version,
               COUNT(DISTINCT CASE
                 WHEN er.attendance_status='normal' AND er.effective_total IS NOT NULL
                 THEN er.student_id
               END) AS reference_count
        FROM exams e
        JOIN grades g ON g.id=e.grade_id
        LEFT JOIN exam_results er ON er.exam_id=e.id
        WHERE e.archived_at IS NULL
        GROUP BY e.id
        ORDER BY e.exam_date DESC, e.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def filter_options(connection: sqlite3.Connection, exam_key: str | None = None) -> dict:
    params: list[object] = []
    exam_clause = ""
    if exam_key:
        exam_clause = "AND e.exam_key=?"
        params.append(exam_key)
    organizations = connection.execute(
        f"""
        SELECT DISTINCT o.id, o.name
        FROM organizations o
        JOIN student_exam_enrollments se ON se.organization_id=o.id
        JOIN exams e ON e.id=se.exam_id
        WHERE o.archived_at IS NULL {exam_clause}
        ORDER BY o.name
        """,
        params,
    ).fetchall()
    classes = connection.execute(
        f"""
        SELECT DISTINCT c.id, c.class_name, c.track, o.name AS organization_name
        FROM classes c
        JOIN organizations o ON o.id=c.organization_id
        JOIN student_exam_enrollments se ON se.class_id=c.id
        JOIN exams e ON e.id=se.exam_id
        WHERE c.archived_at IS NULL {exam_clause}
        ORDER BY o.name, c.track, c.class_name
        """,
        params,
    ).fetchall()
    target_names: list[str] = []
    default_target_name = None
    if exam_key:
        exam = _exam(connection, exam_key)
        target_names = _target_names(connection, exam["grade_id"])
        default_target_name = _default_target_name(exam["name"], target_names)
    return {
        "organizations": [dict(row) for row in organizations],
        "classes": [dict(row) for row in classes],
        "tracks": ["物理", "历史"],
        "targets": target_names,
        "default_target_name": default_target_name,
        "target_missing_reason": None if default_target_name else "未设置默认高考目标，请选择目标方案",
    }


def _exam(connection: sqlite3.Connection, exam_key: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT e.*, g.name AS grade_name
        FROM exams e JOIN grades g ON g.id=e.grade_id
        WHERE e.exam_key=? AND e.archived_at IS NULL
        """,
        (exam_key,),
    ).fetchone()
    if row is None:
        raise ValueError("考试不存在")
    return row


def _scope_where(scope: Scope, alias: str = "se") -> tuple[str, list[object]]:
    clauses = ["er.attendance_status='normal'", "er.effective_total IS NOT NULL"]
    params: list[object] = []
    if scope.track:
        clauses.append(f"{alias}.track=?")
        params.append(scope.track)
    if scope.organization_id:
        clauses.append(f"{alias}.organization_id=?")
        params.append(scope.organization_id)
    if scope.class_id:
        clauses.append(f"{alias}.class_id=?")
        params.append(scope.class_id)
    return " AND ".join(clauses), params


def _result_rows(
    connection: sqlite3.Connection,
    scope: Scope,
    keyword: str | None = None,
    limit: int | None = None,
) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    exam = _exam(connection, scope.exam_key)
    where, params = _scope_where(scope)
    search_clause = ""
    query_params: list[object] = [exam["id"], *params]
    cleaned_keyword = (keyword or "").strip()
    if cleaned_keyword:
        escaped = cleaned_keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        search_clause = """AND (
          student_name LIKE ? ESCAPE '\\' OR student_no LIKE ? ESCAPE '\\'
          OR organization_name LIKE ? ESCAPE '\\' OR class_name LIKE ? ESCAPE '\\'
        )"""
        query_params.extend([pattern, pattern, pattern, pattern])
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        query_params.append(max(1, int(limit)))
    rows = connection.execute(
        f"""
        WITH ranked_results AS (
          SELECT er.*, se.track, se.student_type, se.class_id, se.organization_id,
                 c.class_name, o.name AS organization_name,
                 COALESCE(s.display_student_no, s.student_no) AS student_no,
                 COALESCE(s.identity_key, 'legacy|' || s.student_no) AS identity_key,
                 s.name AS student_name,
                 ROW_NUMBER() OVER (
                   PARTITION BY er.student_id
                   ORDER BY COALESCE(er.updated_at, er.created_at) DESC, er.id DESC
                 ) AS duplicate_rank
          FROM exam_results er
          JOIN student_exam_enrollments se ON se.id=er.enrollment_id
          JOIN classes c ON c.id=se.class_id
          JOIN organizations o ON o.id=se.organization_id
          JOIN students s ON s.id=er.student_id
          WHERE er.exam_id=? AND {where}
        )
        SELECT * FROM ranked_results
        WHERE duplicate_rank=1 {search_clause}
        ORDER BY effective_total DESC, identity_key ASC
        {limit_clause}
        """,
        query_params,
    ).fetchall()
    return exam, rows


def _target_names(connection: sqlite3.Connection, grade_id: int) -> list[str]:
    rows = connection.execute(
        """SELECT cst.target_name, MIN(cst.target_order) AS target_order
           FROM class_stage_targets cst
           JOIN classes c ON c.id=cst.class_id
           WHERE c.grade_id=? AND c.archived_at IS NULL
           GROUP BY cst.target_name
           ORDER BY target_order, cst.target_name""",
        (grade_id,),
    ).fetchall()
    return [row["target_name"] for row in rows]


def _default_target_name(exam_name: str, target_names: list[str]) -> str | None:
    return next((name for name in target_names if name in {"高考", "高考目标"}), None)


def _resolve_target_name(
    connection: sqlite3.Connection,
    exam: sqlite3.Row,
    target_name: str | None,
) -> tuple[str | None, list[str]]:
    target_names = _target_names(connection, exam["grade_id"])
    selected = (target_name or "").strip() or _default_target_name(exam["name"], target_names)
    if selected and selected not in target_names and selected.endswith("目标") and selected[:-2] in target_names:
        selected = selected[:-2]
    if selected and selected not in target_names:
        raise ValueError("所选目标方案不属于当前考试年级")
    return selected, target_names


def _line_map(connection: sqlite3.Connection, exam_id: int, track: str | None) -> dict[str, float | None]:
    if not track:
        return {line_type: None for line_type in TOTAL_LINE_TYPES}
    rows = connection.execute(
        """
        SELECT line_type, line_value FROM score_lines
        WHERE exam_id=? AND track=? AND subject_code='__TOTAL__'
        """,
        (exam_id, track),
    ).fetchall()
    values = {row["line_type"]: row["line_value"] for row in rows}
    return {line_type: values.get(line_type) for line_type in TOTAL_LINE_TYPES}


def _safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    return None if not denominator else numerator / denominator





def _score_label(value: float | int | None) -> str:
    if value is None:
        return ""
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.2f}".rstrip("0").rstrip(".")


def _mround_half(value: float | Decimal | None) -> float | None:
    if value is None:
        return None
    number = Decimal(str(value))
    multiple = Decimal("0.5")
    units = (number / multiple).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(units * multiple)


def _scope_for_exam(scope: Scope, exam_key: str) -> Scope:
    return Scope(
        exam_key=exam_key,
        track=scope.track,
        organization_id=scope.organization_id,
        class_id=scope.class_id,

    )


def comparison_exams(
    connection: sqlite3.Connection,
    current_exam: sqlite3.Row,
    exam_keys: list[str] | None = None,
    limit: int = 5,
) -> list[sqlite3.Row]:
    """Resolve a stable, same-grade comparison set for analysis and exports."""
    if exam_keys is None:
        return connection.execute(
            """
            SELECT e.* FROM exams e
            WHERE e.grade_id=? AND e.exam_date<=? AND e.archived_at IS NULL
            ORDER BY e.exam_date, e.id
            """,
            (current_exam["grade_id"], current_exam["exam_date"]),
        ).fetchall()
    selected_keys = list(dict.fromkeys(key for key in exam_keys if key))
    if current_exam["exam_key"] not in selected_keys:
        raise ValueError("历次考试对比必须包含单次考试。")
    if len(selected_keys) > limit:
        raise ValueError(f"历次考试对比最多选择{limit}场考试。")
    placeholders = ",".join("?" for _ in selected_keys)
    rows = connection.execute(
        f"""
        SELECT e.* FROM exams e
        WHERE e.exam_key IN ({placeholders}) AND e.archived_at IS NULL
        ORDER BY e.exam_date, e.id
        """,
        selected_keys,
    ).fetchall()
    if len(rows) != len(selected_keys):
        raise ValueError("所选历次考试不存在或已归档。")
    if any(row["grade_id"] != current_exam["grade_id"] for row in rows):
        raise ValueError("单次考试与历次考试对比必须属于同一年级。")
    return rows


def _comparison_previous(exams: list[sqlite3.Row], current_exam: sqlite3.Row) -> sqlite3.Row | None:
    current_order = (current_exam["exam_date"], current_exam["id"])
    previous = [row for row in exams if (row["exam_date"], row["id"]) < current_order]
    return previous[-1] if previous else None


def _previous_exam(connection: sqlite3.Connection, exam: sqlite3.Row) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT e.* FROM exams e
        WHERE e.grade_id=? AND e.exam_date<? AND e.archived_at IS NULL
        ORDER BY e.exam_date DESC, e.id DESC LIMIT 1
        """,
        (exam["grade_id"], exam["exam_date"]),
    ).fetchone()


def grade_statistics(connection: sqlite3.Connection, exam_key: str, track: str | None) -> dict:
    """本校同次考试同方向的已导入有效成绩；不受班级和搜索筛选影响。"""
    _exam_row, rows = _result_rows(connection, Scope(exam_key, track))
    result_ids = [row["id"] for row in rows]
    effective = {"__TOTAL__": {row["id"]: float(row["effective_total"]) for row in rows}}
    raw_scores = {"__TOTAL__": {row["id"]: float(row["raw_total"]) for row in rows if row["raw_total"] is not None}}
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        for item in connection.execute(
            f"SELECT exam_result_id, subject_code, effective_score, raw_score FROM subject_scores WHERE exam_result_id IN ({placeholders})",
            result_ids,
        ):
            code, result_id = item["subject_code"], item["exam_result_id"]
            if item["effective_score"] is not None:
                effective.setdefault(code, {})[result_id] = float(item["effective_score"])
            if item["raw_score"] is not None:
                raw_scores.setdefault(code, {})[result_id] = float(item["raw_score"])
    def ranks(values):
        positions = {}
        for position, value in enumerate(sorted(values.values(), reverse=True), start=1):
            positions.setdefault(value, position)
        return {key: positions[value] for key, value in values.items()}
    return {
        "averages": {code: fmean(values.values()) for code, values in effective.items() if values},
        "counts": {code: len(values) for code, values in effective.items()},
        "ranks": {code: ranks(values) for code, values in effective.items()},
        "raw_ranks": {code: ranks(values) for code, values in raw_scores.items()},
        "reference_count": len(rows),
        "class_count": len({row["class_id"] for row in rows}),
        "scope_note": "本校同次考试同方向已导入有效成绩；请核对是否覆盖全年级",
    }


def _benchmark_average_map(connection: sqlite3.Connection, exam_id: int, track: str | None) -> dict[str, float]:
    # Keep the existing internal comparison interface, but never read uploaded averages.
    if not track:
        return {}
    exam = connection.execute("SELECT exam_key FROM exams WHERE id=?", (exam_id,)).fetchone()
    return grade_statistics(connection, exam["exam_key"], track)["averages"] if exam else {}


def subject_line_pairs(track: str | None) -> tuple[tuple[str, str], ...]:
    """返回当前方向的（权威来源科目, 共用划线科目）配对。"""
    if track == "物理":
        return (("chemistry", "politics"), ("biology", "geography"))
    if track == "历史":
        return (("politics", "chemistry"), ("geography", "biology"))
    return ()


def _derived_subject_lines(
    connection: sqlite3.Connection,
    exam_key: str,
    track: str | None,
) -> dict[str, dict[str, float | None]]:
    """按模板口径，用整场同方向总分上线学生推导单科线，并舍入到 0.5。"""
    if not track:
        return {}
    exam, full_rows = _result_rows(connection, Scope(exam_key, track))
    result_by_id = {row["id"]: row for row in full_rows}
    result_ids = list(result_by_id)
    score_rows = []
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        score_rows = connection.execute(
            f"""
            SELECT exam_result_id, subject_code, scaled_score, effective_score
            FROM subject_scores
            WHERE exam_result_id IN ({placeholders})
              AND (scaled_score IS NOT NULL OR effective_score IS NOT NULL)
            """,
            result_ids,
        ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in score_rows:
        grouped[row["subject_code"]].append(row)
    total_lines = _line_map(connection, exam["id"], track)
    output: dict[str, dict[str, float | None]] = {}
    for code, values in grouped.items():
        output[code] = {}
        for line_type in LINE_TYPES:
            total_line = total_lines.get(line_type)
            # 模板等价公式：MROUND(AVERAGEIF(总分,">="&线,学科分)
            # * 线 / AVERAGEIF(总分,">="&线,总分), 0.5)。分母必须是
            # 同方向全部总分达线考生，而不是仅有该学科成绩的子集。
            eligible_totals = [
                Decimal(str(row["scaled_total"]))
                for row in full_rows
                if total_line is not None and row["scaled_total"] is not None
                and Decimal(str(row["scaled_total"])) >= Decimal(str(total_line))
            ]
            use_scaled_score = code in {"chemistry", "biology", "politics", "geography"}
            subject_values = [
                Decimal(str(value["scaled_score"] if use_scaled_score else value["effective_score"]))
                for value in values
                if total_line is not None
                and (value["scaled_score"] if use_scaled_score else value["effective_score"]) is not None
                and result_by_id[value["exam_result_id"]]["scaled_total"] is not None
                and Decimal(str(result_by_id[value["exam_result_id"]]["scaled_total"]))
                >= Decimal(str(total_line))
            ]
            if not eligible_totals or not subject_values or total_line is None:
                output[code][line_type] = None
            else:
                subject_average = sum(subject_values) / Decimal(len(subject_values))
                total_average = sum(eligible_totals) / Decimal(len(eligible_totals))
                raw_line = subject_average * Decimal(str(total_line)) / total_average
                output[code][line_type] = _mround_half(raw_line)
    manual_rows = connection.execute(
        """
        SELECT subject_code, line_type, line_value
        FROM score_lines
        WHERE exam_id=? AND track=? AND subject_code<>'__TOTAL__'
        """,
        (exam["id"], track),
    ).fetchall()
    manual_lines: dict[str, dict[str, float]] = defaultdict(dict)
    for row in manual_rows:
        manual_lines[row["subject_code"]][row["line_type"]] = float(row["line_value"])
        output.setdefault(row["subject_code"], {})[row["line_type"]] = float(row["line_value"])

    # 赋分再选科执行正式的固定配对划线，而不是缺失时才回退。
    # 无人工线时始终取当前方向的权威来源科目；任一侧有人工线时整组共用。
    for authority_code, shared_code in subject_line_pairs(track):
        output.setdefault(authority_code, {})
        output.setdefault(shared_code, {})
        for line_type in LINE_TYPES:
            configured = {
                manual_lines[code][line_type]
                for code in (authority_code, shared_code)
                if line_type in manual_lines.get(code, {})
            }
            if len(configured) > 1:
                raise ValueError(
                    f"配对科目划线冲突：{track}方向"
                    f"{SUBJECTS[authority_code].name}与{SUBJECTS[shared_code].name}"
                    f"的{line_type}线必须一致"
                )
            shared_value = (
                next(iter(configured))
                if configured
                else output[authority_code].get(line_type)
            )
            output[authority_code][line_type] = shared_value
            output[shared_code][line_type] = shared_value
    return output


def _class_online_counts(rows: list[sqlite3.Row], line: float | None) -> dict[tuple[str, str, str], int]:
    if line is None:
        return {}
    output: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        key = (row["organization_name"], row["class_name"], row["track"])
        output[key] += int(float(row["effective_total"]) >= line)
    return dict(output)





def _target_summary(
    connection: sqlite3.Connection,
    exam_id: int,
    rows: list[sqlite3.Row],
    line: float | None,
    target_name: str | None,
) -> dict:
    if line is None:
        return {"target_name": target_name, "configured_classes": 0, "met": 0, "missed": 0, "rate": None, "details": []}
    class_scores: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        class_scores[row["class_id"]].append(row["effective_total"])
    targets = connection.execute(
        """
        SELECT c.id AS class_id,
               CASE WHEN ?='特控' THEN COALESCE(ct.target_count, cst.target_count)
                    ELSE cst.target_count END AS target_count,
               c.class_name, o.name AS organization_name
        FROM classes c
        JOIN organizations o ON o.id=c.organization_id
        LEFT JOIN class_stage_targets cst
          ON cst.class_id=c.id AND cst.target_name=?
        LEFT JOIN class_targets ct
          ON ct.class_id=c.id AND ct.exam_id=? AND ct.line_type='特控'
        WHERE (CASE WHEN ?='特控' THEN COALESCE(ct.target_count, cst.target_count)
                    ELSE cst.target_count END) IS NOT NULL
        """,
        (target_name, target_name, exam_id, target_name),
    ).fetchall()
    details = []
    for target in targets:
        if target["class_id"] not in class_scores:
            continue
        actual = sum(score >= line for score in class_scores[target["class_id"]])
        target_count = target["target_count"]
        difference = actual - target_count
        details.append(
            {
                "class_id": target["class_id"],
                "class_name": target["class_name"],
                "organization_name": target["organization_name"],
                "actual": actual,
                "target": target_count,
                "difference": difference,
                "status": "超目标" if difference > 0 else "差目标" if difference < 0 else "持平",
            }
        )
    met = sum(item["difference"] >= 0 for item in details)
    return {
        "target_name": target_name,
        "configured_classes": len(details),
        "met": met,
        "missed": len(details) - met,
        "rate": _safe_rate(met, len(details)),
        "details": details,
    }


def overview(
    connection: sqlite3.Connection,
    scope: Scope,
    critical_window: int = DEFAULT_CRITICAL_WINDOW,
    exam_keys: list[str] | None = None,
    target_name: str | None = None,
) -> dict:
    exam, rows = _result_rows(connection, scope)
    selected_target_name, target_names = _resolve_target_name(connection, exam, target_name)
    comparable_exams = comparison_exams(connection, exam, exam_keys)
    scores = [float(row["effective_total"]) for row in rows]
    lines = _line_map(connection, exam["id"], scope.track)
    line_metrics = {}
    for line_type, line in lines.items():
        if line is None:
            line_metrics[line_type] = {
                "line": None,
                "count": None,
                "rate": None,
                "missing_reason": "请选择方向并配置对应总分线",
            }
            continue
        count = sum(score >= line for score in scores)
        line_metrics[line_type] = {
            "line": line,
            "count": count,
            "rate": _safe_rate(count, len(scores)),
            "missing_reason": None,
        }
    control_line = lines.get("特控")
    critical_count = None
    if control_line is not None:
        critical_count = sum(control_line - critical_window <= score < control_line for score in scores)
    target_summary = _target_summary(connection, exam["id"], rows, control_line, selected_target_name)
    group_metrics = student_groups(connection, scope, critical_window, exam_keys)
    previous = _comparison_previous(comparable_exams, exam)
    class_line_changes = {"increased": 0, "decreased": 0, "unchanged": 0, "comparable_classes": 0, "previous_exam": None}
    if previous is not None and scope.track and control_line is not None:
        previous_scope = _scope_for_exam(scope, previous["exam_key"])
        _previous_exam_row, previous_rows = _result_rows(connection, previous_scope)
        previous_control = _line_map(connection, previous["id"], scope.track).get("特控")
        if previous_control is not None:
            current_counts = _class_online_counts(rows, control_line)
            previous_counts = _class_online_counts(previous_rows, previous_control)
            common_classes = set(current_counts) & set(previous_counts)
            differences = [current_counts[key] - previous_counts[key] for key in common_classes]
            class_line_changes = {
                "increased": sum(value > 0 for value in differences),
                "decreased": sum(value < 0 for value in differences),
                "unchanged": sum(value == 0 for value in differences),
                "comparable_classes": len(common_classes),
                "previous_exam": {"exam_key": previous["exam_key"], "name": previous["name"], "date": previous["exam_date"]},
            }
    ordinary_count = len(rows)
    history = []
    for comparable in comparable_exams:
        snapshot_exam, snapshot_rows = _result_rows(
            connection, _scope_for_exam(scope, comparable["exam_key"])
        )
        snapshot_scores = [float(row["effective_total"]) for row in snapshot_rows]
        snapshot_lines = _line_map(connection, snapshot_exam["id"], scope.track)
        snapshot_control = snapshot_lines.get("特控")
        snapshot_online = (
            sum(score >= snapshot_control for score in snapshot_scores)
            if snapshot_control is not None
            else None
        )
        snapshot_critical = (
            sum(snapshot_control - 40 <= score < snapshot_control for score in snapshot_scores)
            if snapshot_control is not None
            else None
        )
        history.append({
            "exam_key": comparable["exam_key"],
            "exam_name": comparable["name"],
            "exam_date": comparable["exam_date"],
            "reference_count": len(snapshot_scores),
            "average": fmean(snapshot_scores) if snapshot_scores else None,
            "standard_deviation": pstdev(snapshot_scores) if snapshot_scores else None,
            "critical_count": snapshot_critical,
            "control_count": snapshot_online,
            "control_rate": _safe_rate(snapshot_online, len(snapshot_scores)) if snapshot_online is not None else None,
            "line_211_count": (
                sum(score >= snapshot_lines["211"] for score in snapshot_scores)
                if snapshot_lines.get("211") is not None else None
            ),
            "line_985_count": (
                sum(score >= snapshot_lines["985"] for score in snapshot_scores)
                if snapshot_lines.get("985") is not None else None
            ),
        })
    return {
        "exam": {
            "exam_key": exam["exam_key"],
            "name": exam["name"],
            "date": exam["exam_date"],
            "grade": exam["grade_name"],
            "total_max_score": exam["total_max_score"],
            "data_version": exam["data_version"],
        },
        "scope": {
            "track": scope.track,
            "target_name": selected_target_name,
            "target_names": target_names,
            "target_missing_reason": None if selected_target_name else "未设置默认高考目标，请选择目标方案",
            "organization_id": scope.organization_id,
            "class_id": scope.class_id,
        },
        "rule_version": CORE_RULE_VERSION,
        "reference_count": len(scores),
        "class_count": len({row["class_id"] for row in rows}),
        "student_types": [
            {"name": "学生", "count": ordinary_count, "rate": _safe_rate(ordinary_count, len(scores))},
        ],
        "highest": max(scores) if scores else None,
        "lowest": min(scores) if scores else None,
        "average": fmean(scores) if scores else None,
        "standard_deviation": pstdev(scores) if scores else None,
        "standard_deviation_type": "population",
        "lines": line_metrics,
        "critical": {
            "window": critical_window,
            "count": critical_count,
            "boundary": CRITICAL_BOUNDARY,
        },
        "targets": target_summary,
        "transitions": {
            "converted_count": len(group_metrics["converted"]),
            "conversion_rate": group_metrics.get("conversion_rate"),
            "newly_critical_count": len(group_metrics["newly_critical"]),
            "common_student_count": group_metrics["common_student_count"],
            "missing_reason": group_metrics.get("missing_reason"),
        },
        "class_line_changes": class_line_changes,
        "history": history,
        "data_quality": {
            "effective_total_source": "总分赋分优先，缺失时使用完整六科有效成绩之和",
            "reference_definition": "正常参考且有效总分的去重学生",
        },
    }


def score_bands(
    connection: sqlite3.Connection,
    scope: Scope,
    step: int = 50,
    include_history: bool = True,
    exam_keys: list[str] | None = None,
) -> dict:
    exam, rows = _result_rows(connection, scope)
    scores = [float(row["effective_total"]) for row in rows]
    lines = _line_map(connection, exam["id"], scope.track)
    control, line_211, line_985 = lines.get("特控"), lines.get("211"), lines.get("985")
    line_bands = []
    if all(value is not None for value in (control, line_211, line_985)):
        boundaries = [
            (f"0-{_score_label(control - 90)}", -math.inf, control - 90),
            (f"{_score_label(control - 90)}-{_score_label(control - 40)}", control - 90, control - 40),
            (f"{_score_label(control - 40)}-{_score_label(control)}", control - 40, control),
            (f"{_score_label(control)}-{_score_label(line_211)}", control, line_211),
            (f"{_score_label(line_211)}-{_score_label(line_985)}", line_211, line_985),
            (f"{_score_label(line_985)}及以上", line_985, math.inf),
        ]
        assigned = 0
        for _index, (label, low, high) in enumerate(boundaries):
            count = sum(
                (low == -math.inf or score >= low)
                and (high == math.inf or score < high)
                for score in scores
            )
            assigned += count
            line_bands.append({
                "label": label,
                "display_label": LINE_BAND_DISPLAY_LABELS[_index],
                "low": None if low == -math.inf else low,
                "high": None if high == math.inf else high,
                "count": count,
                "rate": _safe_rate(count, len(scores)),
            })
        reconcile = {"assigned": assigned, "reference_count": len(scores), "matches": assigned == len(scores)}
    else:
        reconcile = {"assigned": 0, "reference_count": len(scores), "matches": False}
    maximum = int(math.ceil(float(exam["total_max_score"]) / step) * step)
    fixed_bands = []
    for low in range(0, maximum, step):
        high = min(low + step, maximum)
        if high == maximum:
            count = sum(low <= score <= high for score in scores)
        else:
            count = sum(low <= score < high for score in scores)
        fixed_bands.append({"label": f"{low}—{high}", "count": count, "rate": _safe_rate(count, len(scores))})
    result = {
        "reference_count": len(scores),
        "line_boundary": LINE_BAND_BOUNDARY,
        "fixed_boundary": FIXED_BAND_BOUNDARY,
        "line_bands": line_bands,
        "fixed_bands": fixed_bands,
        "reconcile": reconcile,
        "missing_reason": None if line_bands else "请选择方向并配置特控、211、985三条总分线",
    }
    if include_history:
        comparable_exams = comparison_exams(connection, exam, exam_keys)
        result["history"] = []
        for comparable in comparable_exams:
            snapshot = score_bands(
                connection,
                _scope_for_exam(scope, comparable["exam_key"]),
                step,
                include_history=False,
            )
            result["history"].append(
                {
                    "exam_key": comparable["exam_key"],
                    "exam_name": comparable["name"],
                    "exam_date": comparable["exam_date"],
                    "reference_count": snapshot["reference_count"],
                    "line_bands": snapshot["line_bands"],
                    "fixed_bands": snapshot["fixed_bands"],
                }
            )
    return result


def _subject_line(
    total_line: float | None,
    eligible_pairs: list[tuple[float, float]],
) -> float | None:
    if total_line is None or not eligible_pairs:
        return None
    average_subject = fmean(pair[1] for pair in eligible_pairs)
    average_total = fmean(pair[0] for pair in eligible_pairs)
    if average_total == 0:
        return None
    return average_subject * total_line / average_total


def subject_metrics(
    connection: sqlite3.Connection,
    scope: Scope,
    include_history: bool = True,
    _derived_cache: dict[tuple[str, str | None], dict] | None = None,
    exam_keys: list[str] | None = None,
) -> dict:
    if _derived_cache is None:
        _derived_cache = {}
    exam, rows = _result_rows(connection, scope)
    if not rows:
        return {
            "reference_count": 0,
            "subjects": [],
            "history": [],
            "line_formula": "整场同方向总分上线学生的该科均分 × 对应总分线 ÷ 这些学生的总分赋分均分，再按 0.5 舍入",
            "line_rounding": "mround-0.5",
            "rate_definitions": {
                "hit_rate": "总分与该科双上线人数 ÷ 该科上线人数",
                "contribution_rate": "总分与该科双上线人数 ÷ 总分上线人数",
            },
            "missing_reason": "当前范围没有有效成绩",
        }
    result_ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in result_ids)
    subject_rows = connection.execute(
        f"""
        SELECT ss.*, s.name AS subject_name, s.default_max_score, er.effective_total
        FROM subject_scores ss
        JOIN subjects s ON s.code=ss.subject_code
        JOIN exam_results er ON er.id=ss.exam_result_id
        WHERE ss.exam_result_id IN ({placeholders}) AND ss.effective_score IS NOT NULL
        """,
        result_ids,
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in subject_rows:
        grouped[row["subject_code"]].append(row)
    total_lines = _line_map(connection, exam["id"], scope.track)
    cache_key = (exam["exam_key"], scope.track)
    if cache_key not in _derived_cache:
        _derived_cache[cache_key] = _derived_subject_lines(connection, exam["exam_key"], scope.track)
    derived_lines = _derived_cache[cache_key]
    benchmark_averages = _benchmark_average_map(connection, exam["id"], scope.track)
    total_reference_count = len(rows)
    output = []
    for code, values in grouped.items():
        scores = [float(value["effective_score"]) for value in values]
        subject_lines = {
            line_type: derived_lines.get(code, {}).get(line_type)
            for line_type in LINE_TYPES
        }
        control_line = subject_lines.get("特控")
        total_control = total_lines.get("特控")
        subject_online = sum(score >= control_line for score in scores) if control_line is not None else None
        total_online_ids = {
            row["id"] for row in rows if total_control is not None and row["effective_total"] >= total_control
        }
        both_online = (
            sum(
                value["exam_result_id"] in total_online_ids
                and value["effective_score"] >= control_line
                for value in values
            )
            if control_line is not None
            else None
        )
        output.append(
            {
                "code": code,
                "name": values[0]["subject_name"],
                "reference_count": len(scores),
                "highest": max(scores),
                "lowest": min(scores),
                "average": fmean(scores),
                "score_rate": fmean(scores) / float(values[0]["default_max_score"]),
                "benchmark_average": benchmark_averages.get(code),
                "benchmark_ratio": (
                    fmean(scores) / benchmark_averages[code]
                    if benchmark_averages.get(code)
                    else None
                ),
                "lines": subject_lines,
                "line_gap": fmean(scores) - control_line if control_line is not None else None,
                "online": {
                    line_type: {
                        "count": sum(score >= line for score in scores) if line is not None else None,
                        "rate": _safe_rate(sum(score >= line for score in scores), total_reference_count) if line is not None else None,
                    }
                    for line_type, line in subject_lines.items()
                },
                "control_online_count": subject_online,
                "control_online_rate": _safe_rate(subject_online, total_reference_count) if subject_online is not None else None,
                "both_online_count": both_online,
                "hit_rate": _safe_rate(both_online, subject_online) if both_online is not None else None,
                "contribution_rate": _safe_rate(both_online, len(total_online_ids)) if both_online is not None else None,
                "critical_10": (
                    sum(control_line - 10 <= score < control_line for score in scores)
                    if control_line is not None
                    else None
                ),
                "critical_20": (
                    sum(control_line - 20 <= score < control_line for score in scores)
                    if control_line is not None
                    else None
                ),
            }
        )
    output.sort(key=lambda item: (-item["score_rate"], item["name"]))
    if output:
        rate_average = fmean(item["score_rate"] for item in output)
        for item in output:
            delta = item["score_rate"] - rate_average
            item["diagnosis"] = "优势" if delta >= 0.05 else "薄弱" if delta <= -0.05 else "稳定"
            item["diagnosis_basis"] = f"得分率较当前多学科均值{delta:+.1%}"
    result = {
        "reference_count": len(rows),
        "subjects": output,
        "line_formula": "整场同方向总分上线学生的该科均分 × 对应总分线 ÷ 这些学生的总分赋分均分，再按 0.5 舍入",
        "line_rounding": "mround-0.5",
        "rate_definitions": {
            "hit_rate": "总分与该科双上线人数 ÷ 该科上线人数",
            "contribution_rate": "总分与该科双上线人数 ÷ 总分上线人数",
        },
    }
    if include_history:
        comparable_exams = comparison_exams(connection, exam, exam_keys)
        result["history"] = []
        for comparable in comparable_exams:
            snapshot = subject_metrics(
                connection,
                _scope_for_exam(scope, comparable["exam_key"]),
                include_history=False,
                _derived_cache=_derived_cache,
            )
            result["history"].append(
                {
                    "exam_key": comparable["exam_key"],
                    "exam_name": comparable["name"],
                    "exam_date": comparable["exam_date"],
                    "subjects": snapshot["subjects"],
                }
            )
    return result


def student_groups(
    connection: sqlite3.Connection,
    scope: Scope,
    critical_window: int = DEFAULT_CRITICAL_WINDOW,
    exam_keys: list[str] | None = None,
) -> dict:
    exam, rows = _result_rows(connection, scope)
    comparable_exams = comparison_exams(connection, exam, exam_keys)
    lines = _line_map(connection, exam["id"], scope.track)
    control = lines.get("特控")
    previous_exam = _comparison_previous(comparable_exams, exam)
    output = {
        "current_critical": [],
        "converted": [],
        "newly_critical": [],
        "common_student_count": 0,
        "previous_exam": dict(previous_exam) if previous_exam else None,
        "critical_window": critical_window,
    }
    if control is None:
        output["missing_reason"] = "请选择方向并配置特控线"
        return output
    current_by_student = {row["student_id"]: row for row in rows}
    output["current_critical"] = [
        _student_summary(row, control)
        for row in rows
        if control - critical_window <= row["effective_total"] < control
    ]
    if previous_exam is None:
        output["missing_reason"] = "缺少上一场可比考试"
        return output
    previous_line = connection.execute(
        """
        SELECT line_value FROM score_lines
        WHERE exam_id=? AND track=? AND line_type='特控' AND subject_code='__TOTAL__'
        """,
        (previous_exam["id"], scope.track),
    ).fetchone()
    if previous_line is None:
        output["missing_reason"] = "上一场考试缺少对应方向特控线"
        return output
    previous_where, previous_params = _scope_where(scope)
    previous_rows = connection.execute(
        f"""
        SELECT er.*, se.track, se.student_type, se.class_id, se.organization_id,
               c.class_name, o.name AS organization_name,
               COALESCE(s.display_student_no, s.student_no) AS student_no,
               COALESCE(s.identity_key, 'legacy|' || s.student_no) AS identity_key,
               s.name AS student_name
        FROM exam_results er
        JOIN student_exam_enrollments se ON se.id=er.enrollment_id
        JOIN classes c ON c.id=se.class_id
        JOIN organizations o ON o.id=se.organization_id
        JOIN students s ON s.id=er.student_id
        WHERE er.exam_id=? AND {previous_where}
        """,
        [previous_exam["id"], *previous_params],
    ).fetchall()
    previous_by_student = {row["student_id"]: row for row in previous_rows}
    common_ids = set(current_by_student) & set(previous_by_student)
    output["common_student_count"] = len(common_ids)
    previous_control = float(previous_line["line_value"])
    current_critical_by_identity = {
        item["identity_key"]: item for item in output["current_critical"]
    }
    for student_id in common_ids:
        current = current_by_student[student_id]
        previous = previous_by_student[student_id]
        current_critical = current_critical_by_identity.get(current["identity_key"])
        if current_critical is not None:
            current_critical["previous_total"] = previous["effective_total"]
        previously_critical = previous_control - critical_window <= previous["effective_total"] < previous_control
        currently_critical = control - critical_window <= current["effective_total"] < control
        if previously_critical and current["effective_total"] >= control:
            item = _student_summary(current, control)
            item["previous_total"] = previous["effective_total"]
            output["converted"].append(item)
        if previous["effective_total"] >= previous_control and currently_critical:
            item = _student_summary(current, control)
            item["previous_total"] = previous["effective_total"]
            output["newly_critical"].append(item)
    output["conversion_rate"] = _safe_rate(
        len(output["converted"]),
        sum(
            previous_control - critical_window <= previous_by_student[student_id]["effective_total"] < previous_control
            for student_id in common_ids
        ),
    )
    output["missing_reason"] = None
    return output


def _score_level(score: float | None, lines: dict[str, float | None], critical_gap: float) -> str:
    if score is None:
        return "missing"
    if lines.get("985") is not None and score >= lines["985"]:
        return "line-985"
    if lines.get("211") is not None and score >= lines["211"]:
        return "line-211"
    if lines.get("特控") is not None and score >= lines["特控"]:
        return "line-control"
    if lines.get("特控") is not None and score >= lines["特控"] - critical_gap:
        return "line-critical"
    return "normal"


def student_group_matrix(
    connection: sqlite3.Connection,
    scope: Scope,
    exam_limit: int = 5,
    exam_keys: list[str] | None = None,
) -> dict:
    exam, current_rows = _result_rows(connection, scope)
    if exam_keys is None:
        exam_limit = max(1, min(exam_limit, 12))
        comparable = connection.execute(
            """
            SELECT exam_key, id, name, exam_date
            FROM exams
            WHERE grade_id=? AND exam_date<=? AND archived_at IS NULL
            ORDER BY exam_date DESC, id DESC LIMIT ?
            """,
            (exam["grade_id"], exam["exam_date"], exam_limit),
        ).fetchall()[::-1]
    else:
        comparable = comparison_exams(connection, exam, exam_keys)
        latest_by_student: dict[int, sqlite3.Row] = {}
        for comparable_exam in comparable:
            _snapshot_exam, snapshot_rows = _result_rows(
                connection, _scope_for_exam(scope, comparable_exam["exam_key"])
            )
            for row in snapshot_rows:
                latest_by_student[row["student_id"]] = row
        current_rows = list(latest_by_student.values())
    exams = [dict(row) for row in comparable]
    if not current_rows or not comparable:
        return {"exams": exams, "subjects": [], "students": [], "color_rules": {}}
    student_ids = [row["student_id"] for row in current_rows]
    exam_ids = [row["id"] for row in comparable]
    student_placeholders = ",".join("?" for _ in student_ids)
    exam_placeholders = ",".join("?" for _ in exam_ids)
    result_rows = connection.execute(
        f"""
        SELECT er.id AS result_id, er.student_id, er.exam_id, er.effective_total
        FROM exam_results er
        JOIN student_exam_enrollments se ON se.id=er.enrollment_id
        WHERE er.student_id IN ({student_placeholders})
          AND er.exam_id IN ({exam_placeholders})
          AND er.attendance_status='normal' AND se.track=?
        """,
        [*student_ids, *exam_ids, scope.track],
    ).fetchall()
    result_map = {(row["student_id"], row["exam_id"]): row for row in result_rows}
    result_ids = [row["result_id"] for row in result_rows]
    score_map: dict[tuple[int, int, str], float] = {}
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        for row in connection.execute(
            f"""
            SELECT er.student_id, er.exam_id, ss.subject_code, ss.effective_score
            FROM subject_scores ss JOIN exam_results er ON er.id=ss.exam_result_id
            WHERE ss.exam_result_id IN ({placeholders}) AND ss.effective_score IS NOT NULL
            """,
            result_ids,
        ):
            score_map[(row["student_id"], row["exam_id"], row["subject_code"])] = float(row["effective_score"])
    subject_codes = [
        code for code in (
            ["chinese", "math", "english", "physics", "chemistry", "biology", "politics", "geography"]
            if scope.track == "物理"
            else ["chinese", "math", "english", "history", "politics", "geography", "chemistry", "biology"]
        )
        if any(key[2] == code for key in score_map)
    ]
    total_lines_by_exam = {
        item["id"]: _line_map(connection, item["id"], scope.track) for item in comparable
    }
    subject_lines_by_exam = {
        item["id"]: _derived_subject_lines(connection, item["exam_key"], scope.track)
        for item in comparable
    }
    students = []
    for current in current_rows:
        item = _student_summary(current)
        item["totals"] = []
        item["subjects"] = {}
        for comparable_exam in comparable:
            result = result_map.get((current["student_id"], comparable_exam["id"]))
            total = float(result["effective_total"]) if result else None
            item["totals"].append({
                "exam_key": comparable_exam["exam_key"],
                "score": total,
                "level": _score_level(total, total_lines_by_exam[comparable_exam["id"]], 40),
            })
        for code in subject_codes:
            cells = []
            for comparable_exam in comparable:
                score = score_map.get((current["student_id"], comparable_exam["id"], code))
                lines = subject_lines_by_exam[comparable_exam["id"]].get(code, {})
                cells.append({
                    "exam_key": comparable_exam["exam_key"],
                    "score": score,
                    "level": _score_level(score, lines, 10),
                })
            item["subjects"][code] = cells
        students.append(item)
    return {
        "exams": exams,
        "subjects": [{"code": code, "name": SUBJECTS[code].name} for code in subject_codes],
        "students": students,
        "total_lines": total_lines_by_exam,
        "subject_lines": subject_lines_by_exam,
        "color_rules": {
            "line-critical": "单科达到特控线下10分或总分达到特控线下40分",
            "line-control": "达到特控线",
            "line-211": "达到211线",
            "line-985": "达到985线",
        },
    }


def _rank_desc(value: float | None, values: list[float | None]) -> int | None:
    if value is None:
        return None
    return 1 + sum(item is not None and item > value for item in values)


def class_metrics(
    connection: sqlite3.Connection,
    scope: Scope,
    include_history: bool = True,
    exam_keys: list[str] | None = None,
    target_name: str | None = None,
) -> dict:
    exam = _exam(connection, scope.exam_key)
    selected_target_name, target_names = _resolve_target_name(connection, exam, target_name)
    comparable_exams = comparison_exams(connection, exam, exam_keys) if include_history or exam_keys is not None else []
    if not scope.track:
        return {"classes": [], "subjects": [], "missing_reason": "请选择方向"}
    _full_exam, full_rows = _result_rows(
        connection, Scope(scope.exam_key, scope.track, None, None)
    )
    ordinary_rows = [row for row in full_rows]
    grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in ordinary_rows:
        grouped[row["class_id"]].append(row)
    total_lines = _line_map(connection, exam["id"], scope.track)
    control = total_lines.get("特控")
    line211 = total_lines.get("211")
    line985 = total_lines.get("985")
    benchmark = _benchmark_average_map(connection, exam["id"], scope.track)
    cloud_scores = [float(row["effective_total"]) for row in ordinary_rows]
    cloud_std = pstdev(cloud_scores) if cloud_scores else None
    target_values: dict[int, dict[str, int]] = defaultdict(dict)
    class_ids = list(grouped)
    if class_ids:
        placeholders = ",".join("?" for _ in class_ids)
        for row in connection.execute(
            f"""SELECT class_id, target_name, target_count
                FROM class_stage_targets WHERE class_id IN ({placeholders})""",
            class_ids,
        ):
            target_values[row["class_id"]][row["target_name"]] = row["target_count"]
        if selected_target_name == "特控":
            for row in connection.execute(
                f"""SELECT class_id, target_count FROM class_targets
                    WHERE exam_id=? AND line_type='特控' AND class_id IN ({placeholders})""",
                [exam["id"], *class_ids],
            ):
                target_values[row["class_id"]]["特控"] = row["target_count"]
    participated_by_class: dict[int, list[dict]] = defaultdict(list)
    if class_ids:
        placeholders = ",".join("?" for _ in class_ids)
        for row in connection.execute(
            f"""SELECT DISTINCT se.class_id, e.exam_key, e.name, e.exam_date
                FROM student_exam_enrollments se
                JOIN exam_results er ON er.enrollment_id=se.id
                JOIN exams e ON e.id=se.exam_id
                WHERE se.class_id IN ({placeholders})
                  AND er.attendance_status='normal' AND er.effective_total IS NOT NULL
                  AND e.archived_at IS NULL
                ORDER BY e.exam_date, e.id""",
            class_ids,
        ):
            participated_by_class[row["class_id"]].append({
                "exam_key": row["exam_key"], "name": row["name"], "date": row["exam_date"]
            })

    previous = _comparison_previous(comparable_exams, exam) if exam_keys is not None else _previous_exam(connection, exam)
    previous_by_class: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    previous_by_student: dict[int, sqlite3.Row] = {}
    previous_control = None
    if previous is not None:
        _previous_exam_row, previous_rows = _result_rows(
            connection, Scope(previous["exam_key"], scope.track, None, None)
        )
        for row in previous_rows:
            previous_by_class[(row["organization_name"], row["class_name"], row["track"])].append(row)
            previous_by_student[row["student_id"]] = row
        previous_control = _line_map(connection, previous["id"], scope.track).get("特控")

    class_items = []
    for class_id, members in grouped.items():
        totals = [float(row["effective_total"]) for row in members]
        key = (members[0]["organization_name"], members[0]["class_name"], members[0]["track"])
        online = lambda line: sum(score >= line for score in totals) if line is not None else None
        control_count = online(control)
        previous_members = previous_by_class.get(key, [])
        previous_control_count = (
            sum(float(row["effective_total"]) >= previous_control for row in previous_members)
            if previous_control is not None and previous_members
            else None
        )
        converted = 0
        newly_critical = 0
        if previous_control is not None and control is not None:
            for row in members:
                old = previous_by_student.get(row["student_id"])
                if old is None:
                    continue
                old_score = float(old["effective_total"])
                new_score = float(row["effective_total"])
                converted += int(previous_control - 40 <= old_score < previous_control and new_score >= control)
                newly_critical += int(old_score >= previous_control and control - 40 <= new_score < control)
        target = target_values.get(class_id, {}).get(selected_target_name) if selected_target_name else None
        class_items.append({
            "class_id": class_id,
            "organization_id": members[0]["organization_id"],
            "school": key[0],
            "class_name": key[1],
            "track": key[2],
            "reference_count": len(totals),
            "highest": max(totals),
            "lowest": min(totals),
            "average": fmean(totals),
            "benchmark_average": benchmark.get("__TOTAL__"),
            "benchmark_gap": fmean(totals) - benchmark["__TOTAL__"] if benchmark.get("__TOTAL__") is not None else None,
            "benchmark_ratio": fmean(totals) / benchmark["__TOTAL__"] if benchmark.get("__TOTAL__") else None,
            "standard_deviation": pstdev(totals),
            "cloud_standard_deviation": cloud_std,
            "control_count": control_count,
            "control_rate": _safe_rate(control_count, len(totals)) if control_count is not None else None,
            "control_change": control_count - previous_control_count if control_count is not None and previous_control_count is not None else None,
            "target": target,
            "target_name": selected_target_name,
            "target_values": target_values.get(class_id, {}),
            "participated_exams": participated_by_class.get(class_id, []),
            "target_completion_rate": _safe_rate(control_count, target) if control_count is not None and target else None,
            "critical_40": sum(control - 40 <= score < control for score in totals) if control is not None else None,
            "critical_90": sum(control - 90 <= score < control for score in totals) if control is not None else None,
            "converted_count": converted,
            "newly_critical_count": newly_critical,
            "line_211_count": online(line211),
            "line_985_count": online(line985),
            "potential_count": sum(score >= control - 40 for score in totals) if control is not None else None,
        })
    averages = [item["average"] for item in class_items]
    control_rates = [item["control_rate"] for item in class_items]
    for item in class_items:
        item["cloud_rank"] = _rank_desc(item["average"], averages)
        item["average_rank"] = item["cloud_rank"]
        item["control_rate_rank"] = _rank_desc(item["control_rate"], control_rates)

    result_ids = [row["id"] for row in ordinary_rows]
    score_rows = []
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        score_rows = connection.execute(
            f"""
            SELECT ss.exam_result_id, ss.subject_code, ss.effective_score
            FROM subject_scores ss
            WHERE ss.exam_result_id IN ({placeholders}) AND ss.effective_score IS NOT NULL
            """,
            result_ids,
        ).fetchall()
    class_by_result = {row["id"]: row["class_id"] for row in ordinary_rows}
    subject_scores: dict[tuple[int, str], list[float]] = defaultdict(list)
    for row in score_rows:
        subject_scores[(class_by_result[row["exam_result_id"]], row["subject_code"])].append(float(row["effective_score"]))
    subject_lines = _derived_subject_lines(connection, exam["exam_key"], scope.track)
    codes = [code for code in SUBJECTS if any(key[1] == code for key in subject_scores)]
    subject_comparison = []
    for code in codes:
        interim = []
        lines = subject_lines.get(code, {})
        for item in class_items:
            values = subject_scores.get((item["class_id"], code), [])
            if not values:
                continue
            subject_online = lambda line: sum(score >= line for score in values) if line is not None else None
            control_subject_count = subject_online(lines.get("特控"))
            interim.append({
                "class_id": item["class_id"],
                "school": item["school"],
                "class_name": item["class_name"],
                "code": code,
                "name": SUBJECTS[code].name,
                "reference_count": len(values),
                "average": fmean(values),
                "benchmark_average": benchmark.get(code),
                "benchmark_ratio": fmean(values) / benchmark[code] if benchmark.get(code) else None,
                "lines": lines,
                "control_count": control_subject_count,
                "control_rate": _safe_rate(control_subject_count, item["reference_count"]) if control_subject_count is not None else None,
                "line_211_count": subject_online(lines.get("211")),
                "line_985_count": subject_online(lines.get("985")),
            })
        subject_averages = [item["average"] for item in interim]
        subject_rates = [item["control_rate"] for item in interim]
        for item in interim:
            item["average_rank"] = _rank_desc(item["average"], subject_averages)
            item["control_rate_rank"] = _rank_desc(item["control_rate"], subject_rates)
        subject_comparison.extend(interim)

    visible_classes = class_items
    if scope.organization_id:
        visible_classes = [item for item in visible_classes if item["organization_id"] == scope.organization_id]
    if scope.class_id:
        visible_classes = [item for item in visible_classes if item["class_id"] == scope.class_id]
    visible_ids = {item["class_id"] for item in visible_classes}
    result = {
        "exam": {"exam_key": exam["exam_key"], "name": exam["name"], "date": exam["exam_date"], "grade": exam["grade_name"]},
        "track": scope.track,
        "target_name": selected_target_name,
        "target_names": target_names,
        "target_missing_reason": None if selected_target_name else "未设置默认高考目标，请选择目标方案",
        "classes": sorted(visible_classes, key=lambda item: (item["school"], item["class_name"])),
        "subject_comparison": [item for item in subject_comparison if item["class_id"] in visible_ids],
        "comparison_classes": sorted(class_items, key=lambda item: (item["school"], item["class_name"])),
        "subject_comparison_all": subject_comparison,
        "total_lines": total_lines,
        "previous_exam": {"exam_key": previous["exam_key"], "name": previous["name"], "date": previous["exam_date"]} if previous else None,
        "definitions": {
            "target_completion_rate": "特控实际上线人数 ÷ 班级目标人数",
            "potential_count": "特控线上人数＋特控线下40分临界人数",
        },
    }
    if include_history:
        if exam_keys is None:
            comparable_exams = comparison_exams(connection, exam)
        result["history"] = []
        for comparable in comparable_exams:
            snapshot = class_metrics(
                connection,
                _scope_for_exam(scope, comparable["exam_key"]),
                include_history=False,
                exam_keys=exam_keys,
                target_name=selected_target_name,
            )
            result["history"].append({
                "exam_key": comparable["exam_key"],
                "exam_name": comparable["name"],
                "exam_date": comparable["exam_date"],
                "classes": snapshot["classes"],
            })
    return result


def benchmark_metrics(connection: sqlite3.Connection, exam_key: str) -> dict:
    exam = _exam(connection, exam_key)
    tracks = {}
    for track in ("物理", "历史"):
        grade = grade_statistics(connection, exam_key, track)
        averages = grade["averages"]
        subject_lines = _derived_subject_lines(connection, exam_key, track)
        order = ["chinese", "math", "english", "physics" if track == "物理" else "history", "chemistry", "biology", "politics", "geography"]
        tracks[track] = {
            "grade_averages": {
                "total": averages.get("__TOTAL__"),
                "subjects": [{"code": code, "name": SUBJECTS[code].name, "average": averages.get(code), "reference_count": grade["counts"].get(code, 0)} for code in order],
            },
            "reference_count": grade["reference_count"],
            "class_count": grade["class_count"],
            "scope_note": grade["scope_note"],
            "total_lines": _line_map(connection, exam["id"], track),
            "subject_lines": [{"code": code, "name": SUBJECTS[code].name, "lines": subject_lines.get(code, {})} for code in order],
        }
    return {
        "exam": {"exam_key": exam_key, "name": exam["name"], "date": exam["exam_date"], "grade": exam["grade_name"]},
        "tracks": tracks,
        "line_formula": "整场同方向总分上线学生的单科均分 × 对应总分线 ÷ 这些学生的总分赋分均分",
        "rounding": "所有单科线按 0.5 舍入",
    }


def _student_summary(row: sqlite3.Row, line: float | None = None) -> dict:
    return {
        "organization_id": row["organization_id"],
        "class_id": row["class_id"],
        "student_no": row["student_no"],
        "identity_key": row["identity_key"],
        "name": row["student_name"],
        "organization": row["organization_name"],
        "class_name": row["class_name"],
        "track": row["track"],
        "student_type": row["student_type"],
        "effective_total": row["effective_total"],
        "line_gap": row["effective_total"] - line if line is not None else None,
    }


def student_list(
    connection: sqlite3.Connection,
    scope: Scope,
    limit: int = 100,
    keyword: str | None = None,
) -> list[dict]:
    capped_limit = max(1, min(limit, 50 if keyword else 10))
    _exam_row, rows = _result_rows(connection, scope, keyword=keyword, limit=capped_limit)
    return [_student_summary(row) for row in rows]


def student_detail(
    connection: sqlite3.Connection,
    student_no: str,
    exam_key: str | None = None,
    exam_keys: list[str] | None = None,
) -> dict | None:
    student = connection.execute(
        """
        SELECT id, COALESCE(display_student_no, student_no) AS student_no,
               COALESCE(identity_key, 'legacy|' || student_no) AS identity_key, name
        FROM students
        WHERE (identity_key=? OR ('legacy|' || student_no)=? OR display_student_no=? OR student_no=?)
          AND archived_at IS NULL
        ORDER BY CASE WHEN identity_key=? OR ('legacy|' || student_no)=? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (student_no, student_no, student_no, student_no, student_no, student_no),
    ).fetchone()
    if student is None:
        return None
    exam_clause = ""
    exam_params: list[object] = []
    if exam_key:
        current_exam = _exam(connection, exam_key)
        selected_exams = comparison_exams(connection, current_exam, exam_keys)
        selected_ids = [row["id"] for row in selected_exams]
        placeholders = ",".join("?" for _ in selected_ids)
        exam_clause = f"AND e.id IN ({placeholders})"
        exam_params.extend(selected_ids)
    results = connection.execute(
        f"""
        SELECT er.id AS result_id, e.id AS exam_id, e.exam_key, e.name AS exam_name, e.exam_date,
               e.total_max_score, er.effective_total, er.raw_total, er.scaled_total,
               er.total_source,
               se.track, se.student_type, se.class_id, c.class_name, o.name AS organization_name
        FROM exam_results er
        JOIN exams e ON e.id=er.exam_id
        JOIN student_exam_enrollments se ON se.id=er.enrollment_id
        JOIN classes c ON c.id=se.class_id
        JOIN organizations o ON o.id=se.organization_id
        WHERE er.student_id=? AND er.attendance_status='normal' {exam_clause}
        ORDER BY e.exam_date, e.id
        """,
        [student["id"], *exam_params],
    ).fetchall()
    history = []
    for result in results:
        scores = connection.execute(
            """
            SELECT ss.subject_code, s.name, s.category, ss.effective_score
            FROM subject_scores ss JOIN subjects s ON s.code=ss.subject_code
            JOIN exam_results er ON er.id=ss.exam_result_id
            WHERE er.exam_id=? AND er.student_id=?
            ORDER BY CASE s.category WHEN 'common' THEN 1 WHEN 'primary' THEN 2 ELSE 3 END, s.name
            """,
            (result["exam_id"], student["id"]),
        ).fetchall()
        line = connection.execute(
            """
            SELECT line_value FROM score_lines
            WHERE exam_id=? AND track=? AND line_type='特控' AND subject_code='__TOTAL__'
            """,
            (result["exam_id"], result["track"]),
        ).fetchone()
        item = dict(result)
        item["score_rate"] = result["effective_total"] / result["total_max_score"]
        item["control_line"] = line["line_value"] if line else None
        item["control_gap"] = result["effective_total"] - line["line_value"] if line else None
        item["class_rank"] = 1 + connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM exam_results other
            JOIN student_exam_enrollments ose ON ose.id=other.enrollment_id
            WHERE other.exam_id=? AND ose.class_id=? AND other.attendance_status='normal'
              AND other.effective_total>?
            """,
            (result["exam_id"], result["class_id"], result["effective_total"]),
        ).fetchone()["count"]
        grade = grade_statistics(connection, result["exam_key"], result["track"])
        item["grade_rank"] = grade["ranks"]["__TOTAL__"].get(result["result_id"])
        item["grade_reference_count"] = grade["reference_count"]
        subject_lines = _derived_subject_lines(connection, result["exam_key"], result["track"])
        subject_items = []
        for score in scores:
            subject = dict(score)
            rank_value = grade["ranks"].get(score["subject_code"], {}).get(result["result_id"])
            count = grade["counts"].get(score["subject_code"], 0)
            subject["grade_rank"] = rank_value
            subject["cloud_rank"] = rank_value
            subject["rank_percentile"] = _safe_rate(count - rank_value + 1, count) if rank_value is not None else None
            subject["lines"] = subject_lines.get(score["subject_code"], {})
            subject["line_gaps"] = {
                line_type: score["effective_score"] - line_value if line_value is not None else None
                for line_type, line_value in subject["lines"].items()
            }
            subject_items.append(subject)
        percentiles = [item_["rank_percentile"] for item_ in subject_items if item_["rank_percentile"] is not None]
        strongest = max(percentiles) if percentiles else None
        weakest = min(percentiles) if percentiles else None
        item["advantages"] = [item_["name"] for item_ in subject_items if strongest is not None and item_["rank_percentile"] == strongest]
        item["weaknesses"] = [item_["name"] for item_ in subject_items if weakest is not None and item_["rank_percentile"] == weakest]
        item["subjects"] = subject_items
        history.append(item)
    return {
        "student": dict(student),
        "history": history,
        "diagnosis_formula": "学科位次百分位＝（同方向同学科参考人数－学科位次＋1）÷同方向同学科参考人数",
    }
