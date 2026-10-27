from __future__ import annotations

from dataclasses import dataclass


CORE_RULE_VERSION = "2026.10-grade-v1"
EXPORT_TEMPLATE_VERSION = "2026.10-grade-v1"

TRACK_PHYSICS = "物理"
TRACK_HISTORY = "历史"
TRACKS = (TRACK_PHYSICS, TRACK_HISTORY)

LINE_UNDERGRADUATE = "本科"
LINE_CONTROL = "特控"
LINE_211 = "211"
LINE_985 = "985"
LINE_TYPES = (LINE_CONTROL, LINE_211, LINE_985)
TOTAL_LINE_TYPES = (LINE_UNDERGRADUATE, *LINE_TYPES)

CRITICAL_WINDOWS = (40, 60, 90)
DEFAULT_CRITICAL_WINDOW = 40

# 用户最终确认：总分分数段采用左闭右开；最高档不设右界。
LINE_BAND_BOUNDARY = "left-closed-right-open"
CRITICAL_BOUNDARY = "left-closed-right-open"
FIXED_BAND_BOUNDARY = "left-closed-right-open"

NORMAL_ATTENDANCE = "normal"
ABSENT_ATTENDANCE = "absent"


@dataclass(frozen=True)
class SubjectDefinition:
    code: str
    name: str
    category: str
    default_max_score: float


SUBJECTS = {
    "chinese": SubjectDefinition("chinese", "语文", "common", 150),
    "math": SubjectDefinition("math", "数学", "common", 150),
    "english": SubjectDefinition("english", "英语", "common", 150),
    "physics": SubjectDefinition("physics", "物理", "primary", 100),
    "history": SubjectDefinition("history", "历史", "primary", 100),
    "chemistry": SubjectDefinition("chemistry", "化学", "elective", 100),
    "biology": SubjectDefinition("biology", "生物", "elective", 100),
    "politics": SubjectDefinition("politics", "政治", "elective", 100),
    "geography": SubjectDefinition("geography", "地理", "elective", 100),
}

SUBJECT_NAME_TO_CODE = {
    definition.name: definition.code for definition in SUBJECTS.values()
}

SCORE_SHEETS = {
    "物理方向学生成绩": TRACK_PHYSICS,
    "历史方向学生成绩": TRACK_HISTORY,
}

SCORE_FIRST_SIX_HEADERS = ("年级", "考试名称", "考试时间", "学号", "班级", "姓名")
