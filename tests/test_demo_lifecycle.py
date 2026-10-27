"""Regression coverage for empty startup and user-controlled demo cleanup."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
import test_system
from app import create_app
from app.db import get_db
from app.services.demo import seed_demo_data
from app.services.importer import preview_workbook, commit_batch


class DemoLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = patch("app.data_directory", return_value=Path(self.temp.name))
        self.directory.start()
        self.case = test_system.SystemTestCase()
        self.case.setUp()
        self.app = self.case.app
        self.client = self.app.test_client()
        self.db = get_db()

    def tearDown(self):
        self.case.tearDown()
        self.directory.stop()
        self.temp.cleanup()

    def upload_base(self):
        book = Workbook()
        school = book.active
        school.title = "学校信息"
        school.append(["省份", "学校", "年级", "班级", "班级人数", "特控目标"])
        school.append(["虚拟省", "虚拟示例中学", "高2027届", "01班", 1, 1])
        students = book.create_sheet("学生信息")
        students.append(["学校", "年级", "班级", "学生姓名", "学号", "选科标签"])
        students.append(["虚拟示例中学", "高2027届", "01班", "演示学生001", "VIRTUAL0001", "物化生"])
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        stream.seek(0)
        return self.client.post("/api/base-information/upload", data={"file": (stream, "base.xlsx")})

    def test_new_user_and_restart_do_not_seed_students(self):
        for table in ("students", "exams", "exam_results", "base_students", "organizations"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        app = create_app({"TESTING": True, "DATABASE": self.app.config["DATABASE"],
                          "UPLOAD_FOLDER": self.app.config["UPLOAD_FOLDER"],
                          "EXPORT_FOLDER": self.app.config["EXPORT_FOLDER"]})
        with app.app_context():
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM students").fetchone()[0], 0)
        self.assertEqual(self.client.get("/api/demo-data").json, {"students": 0, "exams": 0})

    def test_school_conflict_explained_then_upload_succeeds_after_cleanup(self):
        seed_demo_data(self.db)
        response = self.upload_base()
        self.assertEqual(response.status_code, 400)
        self.assertIn("多个学校名称", response.json["error"])
        self.assertIn("清除演示数据", response.json["error"])
        self.assertEqual(response.json["issues"][0]["issue_code"], "single_school_required")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM base_students").fetchone()[0], 0)
        self.assertEqual(self.client.get("/api/demo-data").json, {"students": 120, "exams": 3})
        response = self.client.delete("/api/demo-data", json={"confirmed": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["students"], 120)
        self.assertEqual(self.client.get("/api/exams").json["items"], [])
        response = self.upload_base()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["students"], 1)
        self.assertEqual(self.client.delete("/api/demo-data", json={"confirmed": True}).json["students"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM base_students").fetchone()[0], 1)

    def test_cleanup_requires_explicit_confirmation(self):
        seed_demo_data(self.db)
        for body in ({}, {"confirmed": False}):
            self.assertEqual(self.client.delete("/api/demo-data", json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/demo-data").json["students"], 120)

    def test_cleanup_preserves_uploaded_results_batches_and_file(self):
        seed_demo_data(self.db)
        path = Path(self.case.tempdir.name) / "keep.xlsx"
        self.case._make_valid_workbook(path)
        before = path.read_bytes()
        preview = preview_workbook(self.db, path, path.name)
        result = commit_batch(self.db, preview["batch_key"], "reject")
        response = self.client.delete("/api/demo-data", json={"confirmed": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM exam_results").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT status FROM import_batches WHERE batch_key=?", (result["batch_key"],)).fetchone()[0], "committed")
        self.assertEqual(path.read_bytes(), before)

    def test_cleanup_does_not_require_excluded_generator_module(self):
        with patch.dict(sys.modules, {"app.services.demo": None}):
            self.assertEqual(self.client.delete("/api/demo-data", json={"confirmed": True}).status_code, 200)

    def test_demo_endpoints_reject_remote_requests(self):
        self.assertEqual(self.client.get("/api/demo-data", environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
        self.assertEqual(self.client.delete("/api/demo-data", json={"confirmed": True}, environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
