"""院校分类试点：不覆盖旧库，不猜专业，不自动裁定来源冲突。

数据按项目、年份、主题归位；证据、旧标签及字段迁移清单单独导出。
所有输入叶节点都有一个保留原值的目标位置，测试据此检查是否丢信息。
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

BASE = Path(__file__).resolve().parents[1]
NUMBER = r"\d+(?:\.\d+)?"
CODE = re.compile(r"(?<!\d)(?:0[18]\d{4}|140500)(?!\d)")
TOPICS = ("examinations", "enrollment_plans", "retest_results",
          "admission_results", "subject_statistics", "recruitment_notes")

# 同名数值也按主题区分；不把复试均分称作录取均分。
METRICS = {
    "line2026": ("retest_results", "line"),
    "line": ("retest_results", "line"),
    "lineUltimate2026": ("retest_results", "overview_line"),
    "plan2026": ("enrollment_plans", "count"),
    "plan": ("enrollment_plans", "count"),
    "retestCnt": ("retest_results", "count"),
    "adjCnt": ("retest_results", "transfer_count_reported"),
    "avgTotal": ("retest_results", "mean_total"),
    "ratioRetest": ("retest_results", "legacy_retest_ratio"),
    "ratioApply": ("retest_results", "legacy_apply_ratio"),
    "ratioNN": ("retest_results", "legacy_nn_ratio"),
    "admitCnt": ("admission_results", "count"),
    "admitMax": ("admission_results", "max_total"),
    "admitMin": ("admission_results", "min_total"),
    "admitAvg": ("admission_results", "mean_total"),
    "nnRate": ("admission_results", "reported_rate"),
    "rate": ("admission_results", "reported_rate"),
    "nn408avg": ("subject_statistics", "s408_mean"),
    "avg408": ("subject_statistics", "s408_mean"),
    "avgPol": ("subject_statistics", "politics_mean"),
    "avgEng": ("subject_statistics", "english_mean"),
    "avgMath": ("subject_statistics", "mathematics_mean"),
}
CONTEXT = ("school", "college", "nnCollege", "program", "nnProg", "direction",
           "province", "region", "tier", "batch", "scope", "scope2", "note",
           "remark", "verify", "subjectStatus", "src", "srcLabel", "url",
           "nnUrl", "kaoqingUrl", "lineDelta")


def esc(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def leaf_items(value, path=""):
    """空容器和 null 也是必须保留的值，不能只统计非空字段。"""
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaf_items(child, path + "/" + esc(key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaf_items(child, path + "/" + str(index))
    else:
        yield path, value


def get_pointer(document, pointer):
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def number_value(value):
    val = float(value)
    return int(val) if val.is_integer() else val


def parse_quantity(raw):
    """只解析有明确语法的数；复杂叙述不能通过取首个数字变成事实。"""
    out = {"value": None, "raw": raw, "status": "unparsed",
           "approximate": False, "components": []}
    if raw is None or raw == "":
        out["status"] = "missing"
        return out
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        out.update(value=raw, status="exact")
        return out
    if not isinstance(raw, str):
        return out
    text = raw.strip().replace("（", "(").replace("）", ")")
    approximate = text.startswith(("约", "≈", "~"))
    if approximate:
        text = text[1:].strip()
    out["approximate"] = approximate
    simple = re.fullmatch("(" + NUMBER + r")(%?)", text)
    if simple:
        out.update(value=number_value(simple[1]), status="approximate" if approximate else "exact")
        if simple[2]:
            out["unit"] = "percent"
        return out

    # 允许「50+1专项」「约181(96+85调剂)」；标签与各项数字一起保留。
    outer = re.fullmatch("(" + NUMBER + r")\((.+)\)", text)
    expression = outer[2] if outer else text
    terms = expression.split("+")
    if len(terms) < 2:
        return out
    components = []
    for term in terms:
        match = re.fullmatch("(" + NUMBER + r")([\u4e00-\u9fff]*)", term.strip())
        if not match:
            return out
        components.append({"value": number_value(match[1]), "label": match[2] or None})
    total = sum(p["value"] for p in components)
    out["components"] = components
    if outer and number_value(outer[1]) != total:
        out["status"] = "inconsistent_components"
        return out
    out.update(value=number_value(outer[1]) if outer else total, status="explicit_sum")
    return out


def explicit_program(row):
    """优先结构化专业描述；备注含多个代码时不猜哪个才是本行专业。"""
    for field in ("program", "nnProg", "direction", "note"):
        codes = set(CODE.findall(str(row.get(field) or "")))
        if codes:
            return (next(iter(codes)), field) if len(codes) == 1 else (None, field)
    return None, None


def exam_components(raw):
    """仅识别明确表达的科目；「混合/待确认/无085410」不会变成考试组合。"""
    result = {"english": None, "mathematics": None, "professional_code": None}
    text = str(raw or "")
    if text in ("22408", "11408"):
        result.update(english="英语二" if text[0] == "2" else "英语一",
                      mathematics="数学二" if text[1] == "2" else "数学一",
                      professional_code="408")
        return result
    for variant, label in (("英二", "英语二"), ("英语二", "英语二"), ("英一", "英语一"), ("英语一", "英语一")):
        if variant in text:
            result["english"] = label
    for variant, label in (("数学二", "数学二"), ("数二", "数学二"), ("数学一", "数学一"), ("数一", "数学一")):
        if variant in text:
            result["mathematics"] = label
    # 「非408」是排除标签，不是一个正向科目声明；括号中的809仍是明确科目。
    professional_text = re.sub(r"^\s*非\s*408", "", text)
    codes = set(re.findall(r"(?<!\d)(?:408|8\d{2})(?!\d)", professional_text))
    if len(codes) == 1:
        result["professional_code"] = next(iter(codes))
    return result


class Converter:
    def __init__(self, source, identity):
        if identity.get("name") != source["name"]:
            raise ValueError("院校身份映射与源文件校名不一致")
        self.source = source
        code = identity.get("code")
        school_id = code or "local-" + hashlib.sha256(source["name"].encode()).hexdigest()[:12]
        self.doc = {
            "schema": "kaoyan-school/v2-pilot", "verification_status": "not_rechecked",
            "school": {"id": school_id, "code": code, "name": source["name"],
                       "code_status": "verified_in_legacy_mapping" if identity.get("code_verified") else "unverified_in_legacy_mapping",
                       "province": None, "region": None, "tier": None},
            "offerings": [], "changes": [], "research": {"tutor_notes": []}, "sources": [],
            "quality": {"conflicts": [], "school_notes": [], "unassigned_records": [], "review_notes": []},
            "records": {}, "legacy_annotations": {}, "coverage": [],
            "migration": {"legacy_schema": source.get("schema"), "legacy_generated": source.get("generated")},
        }
        self.routes = {}
        self.route("/name", "/school/name")
        self.route("/schema", "/migration/legacy_schema", "context")
        if "generated" in source:
            self.route("/generated", "/migration/legacy_generated", "context")

    def route(self, old, new, disposition="structured"):
        self.routes[old] = (new, disposition)

    def record(self, pointer, row, collection, method):
        rid = "r-" + hashlib.sha256(pointer.encode()).hexdigest()[:10]
        record = {"source_pointer": pointer, "legacy_collection": collection,
                  "match_method": method, "verification_status": "not_rechecked",
                  "batch": row.get("batch"), "context": {}}
        self.doc["records"][rid] = record
        for key in CONTEXT:
            if key in row:
                record["context"][key] = copy.deepcopy(row[key])
                self.route(pointer + "/" + esc(key), "/records/" + rid + "/context/" + esc(key), "context")
        return rid

    def annual(self, offering, year):
        for index, row in enumerate(offering["annual_data"]):
            if row["year"] == year:
                return row, index
        row = {"year": year, **{topic: [] for topic in TOPICS}}
        offering["annual_data"].append(row)
        return row, len(offering["annual_data"]) - 1

    def metric(self, offering_index, year, rid, topic, metric, raw, source_pointer, numeric=True):
        annual, ai = self.annual(self.doc["offerings"][offering_index], year)
        entries = annual[topic]
        for index, entry in enumerate(entries):
            existing = entry["values"].get(metric)
            old_raw = existing.get("raw") if numeric and isinstance(existing, dict) else existing
            if entry["record_id"] == rid and (metric not in entry["values"] or old_raw == raw):
                break
        else:
            index = len(entries)
            entries.append({"record_id": rid, "values": {}})
        entries[index]["values"][metric] = parse_quantity(raw) if numeric else copy.deepcopy(raw)
        target = f"/offerings/{offering_index}/annual_data/{ai}/{topic}/{index}/values/{esc(metric)}"
        self.route(source_pointer, target + "/raw" if numeric else target)

    def observations(self, oi, row, pointer, collection, method):
        rid = self.record(pointer, row, collection, method)
        for key, (topic, name) in METRICS.items():
            if key in row:
                self.metric(oi, 2026, rid, topic, name, row[key], pointer + "/" + esc(key))
        for year, raw in (row.get("linesByYear") or {}).items():
            if re.fullmatch(r"\d{4}", str(year)):
                self.metric(oi, int(year), rid, "retest_results", "line", raw, pointer + "/linesByYear/" + esc(year))
        for key in ("fill", "fill2026"):
            if key in row:
                self.metric(oi, 2026, rid, "recruitment_notes", key, row[key], pointer + "/" + key, numeric=False)

        annual, ai = self.annual(self.doc["offerings"][oi], 2026)
        reported_key = "subjectClass" if "subjectClass" in row else "subjects" if "subjects" in row else None
        explicit_key = "nnSubjects" if row.get("nnSubjects") else reported_key
        if explicit_key:
            index = len(annual["examinations"])
            item = {"record_id": rid, "raw": row[explicit_key],
                    "components": exam_components(row[explicit_key]),
                    "reported_class": row.get(reported_key), "verification_status": "not_rechecked"}
            annual["examinations"].append(item)
            target = f"/offerings/{oi}/annual_data/{ai}/examinations/{index}"
            self.route(pointer + "/" + explicit_key, target + "/raw")
            if reported_key:
                self.route(pointer + "/" + reported_key, target + "/reported_class")
        for index, claim in enumerate(row.get("subjectClaim2026") or []):
            pos = len(annual["examinations"])
            annual["examinations"].append({"record_id": rid, "raw": claim.get("claim"),
                "components": exam_components(claim.get("claim")), "legacy_claim": copy.deepcopy(claim),
                "verification_status": "not_rechecked"})
            self.route(pointer + "/subjectClaim2026/" + str(index),
                       f"/offerings/{oi}/annual_data/{ai}/examinations/{pos}/legacy_claim")

    def match(self, row):
        college = row.get("college") or row.get("nnCollege")
        code, code_field = explicit_program(row)
        if code is None and code_field is not None:
            return None, "unassigned"  # 明确出现多个代码，不能退回学院唯一匹配。
        def normalized(name):
            return re.sub(r"\s+", "", str(name or "").replace("（", "(").replace("）", ")"))
        candidates = [i for i, o in enumerate(self.doc["offerings"])
                      if college and normalized(o["college"]["name"]) == normalized(college)
                      and (code is None or o["program"]["code"] == code)]
        if len(candidates) == 1:
            method = "college_and_program" if code else "unique_college"
            if self.doc["offerings"][candidates[0]]["college"]["name"] != college:
                method += "_normalized"
            return candidates[0], method
        return None, "unassigned"

    def convert(self):
        units = self.source.get("units") or []
        for key in ("province", "region", "tier"):
            values = {u[key] for u in units if isinstance(u.get(key), str) and u[key]}
            if len(values) == 1:
                self.doc["school"][key] = next(iter(values))
        for ui, unit in enumerate(units):
            code, from_field = explicit_program(unit)
            semantic_key = [self.doc["school"]["id"], unit.get("college"), code, unit.get("direction"), None]
            oid = "off-" + hashlib.sha256(json.dumps(semantic_key, ensure_ascii=False).encode()).hexdigest()[:14]
            if any(o["id"] == oid for o in self.doc["offerings"]):
                raise ValueError("招生项目身份重复；需先补方向或学习方式，不能按数组行号伪造身份")
            years = sorted({2026} | {int(y) for y in (unit.get("linesByYear") or {}) if re.fullmatch(r"\d{4}", str(y))})
            self.doc["offerings"].append({
                "id": oid, "college": {"code": None, "name": unit.get("college")},
                "program": {"code": code, "name": None, "label_raw": unit.get("nnProg"),
                            "code_status": "extracted_not_rechecked" if code else "unknown",
                            "code_evidence_pointer": f"/units/{ui}/{from_field}" if from_field else None},
                "direction": unit.get("direction"), "study_mode": None,
                "annual_data": [{"year": y, **{topic: [] for topic in TOPICS}} for y in years],
            })
            self.observations(ui, unit, f"/units/{ui}", "units", "primary_unit")

        # 来源名称不再充当主分类：匹配到的考情/候选记录归入同一项目下的主题。
        for collection in ("kaoqingDetail2026", "nnCandidates", "crossRefs"):
            for index, row in enumerate(self.source.get(collection) or []):
                pointer = f"/{collection}/{index}"
                oi, method = self.match(row)
                if oi is None:
                    rid = self.record(pointer, row, collection, method)
                    self.doc["quality"]["unassigned_records"].append({"record_id": rid, "source_pointer": pointer,
                        "reason": "学院或专业不足以唯一归属；整条原记录保留在证据文件中"})
                    self.doc["records"][rid]["unassigned_payload"] = copy.deepcopy(row)
                    self.route(pointer, f"/records/{rid}/unassigned_payload", "unassigned")
                else:
                    self.observations(oi, row, pointer, collection, method)

        for index, original in enumerate(self.source.get("updates2027") or []):
            scope = str(original.get("专业/范围") or "")
            codes = set(CODE.findall(scope))
            matches = [o["id"] for o in self.doc["offerings"] if o["program"]["code"] in codes
                       and o["college"]["name"] and o["college"]["name"] in scope]
            year_raw = original.get("生效年份")
            year = int(str(year_raw)) if re.fullmatch(r"\d{4}", str(year_raw)) else None
            self.doc["changes"].append({"effective_year": year, "scope": scope,
                "offering_ids": matches, "old_subjects": original.get("原科目"),
                "new_subjects": original.get("新科目"), "verification_status": "not_rechecked",
                "original": copy.deepcopy(original)})
            self.route(f"/updates2027/{index}", f"/changes/{index}/original")
        for index, original in enumerate(self.source.get("tutors") or []):
            self.doc["research"]["tutor_notes"].append({"text": copy.deepcopy(original), "offering_ids": [],
                                                       "verification_status": "not_rechecked"})
            self.route(f"/tutors/{index}", f"/research/tutor_notes/{index}/text")
        for index, original in enumerate(self.source.get("sources") or []):
            self.doc["sources"].append({"id": f"src-{index + 1}", "kind": "reference", "citation": copy.deepcopy(original)})
            self.route(f"/sources/{index}", f"/sources/{len(self.doc['sources'])-1}/citation")
        for label, url in (self.source.get("wangdaoLinks") or {}).items():
            pos = len(self.doc["sources"])
            self.doc["sources"].append({"id": f"src-{pos + 1}", "kind": "exam_analysis",
                                        "citation": {"year_label": label, "url": url}})
            self.route("/wangdaoLinks/" + esc(label), f"/sources/{pos}/citation/url")
        for index, original in enumerate(self.source.get("conflicts") or []):
            self.doc["quality"]["conflicts"].append({"legacy_record": copy.deepcopy(original),
                                                     "verification_status": "not_rechecked"})
            self.route(f"/conflicts/{index}", f"/quality/conflicts/{index}/legacy_record", "context")
        if "note" in self.source:
            self.doc["quality"]["school_notes"].append({"text": self.source["note"], "status": "legacy_summary_not_rechecked"})
            self.route("/note", "/quality/school_notes/0/text", "context")

        # 全量覆盖检查放在转换末尾；未知字段自动隔离，不静默丢弃或成为新事实。
        prefixes = sorted(self.routes, key=len, reverse=True)
        for old_pointer, raw in leaf_items(self.source):
            route = next((p for p in prefixes if old_pointer == p or old_pointer.startswith(p + "/")), None)
            if route is not None:
                target, disposition = self.routes[route]
                target += old_pointer[len(route):]
            else:
                self.doc["legacy_annotations"][old_pointer] = copy.deepcopy(raw)
                target = "/legacy_annotations/" + esc(old_pointer)
                disposition = "archived"
            if get_pointer(self.doc, target) != raw:
                raise ValueError("字段原值未完整保留：" + old_pointer)
            self.doc["coverage"].append({"source_pointer": old_pointer, "target_pointer": target, "disposition": disposition})
        return self.doc


def convert_school(source, identity):
    return Converter(source, identity).convert()


def cell(value):
    return str(value if value is not None else "未知").replace("|", "\\|").replace("\n", " ")


def render_summary(documents):
    labels = {"examinations": "考试科目", "enrollment_plans": "招生计划", "retest_results": "复试",
              "admission_results": "录取", "subject_statistics": "单科统计", "recruitment_notes": "招生说明"}
    metric_names = {"line": "复试线", "overview_line": "旧总览线", "count": "人数",
        "min_total": "最低总分", "max_total": "最高总分", "mean_total": "平均总分",
        "reported_rate": "来源录取率", "s408_mean": "408均分", "politics_mean": "政治均分",
        "english_mean": "英语均分", "mathematics_mean": "数学均分", "fill": "招生渠道原文",
        "fill2026": "当年招生说明", "transfer_count_reported": "调剂人数原列"}
    count = sum(len(doc["offerings"]) for doc in documents)
    lines = ["# 院校分类对照", "", "以下是既有资料的归位结果，未重新核实招生事实。数字按来源和批次分别展示，不能跨行直接求和。", "",
             f"当前样例覆盖 {len(documents)} 所学校、{count} 个招生项目。缺失的专业代码保留未知，无法安全匹配的明细单独列出。", "",
             "阅读顺序：学校 → 学院/专业 → 年份 → 考试、计划、复试、录取。来源记录编号可到对应 evidence JSON 的 records 查询原文口径。", ""]
    lines += ["## 先看项目是否分清", "", "这张表只引用旧 units 主记录，不代表已从其他记录中裁定出最终值。", "",
              "| 学校 | 学院 | 专业代码 | 招生年 | 计划原文 | 复试线原文 |", "|---|---|---|---|---|---|"]
    for doc in documents:
        for offering in doc["offerings"]:
            annual = next(y for y in offering["annual_data"] if y["year"] == 2026)
            def primary_raw(topic, key):
                for entry in annual[topic]:
                    if doc["records"][entry["record_id"]]["legacy_collection"] == "units" and key in entry["values"]:
                        return entry["values"][key]["raw"]
                return None
            lines.append("| " + " | ".join(cell(x) for x in [doc["school"]["name"], offering["college"]["name"],
                offering["program"]["code"], 2026, primary_raw("enrollment_plans", "count"), primary_raw("retest_results", "line")]) + " |")
    lines.append("")
    for doc in documents:
        lines += ["## " + doc["school"]["name"], "", "招生单位代码：`" + cell(doc["school"]["code"]) + "`（沿用本地映射，未重新核实）。", ""]
        for offering in doc["offerings"]:
            lines += ["### " + cell(offering["college"]["name"]) + " · " + cell(offering["program"]["code"]), "",
                      "方向：" + cell(offering["direction"]) + "；学习方式：未知。", ""]
            for annual in offering["annual_data"]:
                if not any(entry.get("raw") is not None or any(not isinstance(v, dict) or v.get("raw") is not None for v in entry.get("values", {}).values())
                           for topic in TOPICS for entry in annual[topic]):
                    continue
                lines += ["#### " + str(annual["year"]) + " 年", "", "| 主题 | 记录/批次 | 内容（保留原文） | 口径 |", "|---|---|---|---|"]
                for topic in TOPICS:
                    for entry in annual[topic]:
                        rec = doc["records"][entry["record_id"]]
                        batch = rec.get("batch") or "未细分"
                        if topic == "examinations":
                            detail = cell(entry["raw"])
                        else:
                            parts = []
                            for key, val in entry["values"].items():
                                if isinstance(val, dict) and "raw" in val:
                                    if val["raw"] is None:
                                        continue
                                    text = cell(val["raw"])
                                    if val["components"] and val["value"] is not None:
                                        text += "（显式合计 " + str(val["value"]) + "，组成仍保留）"
                                else:
                                    text = cell(val)
                                parts.append(metric_names.get(key, key) + "=" + text)
                            detail = "；".join(parts) or "旧记录为空，未补猜测值"
                        scope = rec["context"].get("scope") or rec["context"].get("note") or "原文未单列口径"
                        lines.append("| " + labels[topic] + " | " + rec["source_pointer"] + " / " + cell(batch) + " | " + detail + " | " + cell(scope) + " |")
                lines.append("")
        lines += ["### 改考事件与待归属项", ""]
        for change in doc["changes"]:
            lines.append("- 生效年 **" + cell(change["effective_year"]) + "**：" + cell(change["scope"]) + "；" + cell(change["old_subjects"]) + " → " + cell(change["new_subjects"]) + "。保留为事件，不覆盖年度科目。")
        for row in doc["quality"]["unassigned_records"]:
            lines.append("- `" + row["source_pointer"] + "`：" + row["reason"])
        for note in doc["quality"]["review_notes"]:
            lines.append("- **需核口径** `" + note["source_pointer"] + "`：" + note["explanation"])
        lines += ["- 既有冲突 " + str(len(doc["quality"]["conflicts"])) + " 条全部保留；本次不作新的事实裁定。", ""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="备份本目录的既有输出后重建")
    args = parser.parse_args()
    existing = [BASE / name for name in ("schools", "evidence", "分类对照.md", "migration_report.json") if (BASE / name).exists()]
    if existing and not args.replace:
        parser.error("产物已存在；需要重建时加 --replace，会先备份。")
    manifest = json.loads((BASE / "source_manifest.json").read_text(encoding="utf-8"))
    identities = json.loads((BASE / "source_snapshots" / "identities.json").read_text(encoding="utf-8"))
    notes_path = BASE / "sample_notes.json"
    sample_notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}
    documents = []
    for item in manifest["files"]:
        source_path = BASE / item["snapshot"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("原始快照哈希不符，停止：" + item["snapshot"])
        source = json.loads(source_path.read_text(encoding="utf-8"))
        identity = next(v for v in identities.values() if v["name"] == source["name"])
        document = convert_school(source, identity)
        for note in sample_notes.get(source["name"], []):
            get_pointer(source, note["source_pointer"])  # 复核备注必须指向真实源记录。
            document["quality"]["review_notes"].append(copy.deepcopy(note))
        document["migration"].update(source_file=item["snapshot"], source_sha256=item["sha256"])
        documents.append(document)
    if existing:
        backup = BASE / ".backups" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup.mkdir(parents=True)
        for path in existing:
            shutil.copytree(path, backup / path.name) if path.is_dir() else shutil.copy2(path, backup / path.name)
    report = {"schema": "school-migration-report/v1", "fact_verification": "not_rechecked", "schools": []}
    for document in documents:
        name = document["school"]["id"] + "-" + document["school"]["name"]
        audit = {key: document[key] for key in ("records", "legacy_annotations", "coverage", "migration")}
        core = {key: value for key, value in document.items() if key not in audit}
        core["evidence_file"] = "../evidence/" + name + ".json"
        for folder, content in (("schools", core), ("evidence", audit)):
            target = BASE / folder / (name + ".json")
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dispositions = {kind: sum(c["disposition"] == kind for c in document["coverage"])
                        for kind in ("structured", "context", "archived", "unassigned")}
        report["schools"].append({"name": document["school"]["name"], "offerings": len(document["offerings"]),
            "input_leaves": len(list(leaf_items(json.loads((BASE / document["migration"]["source_file"]).read_text(encoding="utf-8"))))),
            "mapped_leaves": len(document["coverage"]), "dispositions": dispositions,
            "unassigned_records": len(document["quality"]["unassigned_records"])})
    (BASE / "分类对照.md").write_text(render_summary(documents), encoding="utf-8")
    (BASE / "migration_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
