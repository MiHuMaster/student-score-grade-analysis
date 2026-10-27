from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from .config import (
    CORE_RULE_VERSION,
    CRITICAL_WINDOWS,
    DEFAULT_CRITICAL_WINDOW,
    EXPORT_TEMPLATE_VERSION,
    LINE_TYPES,
    SUBJECTS,
    TOTAL_LINE_TYPES,
)
from .db import get_db
from .services.analytics import (
    Scope,
    benchmark_metrics,
    class_metrics,
    filter_options,
    list_exams,
    overview,
    score_bands,
    student_detail,
    student_groups,
    student_group_matrix,
    student_list,
    subject_line_pairs,
    subject_metrics,
)
from .services.demo_cleanup import clear_demo_data
from .services.importer import (
    attach_batch_preparation,
    WorkbookPayload,
    _validate_single_school,
    clear_import_cache,
    commit_batch,
    delete_import_batch,
    get_batch_preview,
    list_batch_issues,
    list_batches,
    list_base_information,
    parse_base_information_workbook,
    prepare_import_workbook,
    preview_workbook,
    save_base_information,
    saved_base_reference_data,
)
from .services.standard_exports import export_class_zip


api = Blueprint("api", __name__)


def _scope() -> Scope:
    exam_key = request.args.get("exam_key", "").strip()
    if not exam_key:
        raise ValueError("缺少 exam_key")
    track = request.args.get("track") or None
    if track not in {None, "物理", "历史"}:
        raise ValueError("方向必须是物理或历史")
    organization_id = request.args.get("organization_id", type=int)
    class_id = request.args.get("class_id", type=int)
    return Scope(exam_key, track, organization_id, class_id)


def _critical_window() -> int:
    value = request.args.get("critical_window", DEFAULT_CRITICAL_WINDOW, type=int)
    if value not in CRITICAL_WINDOWS:
        raise ValueError("临界窗口必须是 40、60 或 90")
    return value


def _sync_legacy_control_target(connection: sqlite3.Connection, base_class_id: int, target: int | None) -> None:
    base_row = connection.execute(
        "SELECT school_name, grade_name, class_name FROM base_school_classes WHERE id=?",
        (base_class_id,),
    ).fetchone()
    if base_row is None:
        raise ValueError("基础班级不存在")
    if target is None:
        connection.execute(
            "DELETE FROM base_class_targets WHERE base_class_id=? AND target_name='特控'",
            (base_class_id,),
        )
    else:
        connection.execute(
            """INSERT INTO base_class_targets(base_class_id, target_name, target_order, target_count)
               VALUES (?, '特控', 0, ?)
               ON CONFLICT(base_class_id, target_name) DO UPDATE SET
                 target_count=excluded.target_count, updated_at=CURRENT_TIMESTAMP""",
            (base_class_id, target),
        )
    class_rows = connection.execute(
        """SELECT c.id, c.grade_id FROM classes c
           JOIN organizations o ON o.id=c.organization_id
           JOIN grades g ON g.id=c.grade_id
           WHERE o.name=? AND g.name=? AND c.class_name=? AND c.archived_at IS NULL""",
        tuple(base_row),
    ).fetchall()
    for class_row in class_rows:
        connection.execute("UPDATE classes SET control_target=? WHERE id=?", (target, class_row["id"]))
        if target is None:
            connection.execute(
                "DELETE FROM class_stage_targets WHERE class_id=? AND target_name='特控'",
                (class_row["id"],),
            )
            connection.execute(
                "DELETE FROM class_targets WHERE class_id=? AND line_type='特控'",
                (class_row["id"],),
            )
        else:
            connection.execute(
                """INSERT INTO class_stage_targets(class_id, target_name, target_order, target_count, source)
                   VALUES (?, '特控', 0, ?, 'manual')
                   ON CONFLICT(class_id, target_name) DO UPDATE SET
                     target_count=excluded.target_count, source='manual', updated_at=CURRENT_TIMESTAMP""",
                (class_row["id"], target),
            )
            connection.execute(
                """INSERT INTO class_targets(exam_id, class_id, line_type, target_count, source)
                   SELECT id, ?, '特控', ?, 'manual' FROM exams
                   WHERE grade_id=? AND archived_at IS NULL
                   ON CONFLICT(exam_id, class_id, line_type) DO UPDATE SET
                     target_count=excluded.target_count, source='manual'""",
                (class_row["id"], target, class_row["grade_id"]),
            )
        connection.execute(
            "UPDATE exams SET data_version=data_version+1 WHERE grade_id=?",
            (class_row["grade_id"],),
        )


def _subject_critical_window() -> int:
    value = request.args.get("subject_critical_window", 10, type=int)
    if value not in {10, 20}:
        raise ValueError("单科临界窗口必须是 10 或 20 分")
    return value


def _query_list(name: str, cast=str) -> list:
    values = []
    for raw in request.args.getlist(name):
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    try:
        return list(dict.fromkeys(cast(value) for value in values))
    except (TypeError, ValueError):
        raise ValueError(f"{name} 参数格式错误") from None


@api.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    return jsonify({"error": str(error)}), 400


@api.errorhandler(sqlite3.IntegrityError)
def handle_integrity_error(_error: sqlite3.IntegrityError):
    return jsonify({"error": "数据约束校验失败，请检查重复记录或关联字段"}), 409


@api.get("/")
def index():
    return current_app.send_static_file("index.html")


@api.get("/api/health")
def health():
    connection = get_db()
    version = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"]
    return jsonify({"status": "ok", "database_schema": version, "rule_version": CORE_RULE_VERSION})


@api.get("/api/metadata")
def metadata():
    return jsonify(
        {
            "rule_version": CORE_RULE_VERSION,
            "export_template_version": EXPORT_TEMPLATE_VERSION,
            "critical_windows": CRITICAL_WINDOWS,
            "definitions": {
                "effective_total": "总分赋分优先；未填写时使用六科有效成绩合计，选考科目必须有赋分",
                "reference_count": "正常参考且拥有有效总分的去重学生",
                "hit_rate": "总分和该科同时上线人数 ÷ 该科上线人数",
                "contribution_rate": "总分和该科同时上线人数 ÷ 总分上线人数",
                "standard_deviation": "总体标准差",
                "score_band_boundary": "总分分数段左闭右开；最高档不设右界",
                "subject_line": "整场同方向总分上线学生按均分比例推导，结果按0.5舍入",
            },
        }
    )


@api.get("/api/exams")
def exams():
    return jsonify({"items": list_exams(get_db())})


@api.get("/api/filters")
def filters():
    return jsonify(filter_options(get_db(), request.args.get("exam_key")))


@api.get("/api/export/options")
def export_options():
    connection = get_db()
    selected_keys = _query_list("exam_keys")
    if not selected_keys and request.args.get("exam_key"):
        selected_keys = [request.args["exam_key"]]
    if not selected_keys:
        return jsonify({"organizations": [], "classes": []})
    placeholders = ",".join("?" for _ in selected_keys)
    selected = connection.execute(
        f"SELECT exam_key FROM exams WHERE exam_key IN ({placeholders}) AND archived_at IS NULL",
        selected_keys,
    ).fetchall()
    if len(selected) != len(selected_keys):
        raise ValueError("所选考试不存在或已归档。")
    organizations = connection.execute(
        f"""
        SELECT DISTINCT o.id, o.name
        FROM organizations o
        JOIN student_exam_enrollments se ON se.organization_id=o.id
        JOIN exams e ON e.id=se.exam_id
        WHERE o.archived_at IS NULL
          AND e.exam_key IN ({placeholders})
        ORDER BY o.name
        """,
        selected_keys,
    ).fetchall()
    classes = connection.execute(
        f"""
        SELECT DISTINCT c.id, c.class_name, c.track, c.organization_id,
               o.name AS organization_name
        FROM classes c
        JOIN organizations o ON o.id=c.organization_id
        JOIN student_exam_enrollments se ON se.class_id=c.id
        JOIN exams e ON e.id=se.exam_id
        WHERE c.archived_at IS NULL AND e.exam_key IN ({placeholders})
        ORDER BY o.name, c.track, c.class_name, c.id
        """,
        selected_keys,
    ).fetchall()
    return jsonify({
        "organizations": [dict(row) for row in organizations],
        "classes": [dict(row) for row in classes],
    })


@api.get("/api/analytics/overview")
def analytics_overview():
    return jsonify(overview(
        get_db(), _scope(), _critical_window(), _query_list("exam_keys") or None,
        request.args.get("target_name") or None,
    ))


@api.get("/api/analytics/score-bands")
def analytics_score_bands():
    step = request.args.get("step", 50, type=int)
    if step not in {30, 50}:
        raise ValueError("固定值分段步长只能是30或50")
    return jsonify(score_bands(get_db(), _scope(), step=step, exam_keys=_query_list("exam_keys") or None))


@api.get("/api/analytics/subjects")
def analytics_subjects():
    return jsonify(subject_metrics(get_db(), _scope(), exam_keys=_query_list("exam_keys") or None))


@api.get("/api/analytics/classes")
def analytics_classes():
    return jsonify(class_metrics(
        get_db(), _scope(), exam_keys=_query_list("exam_keys") or None,
        target_name=request.args.get("target_name") or None,
    ))


@api.get("/api/analytics/student-groups")
def analytics_student_groups():
    return jsonify(student_groups(get_db(), _scope(), _critical_window(), _query_list("exam_keys") or None))


@api.get("/api/analytics/student-matrix")
def analytics_student_matrix():
    return jsonify(student_group_matrix(
        get_db(), _scope(), request.args.get("exam_limit", 5, type=int), _query_list("exam_keys") or None,
    ))


@api.get("/api/analytics/benchmark")
def analytics_benchmark():
    exam_key = request.args.get("exam_key", "").strip()
    if not exam_key:
        raise ValueError("缺少 exam_key")
    return jsonify(benchmark_metrics(get_db(), exam_key))


@api.get("/api/students")
def students():
    keyword = (request.args.get("q") or "").strip()
    default_limit = 50 if keyword else 10
    return jsonify({"items": student_list(
        get_db(), _scope(), request.args.get("limit", default_limit, type=int), keyword or None,
    )})


@api.get("/api/students/<student_no>")
def one_student(student_no: str):
    result = student_detail(
        get_db(), student_no, request.args.get("exam_key") or None, _query_list("exam_keys") or None,
    )
    if result is None:
        return jsonify({"error": "学生不存在"}), 404
    return jsonify(result)


@api.get("/api/import/batches")
def import_batches():
    connection = get_db()
    items = list_batches(connection)
    count = connection.execute(
        "SELECT COUNT(*) AS count FROM import_batches WHERE status LIKE 'committed%'"
    ).fetchone()["count"]
    return jsonify({"items": items, "count": count})


@api.get("/api/import/<batch_key>")
def import_batch_preview(batch_key: str):
    return jsonify(get_batch_preview(get_db(), batch_key))


@api.get("/api/import/<batch_key>/issues")
def import_batch_issues(batch_key: str):
    return jsonify(
        list_batch_issues(
            get_db(),
            batch_key,
            request.args.get("severity", "error"),
            request.args.get("page", 1, type=int),
            request.args.get("page_size", 50, type=int),
        )
    )


@api.post("/api/import/preview")
def import_preview():
    if "file" not in request.files:
        raise ValueError("请选择 Excel 文件")
    uploaded = request.files["file"]
    original_name = uploaded.filename or "成绩导入.xlsx"
    if Path(original_name).suffix.lower() != ".xlsx":
        raise ValueError("首版仅支持 .xlsx 文件")
    safe_stem = secure_filename(Path(original_name).stem) or "scores"
    safe_name = f"{safe_stem}.xlsx"
    target = Path(current_app.config["UPLOAD_FOLDER"]) / f"{uuid.uuid4().hex}_{safe_name}"
    uploaded.save(target)
    return jsonify(preview_workbook(get_db(), target, original_name))


@api.get("/api/base-information")
def base_information_list():
    return jsonify(list_base_information(get_db(), request.args.get("page", 1, type=int), request.args.get("page_size", 12, type=int)))


@api.post("/api/base-information/upload")
def base_information_upload():
    path, _name = _uploaded_xlsx("file", "基础信息表")
    try:
        payload = parse_base_information_workbook(path)
        try:
            result = save_base_information(get_db(), payload)
        except ValueError:
            errors = [issue for issue in payload.issues if issue.severity == "error"]
            if not errors:
                raise
            message = "基础信息未保存：" + errors[0].message
            if errors[0].issue_code == "single_school_required":
                message += "。请核对学校名称；如果当前是系统演示数据，请先在数据管理中清除演示数据，再重新上传。"
            return jsonify({"error": message, "issues": [issue.__dict__ for issue in payload.issues]}), 400
        result["issues"] = [issue.__dict__ for issue in payload.issues]
        return jsonify(result)
    finally:
        path.unlink(missing_ok=True)


@api.put("/api/base-information/classes/<int:class_id>")
def base_information_class_update(class_id: int):
    data = request.get_json(force=True)
    try:
        planned_size = int(data["planned_size"]) if data.get("planned_size") not in (None, "") else None
        control_target = int(data["control_target"]) if data.get("control_target") not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("班级人数和特控目标必须是整数") from None
    connection = get_db()
    updated = connection.execute(
        "UPDATE base_school_classes SET province=?, planned_size=?, control_target=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (str(data.get("province", "")).strip() or None, planned_size, control_target, class_id),
    )
    if not updated.rowcount:
        raise ValueError("基础班级不存在")
    _sync_legacy_control_target(connection, class_id, control_target)
    connection.commit()
    return jsonify({"status": "saved", "id": class_id})


def _check_school_name(school_name: str) -> None:
    payload = WorkbookPayload(schools=[{"school": school_name}])
    _validate_single_school(payload, get_db())
    if payload.issues:
        raise ValueError(payload.issues[0].message)


@api.post("/api/base-information/classes")
def base_information_class_create():
    data = request.get_json(force=True)
    school_name = str(data.get("school_name", "")).strip()
    _check_school_name(school_name)
    grade_name = str(data.get("grade_name", "")).strip()
    class_name = str(data.get("class_name", "")).strip()
    if not all((school_name, grade_name, class_name)):
        raise ValueError("学校、年级和班级不能为空")
    try:
        planned_size = int(data["planned_size"]) if data.get("planned_size") not in (None, "") else None
        control_target = int(data["control_target"]) if data.get("control_target") not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("班级人数和特控目标必须是整数") from None
    connection = get_db()
    connection.execute(
        """INSERT INTO base_school_classes(province, school_name, grade_name, class_name, planned_size, control_target)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(school_name, grade_name, class_name) DO UPDATE SET
             province=excluded.province, planned_size=excluded.planned_size, control_target=excluded.control_target,
             updated_at=CURRENT_TIMESTAMP""",
        (str(data.get("province", "")).strip() or None, school_name, grade_name, class_name, planned_size, control_target),
    )
    base_class_id = connection.execute(
        "SELECT id FROM base_school_classes WHERE school_name=? AND grade_name=? AND class_name=?",
        (school_name, grade_name, class_name),
    ).fetchone()["id"]
    _sync_legacy_control_target(connection, base_class_id, control_target)
    connection.commit()
    return jsonify({"status": "saved"}), 201


@api.delete("/api/base-information/classes/<int:class_id>")
def base_information_class_delete(class_id: int):
    connection = get_db()
    item = connection.execute("SELECT school_name, grade_name, class_name FROM base_school_classes WHERE id=?", (class_id,)).fetchone()
    if item is None:
        raise ValueError("基础班级不存在")
    connection.execute("DELETE FROM base_students WHERE school_name=? AND grade_name=? AND class_name=?", tuple(item))
    connection.execute("DELETE FROM base_school_classes WHERE id=?", (class_id,))
    connection.commit()
    return jsonify({"status": "deleted", "id": class_id})


@api.get("/api/base-information/students")
def base_information_students():
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(max(1, request.args.get("page_size", 12, type=int)), 50)
    connection = get_db()
    total = connection.execute("SELECT COUNT(*) AS count FROM base_students").fetchone()["count"]
    rows = connection.execute(
        "SELECT * FROM base_students ORDER BY school_name, grade_name, class_name, student_no LIMIT ? OFFSET ?",
        (page_size, (page - 1) * page_size),
    ).fetchall()
    return jsonify({"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total})


@api.post("/api/base-information/students")
def base_information_student_save():
    data = request.get_json(force=True)
    values = tuple(str(data.get(key, "")).strip() for key in ("school_name", "grade_name", "class_name", "student_name", "student_no"))
    if not all(values):
        raise ValueError("学生的学校、年级、班级、姓名和学号不能为空")
    _check_school_name(values[0])
    get_db().execute(
        """INSERT INTO base_students(school_name, grade_name, class_name, student_name, student_no, subject_tag)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(school_name, grade_name, class_name, student_no) DO UPDATE SET
             student_name=excluded.student_name, subject_tag=excluded.subject_tag, updated_at=CURRENT_TIMESTAMP""",
        (*values, str(data.get("subject_tag", "")).strip() or None),
    )
    get_db().commit()
    return jsonify({"status": "saved"}), 201


@api.delete("/api/base-information/students/<int:student_id>")
def base_information_student_delete(student_id: int):
    result = get_db().execute("DELETE FROM base_students WHERE id=?", (student_id,))
    if not result.rowcount:
        raise ValueError("基础学生不存在")
    get_db().commit()
    return jsonify({"status": "deleted", "id": student_id})


def _uploaded_xlsx(field_name: str, label: str):
    uploaded = request.files.get(field_name)
    if uploaded is None or not uploaded.filename:
        raise ValueError(f"请选择{label}")
    original_name = Path(uploaded.filename).name
    if Path(original_name).suffix.lower() != ".xlsx":
        raise ValueError(f"{label}仅支持 .xlsx 文件")
    safe_stem = secure_filename(Path(original_name).stem) or field_name
    safe_name = f"{safe_stem}.xlsx"
    target = Path(current_app.config["UPLOAD_FOLDER"]) / f"{uuid.uuid4().hex}_{safe_name}"
    uploaded.save(target)
    return target, original_name


@api.post("/api/import/prepare")
def import_prepare():
    saved_paths: list[Path] = []
    batch_key: str | None = None
    try:
        reference_upload = request.files.get("reference_file")
        reference_data = None
        if reference_upload is not None and reference_upload.filename:
            reference_path, reference_name = _uploaded_xlsx("reference_file", "学校学生基础信息对照表")
            saved_paths.append(reference_path)
        else:
            reference_path = None
            reference_data = saved_base_reference_data(get_db())
            reference_name = "已保存的基础信息"
        score_path, score_name = _uploaded_xlsx("score_file", "学生总体赋分成绩表")
        saved_paths.append(score_path)
        output_name = f"{Path(score_name).stem}_已匹配.xlsx"
        output_path = Path(current_app.config["UPLOAD_FOLDER"]) / f"{uuid.uuid4().hex}_prepared.xlsx"
        saved_paths.append(output_path)
        preparation = prepare_import_workbook(
            reference_path,
            score_path,
            output_path,
            request.form.get("grade", ""),
            request.form.get("exam_name", ""),
            request.form.get("exam_month", ""),
            reference_data=reference_data,
        )
        preview = preview_workbook(get_db(), output_path, output_name)
        batch_key = preview["batch_key"]
        preview = attach_batch_preparation(
            get_db(),
            preview["batch_key"],
            {
                **preparation,
                "reference_filename": reference_name,
                "score_filename": score_name,
                "output_filename": output_name,
            },
            [*( [str(reference_path)] if reference_path else []), str(score_path)],
        )
        return jsonify(preview)
    except Exception:
        if batch_key:
            get_db().execute("DELETE FROM import_batches WHERE batch_key=?", (batch_key,))
            get_db().commit()
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise


@api.get("/api/import/<batch_key>/workbook")
def import_prepared_workbook(batch_key: str):
    batch = get_db().execute(
        "SELECT original_filename, source_path FROM import_batches WHERE batch_key=?",
        (batch_key,),
    ).fetchone()
    if batch is None:
        raise ValueError("导入批次不存在")
    path = Path(batch["source_path"])
    if not path.exists():
        raise ValueError("该批次的输出工作簿已被清理")
    return send_file(path, as_attachment=True, download_name=batch["original_filename"])


@api.post("/api/import/<batch_key>/commit")
def import_commit(batch_key: str):
    data = request.get_json(silent=True) or {}
    return jsonify(
        commit_batch(
            get_db(),
            batch_key,
            data.get("mode", "reject"),
            allow_partial=data.get("allow_partial") is True,
            warnings_confirmed=data.get("warnings_confirmed") is True,
        )
    )


def _delete_upload_files(paths: list[str]) -> int:
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    deleted = 0
    for raw_path in paths:
        path = Path(raw_path).resolve()
        if path == upload_root or upload_root not in path.parents:
            continue
        if path.is_file():
            path.unlink()
            deleted += 1
    return deleted


@api.delete("/api/import/<batch_key>")
def import_delete(batch_key: str):
    result = delete_import_batch(get_db(), batch_key)
    result["deleted_files"] = _delete_upload_files(result.pop("file_paths"))
    return jsonify(result)


@api.get("/api/demo-data")
def demo_data_status():
    row = get_db().execute(
        """SELECT COUNT(DISTINCT student_id) AS students,
                  COUNT(DISTINCT exam_id) AS exams
           FROM student_exam_enrollments WHERE source='demo'"""
    ).fetchone()
    return jsonify(dict(row))


@api.delete("/api/demo-data")
def demo_data_clear():
    if (request.get_json(silent=True) or {}).get("confirmed") is not True:
        raise ValueError("请先确认只清除系统演示数据")
    return jsonify(clear_demo_data(get_db()))


@api.delete("/api/import/cache")
def import_clear_cache():
    result = clear_import_cache(get_db())
    result["deleted_files"] = _delete_upload_files(result.pop("file_paths"))
    return jsonify(result)


@api.put("/api/settings/score-lines")
def update_score_lines():
    data = request.get_json(force=True)
    exam_key = str(data.get("exam_key", "")).strip()
    track = data.get("track")
    if track not in {"物理", "历史"}:
        raise ValueError("请选择物理或历史方向")
    connection = get_db()
    exam = connection.execute("SELECT id FROM exams WHERE exam_key=?", (exam_key,)).fetchone()
    if exam is None:
        raise ValueError("考试不存在")

    submitted_values = {
        line_type: data.get(line_type)
        for line_type in TOTAL_LINE_TYPES
        if data.get(line_type) is not None and str(data.get(line_type)).strip() != ""
    }
    try:
        numeric = {key: float(value) for key, value in submitted_values.items()}
    except (TypeError, ValueError):
        raise ValueError("分数线必须是数字") from None
    existing_total_lines = {
        row["line_type"]: float(row["line_value"])
        for row in connection.execute(
            """
            SELECT line_type, line_value FROM score_lines
            WHERE exam_id=? AND track=? AND subject_code='__TOTAL__'
            """,
            (exam["id"], track),
        )
    }
    merged_total_lines = {**existing_total_lines, **numeric}
    ordered_total_values = [
        merged_total_lines[line_type]
        for line_type in TOTAL_LINE_TYPES
        if line_type in merged_total_lines
    ]
    if ordered_total_values != sorted(ordered_total_values):
        raise ValueError("分数线必须满足 本科 ≤ 特控 ≤ 211 ≤ 985")
    subject_lines = data.get("subject_lines") or {}
    if not isinstance(subject_lines, dict):
        raise ValueError("单科划线格式不正确")
    normalized_subject_lines = {}
    for subject_code, subject_values in subject_lines.items():
        if subject_code not in SUBJECTS or not isinstance(subject_values, dict):
            raise ValueError("存在无法识别的学科划线")
        submitted_subject_values = {
            line_type: subject_values.get(line_type)
            for line_type in LINE_TYPES
            if subject_values.get(line_type) is not None
            and str(subject_values.get(line_type)).strip() != ""
        }
        try:
            subject_numeric = {
                line_type: float(value)
                for line_type, value in submitted_subject_values.items()
            }
        except (TypeError, ValueError):
            raise ValueError("单科划线必须是数字") from None
        if not subject_numeric:
            continue
        if any(value < 0 or value > SUBJECTS[subject_code].default_max_score for value in subject_numeric.values()):
            raise ValueError(f"{SUBJECTS[subject_code].name}划线超出该科满分范围")
        normalized_subject_lines[subject_code] = subject_numeric
    for authority_code, shared_code in subject_line_pairs(track):
        authority_values = normalized_subject_lines.get(authority_code, {})
        shared_values = normalized_subject_lines.get(shared_code, {})
        conflicts = {
            line_type
            for line_type in authority_values.keys() & shared_values.keys()
            if authority_values[line_type] != shared_values[line_type]
        }
        if conflicts:
            raise ValueError(
                f"配对科目划线冲突：{track}方向"
                f"{SUBJECTS[authority_code].name}与{SUBJECTS[shared_code].name}必须共用同一条线"
            )
        paired_values = {**authority_values, **shared_values}
        if paired_values:
            normalized_subject_lines[authority_code] = dict(paired_values)
            normalized_subject_lines[shared_code] = dict(paired_values)

    existing_subject_lines: dict[str, dict[str, float]] = {}
    if normalized_subject_lines:
        subject_codes = list(normalized_subject_lines)
        placeholders = ",".join("?" for _ in subject_codes)
        for row in connection.execute(
            f"""
            SELECT subject_code, line_type, line_value FROM score_lines
            WHERE exam_id=? AND track=? AND subject_code IN ({placeholders})
            """,
            [exam["id"], track, *subject_codes],
        ):
            existing_subject_lines.setdefault(row["subject_code"], {})[row["line_type"]] = float(row["line_value"])
    for subject_code, line_values in normalized_subject_lines.items():
        merged_subject_lines = {**existing_subject_lines.get(subject_code, {}), **line_values}
        ordered_subject_values = [
            merged_subject_lines[line_type]
            for line_type in LINE_TYPES
            if line_type in merged_subject_lines
        ]
        if ordered_subject_values != sorted(ordered_subject_values):
            raise ValueError(f"{SUBJECTS[subject_code].name}划线必须满足 特控 ≤ 211 ≤ 985")

    if not numeric and not normalized_subject_lines:
        return jsonify({
            "status": "unchanged", "exam_key": exam_key, "track": track,
            "lines": {}, "subject_lines": {},
        })
    for line_type, value in numeric.items():
        connection.execute(
            """
            INSERT INTO score_lines(
              exam_id, track, line_type, subject_code, line_value, source, rule_version
            ) VALUES (?, ?, ?, '__TOTAL__', ?, 'manual', ?)
            ON CONFLICT(exam_id, track, line_type, subject_code)
            DO UPDATE SET line_value=excluded.line_value, source='manual', rule_version=excluded.rule_version
            """,
            (exam["id"], track, line_type, value, CORE_RULE_VERSION),
        )
    for subject_code, line_values in normalized_subject_lines.items():
        for line_type, value in line_values.items():
            connection.execute(
                """
                INSERT INTO score_lines(
                  exam_id, track, line_type, subject_code, line_value, source, rule_version
                ) VALUES (?, ?, ?, ?, ?, 'manual', ?)
                ON CONFLICT(exam_id, track, line_type, subject_code)
                DO UPDATE SET line_value=excluded.line_value, source='manual', rule_version=excluded.rule_version
                """,
                (exam["id"], track, line_type, subject_code, value, CORE_RULE_VERSION),
            )
    connection.execute("UPDATE exams SET data_version=data_version+1 WHERE id=?", (exam["id"],))
    connection.execute(
        "INSERT INTO operation_logs(action, target_type, target_id, summary) VALUES ('score_lines_update', 'exam', ?, ?)",
        (exam_key, f"更新{track}方向总分及{len(normalized_subject_lines)}科特控/211/985分数线"),
    )
    connection.commit()
    return jsonify({
        "status": "saved", "exam_key": exam_key, "track": track,
        "lines": numeric, "subject_lines": normalized_subject_lines,
    })






@api.get("/api/export/classes")
def export_classes():
    scope = _scope()
    path = export_class_zip(
        get_db(), scope.exam_key, current_app.config["EXPORT_FOLDER"],
        exam_keys=_query_list("exam_keys") or None,
        organization_ids=_query_list("organization_ids", int) or None,
        class_ids=_query_list("class_ids", int) or None,
    )
    return send_file(path, as_attachment=True, download_name=path.name)




