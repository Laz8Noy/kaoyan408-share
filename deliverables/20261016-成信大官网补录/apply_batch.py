"""One-shot, source-checked import of four 2026 CUIT official records.

The input HTML stays in the local work directory; candidate names and IDs are
never exported. All public candidate rows are reduced to aggregate figures.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json
import shutil
import statistics


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCES = ROOT / ".dsh/work/source-extraction-20261015/sources"
SCHOOL = ROOT / "06-院校数据库/data/schools/001-成都信息工程大学.json"
DERIVED = [
    ROOT / "06-院校数据库/data/score_matrix.json",
    ROOT / "06-院校数据库/data/kaoyan408.db",
    ROOT / "06-院校数据库/data/meta.json",
    ROOT / "06-院校数据库/data/todo_patch_list.json",
    ROOT / "06-院校数据库/data/crosswalk.json",
    ROOT / "06-院校数据库/data/schools_unified.json",
    ROOT / "06-院校数据库/data/school_browser.json",
]


class TableParser(HTMLParser):
    """Collect HTML table cells without external dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def load_source(name: str) -> tuple[bytes, list[list[str]]]:
    raw = (SOURCES / name).read_bytes()
    parsed = TableParser()
    parsed.feed(raw.decode("utf-8-sig"))
    return raw, parsed.rows


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source(name: str, url: str, title: str, date: str, raw: bytes) -> dict:
    return {
        "url": url,
        "title": title,
        "publishedDate": date,
        "collectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tier": "T1",
        "retrievalMethod": "downloaded_html",
        "downloadSha256": sha256(raw).hexdigest(),
    }


def record(id_: str, college: str, batch: str, topic: str, metrics: dict,
           scope: str, unit: int, src: dict, location: str) -> dict:
    return {
        "id": id_, "year": 2026, "college": college,
        "programCode": "085410", "programName": "人工智能",
        "direction": None, "studyMode": "全日制", "topic": topic,
        "batch": batch, "metrics": metrics, "scope": scope,
        "unitIndex": unit, "source": src,
        "evidenceLocation": location,
        "verificationStatus": "checked_against_primary",
    }


def score_metrics(rows: list[list[str]], index: int, count_key: str) -> dict:
    scores = [int(r[index]) for r in rows]
    require(bool(scores), "No score rows found")
    return {
        count_key: len(scores),
        "initial_total_min": min(scores),
        "initial_total_max": max(scores),
        "initial_total_mean": round(statistics.mean(scores), 6),
    }


def main() -> None:
    require(not (OUT / "backup.json").exists(), "Batch already applied")
    original_bytes = SCHOOL.read_bytes()
    school = json.loads(original_bytes)
    require(school["name"] == "成都信息工程大学", "Wrong school")
    old_ids = {r["id"] for r in school.get("sourceRecords", [])}
    expected_ids = {
        "cuit-2026-ai-first-shortlist", "cuit-2026-ai-second-shortlist",
        "cuit-2026-ai-transfer-policy", "cuit-2026-cs-ai-third-results",
    }
    require(not (old_ids & expected_ids), "A source record is already present")

    raw_first, all_first = load_source("cuit-ai-first-shortlist.html")
    raw_second, all_second = load_source("cuit-ai-second-shortlist.html")
    raw_third, all_third = load_source("cuit-cs-third-results.html")
    raw_transfer, all_transfer = load_source("cuit-ai-transfer.html")
    first = [r for r in all_first if len(r) == 9 and r[0].startswith("085410 ")]
    second = [r for r in all_second if len(r) == 9 and r[0].startswith("085410 ")]
    third = [r for r in all_third if len(r) == 12 and r[0] == "人工智能"]
    transfer = [r for r in all_transfer if len(r) == 5 and r[0].startswith("085410 ")]
    require((len(first), len(second), len(third), len(transfer)) == (1, 22, 33, 1),
            "Unexpected table row counts")
    require(all(r[1] == "全日制" for r in first + second + third), "Mixed study modes")
    require(all(r[2] == "调剂" for r in third), "Third batch is not all transfer")
    require("201" in transfer[0][1] and "204" in transfer[0][1]
            and "301" in transfer[0][2] and "408" in transfer[0][3],
            "Transfer subject row changed")
    origin_codes = ["0835", "0839", "0812", "0775", "0810", "0811", "0809", "0854", "1405"]
    require(all(code in transfer[0][4] for code in origin_codes),
            "Transfer origin-program row changed")

    first_m = score_metrics(first, 8, "shortlisted_count")
    second_m = score_metrics(second, 8, "shortlisted_count")
    third_m = score_metrics(third, 5, "observed_retest_count")
    third_m["zero_interview_score_count"] = sum(float(r[7]) == 0 for r in third)
    require(first_m["initial_total_min"] == 271
            and second_m["initial_total_min"] == 265
            and second_m["initial_total_max"] == 342
            and third_m["initial_total_min"] == 310,
            "Score columns or source content changed")

    records = [
        record("cuit-2026-ai-first-shortlist", "人工智能学院", "第一批拟复试名单",
               "retest_results", first_m,
               "名单仅确认一名拟复试考生及其初试分数；未证明实际复试或拟录取。", 0,
               source("cuit-ai-first-shortlist.html", "https://qkl.cuit.edu.cn/info/1046/2765.htm",
                      "2026年人工智能学院复试工作安排（第一批）", "2026-03-25", raw_first),
               "正文末尾085410全日制名单表"),
        record("cuit-2026-ai-second-shortlist", "人工智能学院", "第二批拟复试名单",
               "retest_results", second_m,
               "第二批名单22人；网页未在名单行明示志愿类别，不推断录取人数。", 0,
               source("cuit-ai-second-shortlist.html", "https://qkl.cuit.edu.cn/info/1046/2788.htm",
                      "2026年人工智能学院复试工作安排（第二批）", "2026-04-08", raw_second),
               "正文末尾085410全日制名单表"),
        record("cuit-2026-cs-ai-third-results", "计算机学院", "第三批调剂复试成绩",
               "retest_results", third_m,
               "成绩表中人工智能33条均为全日制调剂；面试0分23条。成绩表不能替代拟录取名单。", 1,
               source("cuit-cs-third-results.html", "https://jsjxy.cuit.edu.cn/info/1062/3269.htm",
                      "2026年计算机学院复试（第三批）成绩公布", None, raw_third),
               "成绩表专业=人工智能、志愿类别=调剂的33行"),
        record("cuit-2026-ai-transfer-policy", "人工智能学院", "调剂申请条件",
               "transfer_policy",
               {"accepted_english_codes": ["201", "204"],
                "required_math_code": "301", "required_business_code": "408",
                "eligible_origin_program_codes": origin_codes},
               "调剂资格条件；不是本校一志愿初试科目组合或拟录取结果。", 0,
               source("cuit-ai-transfer.html", "https://qkl.cuit.edu.cn/info/1046/2793.htm",
                      "2026年人工智能学院调剂公告", "2026-04-11", raw_transfer),
               "调剂基本要求第3条表格，085410行"),
    ]

    # Backup before any canonical or generated file is changed.
    backup = ROOT / ".dsh/backups/20261016-cuit-official-next"
    require(not backup.exists(), "Backup already exists")
    manifest = []
    for path in [SCHOOL] + [p for p in DERIVED if p.exists()]:
        dest = backup / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        manifest.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                         "sha256": sha256(path.read_bytes()).hexdigest()})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "backup.json").write_text(json.dumps({"directory": backup.relative_to(ROOT).as_posix(), "files": manifest},
                                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    changes = []
    def change(path: str, before: object, after: object, reason: str) -> None:
        changes.append({"path": path, "before": before, "after": after, "reason": reason})

    school["sourceRecords"].extend(records)
    unit = school["units"][0]
    change("units[0].programCode", unit.get("programCode"), "085410", "官网名单及调剂公告直接标明")
    unit["programCode"] = "085410"
    change("units[0].studyMode", unit.get("studyMode"), "全日制", "官网名单及调剂公告直接标明")
    unit["studyMode"] = "全日制"
    old_scope = unit["scope"]
    unit["scope"] = "计划12、线264为旧汇总；官网第一批拟复试名单1人、第二批22人，未据名单确认录取人数。"
    change("units[0].scope", old_scope, unit["scope"], "旧说明称官网动态页无法解析，已取得两批表格")
    unit.setdefault("fieldSources", {})["programCode"] = [r["id"] for r in records if r["unitIndex"] == 0]
    unit["fieldSources"]["studyMode"] = [r["id"] for r in records if r["unitIndex"] == 0]
    # The old detail called a first-batch score of 271 an admission score.
    detail = next(x for x in school["kaoqingDetail2026"] if x.get("college") == "人工智能学院" and x.get("batch") == "一志愿")
    quarantined = {k: detail[k] for k in ("admitCnt", "admitMin", "admitMax") if detail.get(k) is not None}
    for key in quarantined:
        change(f"kaoqingDetail2026.ai_first.{key}", detail[key], None,
               "第一批官网只给拟复试名单，不能证明录取")
        detail[key] = None
    detail["scope"] = "官网第一批085410全日制拟复试名单1人，初试271；旧汇总的录1人和录取分271未由拟录取公示确认。"
    detail["url"] = "https://qkl.cuit.edu.cn/info/1046/2765.htm"
    school.setdefault("dataQuality", {}).setdefault("unverifiedLegacyClaims", {})["aiCollegeFirstBatchAdmission"] = {
        "values": quarantined, "reason": "拟复试名单不能核实拟录取"}

    SCHOOL.write_text(json.dumps(school, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "source_records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "after-school.json").write_bytes(SCHOOL.read_bytes())
    print(json.dumps({"records_added": len(records), "changes": len(changes),
                      "first_shortlisted": 1, "second_shortlisted": 22,
                      "third_retest_rows": 33, "third_zero_interview": third_m["zero_interview_score_count"],
                      "backup_files": len(manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
