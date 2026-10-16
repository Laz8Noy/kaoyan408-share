"""检查真实院校样例，重点防止串项目、串年份和丢失原文。"""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("school_migrate", BASE / "tools" / "migrate.py")
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


def leaves(value, path=""):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaves(child, path + "/" + key.replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaves(child, path + "/" + str(index))
    else:
        yield path, value


def pointer(document, path):
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


class QuantityTests(unittest.TestCase):
    def test_special_plan_keeps_both_parts(self):
        q = migrate.parse_quantity("50+1专项")
        self.assertEqual(q.get("value"), 51)
        self.assertEqual(q.get("components"), [{"value": 50, "label": None}, {"value": 1, "label": "专项"}])
        self.assertEqual(q.get("raw"), "50+1专项")

    def test_approximate_total_keeps_transfer_component(self):
        q = migrate.parse_quantity("约181(96+85调剂)")
        self.assertEqual(q.get("value"), 181)
        self.assertTrue(q.get("approximate"))
        self.assertEqual(q.get("components"), [{"value": 96, "label": None}, {"value": 85, "label": "调剂"}])

    def test_ambiguous_sentence_does_not_become_first_number(self):
        self.assertIsNone(migrate.parse_quantity("约90人，另有专项名额待定").get("value"))

    def test_inconsistent_total_is_not_silently_accepted(self):
        self.assertIsNone(migrate.parse_quantity("181(96+86调剂)").get("value"))


class SchoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hubu = json.loads((BASE / "source_snapshots" / "001-湖北大学.json").read_text(encoding="utf-8"))
        cls.cuit = json.loads((BASE / "source_snapshots" / "001-成都信息工程大学.json").read_text(encoding="utf-8"))
        cls.identities = json.loads((BASE / "source_snapshots" / "identities.json").read_text(encoding="utf-8"))

    def convert(self, source):
        identity = next(v for v in self.identities.values() if v["name"] == source["name"])
        return migrate.convert_school(copy.deepcopy(source), identity)

    def test_hubu_keeps_distinct_college_program_and_score_lines(self):
        doc = self.convert(self.hubu)
        self.assertEqual(len(doc.get("offerings", [])), 2)
        rows = {o["program"]["code"]: o for o in doc["offerings"]}
        for code, college, line in [("085410", "人工智能学院", 275), ("085404", "计算机学院", 264)]:
            self.assertEqual(rows[code]["college"]["name"], college)
            annual = next(y for y in rows[code]["annual_data"] if y["year"] == 2026)
            self.assertEqual(annual["retest_results"][0]["values"]["line"]["value"], line)

    def test_change_year_comes_from_record_not_updates2027_name(self):
        doc = self.convert(self.hubu)
        self.assertEqual([c["effective_year"] for c in doc.get("changes", [])], [2026])
        self.assertEqual(doc["changes"][0]["offering_ids"], [next(o["id"] for o in doc["offerings"] if o["program"]["code"] == "085404")])

    def test_cuit_keeps_conflicting_exam_claims_and_reference_unassigned(self):
        doc = self.convert(self.cuit)
        self.assertEqual(len(doc.get("offerings", [])), 2)
        row = next(o for o in doc["offerings"] if o["college"]["name"] == "计算机学院")
        annual = next(y for y in row["annual_data"] if y["year"] == 2026)
        claims = [x["raw"] for x in annual["examinations"]]
        self.assertIn("英二+数学一+408", claims)
        self.assertIn("英二+数学二+408", claims)
        self.assertTrue(any(x["source_pointer"] == "/crossRefs/0" for x in doc["quality"]["unassigned_records"]))
        self.assertEqual(doc["changes"][0]["effective_year"], 2027)
        self.assertEqual(len(doc["changes"][0]["offering_ids"]), 2)

    def test_batch_counts_remain_separate_and_addition_stays_explicit(self):
        doc = self.convert(self.cuit)
        row = next(o for o in doc.get("offerings", []) if o["college"]["name"] == "计算机学院") if doc.get("offerings") else {}
        annual = next((y for y in row.get("annual_data", []) if y["year"] == 2026), {})
        entries = {doc["records"][x["record_id"]]["batch"]: x for x in annual.get("admission_results", []) if doc["records"][x["record_id"]].get("batch")}
        self.assertEqual(set(entries), {"一志愿", "调剂"})
        self.assertEqual(entries["一志愿"]["values"]["count"]["value"], 1)
        self.assertEqual(entries["调剂"]["values"]["count"]["value"], 25)
        self.assertEqual(entries["调剂"]["values"]["count"]["raw"], "18+7")

    def test_project_id_does_not_depend_on_array_order(self):
        doc1 = self.convert(self.hubu)
        reordered = copy.deepcopy(self.hubu)
        reordered["units"].reverse()
        doc2 = self.convert(reordered)
        self.assertEqual(len(doc1.get("offerings", [])), 2)
        self.assertEqual({o["college"]["name"]: o["id"] for o in doc1["offerings"]}, {o["college"]["name"]: o["id"] for o in doc2["offerings"]})

    def test_every_old_leaf_has_a_target_with_unchanged_raw_value(self):
        for source in [self.hubu, self.cuit]:
            with self.subTest(school=source["name"]):
                doc = self.convert(source)
                expected = dict(leaves(source))
                coverage = doc.get("coverage", [])
                self.assertEqual({r["source_pointer"] for r in coverage}, set(expected))
                self.assertEqual(len(coverage), len(expected))
                for entry in coverage:
                    self.assertEqual(pointer(doc, entry["target_pointer"]), expected[entry["source_pointer"]])

    def test_unknown_fields_are_kept_without_becoming_new_facts(self):
        source = copy.deepcopy(self.hubu)
        source["units"][0]["futureField"] = {"data": ["不得丢失", None]}
        doc = self.convert(source)
        self.assertTrue(any(r["source_pointer"] == "/units/0/futureField/data/0" and r["disposition"] == "archived" for r in doc.get("coverage", [])))


class ExpandedSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = json.loads((BASE / "source_manifest.json").read_text(encoding="utf-8"))
        cls.identities = json.loads((BASE / "source_snapshots/identities.json").read_text(encoding="utf-8"))
        cls.sources = {}
        for item in manifest["files"]:
            source = json.loads((BASE / item["snapshot"]).read_text(encoding="utf-8"))
            cls.sources[source["name"]] = source

    def convert(self, name, source=None):
        identity = next(v for v in self.identities.values() if v["name"] == name)
        return migrate.convert_school(copy.deepcopy(source or self.sources[name]), identity)

    def test_shenzhen_three_projects_keep_separate_lines_without_guessed_codes(self):
        doc = self.convert("深圳大学")
        self.assertEqual(len(doc["offerings"]), 3)
        for row, want in zip(doc["offerings"], [335, 312, 286]):
            self.assertIsNone(row["program"]["code"])
            annual = next(y for y in row["annual_data"] if y["year"] == 2026)
            self.assertEqual(annual["retest_results"][0]["values"]["line"]["value"], want)

    def test_chongyou_missing_official_code_does_not_become_invented_code(self):
        doc = self.convert("重庆邮电大学")
        self.assertIsNone(doc["school"]["code"])
        self.assertTrue(doc["school"]["id"].startswith("local-"))
        annual = next(y for y in doc["offerings"][0]["annual_data"] if y["year"] == 2026)
        self.assertIsNone(annual["enrollment_plans"][0]["values"]["count"]["value"])

    def test_qinghai_two_directions_do_not_share_ambiguous_detail_records(self):
        doc = self.convert("青海大学")
        self.assertEqual(len({o["id"] for o in doc["offerings"]}), 2)
        self.assertEqual({r["source_pointer"] for r in doc["quality"]["unassigned_records"]}, {"/kaoqingDetail2026/0", "/kaoqingDetail2026/1"})

    def test_nuc_equivalent_brackets_do_not_leave_detail_unassigned(self):
        doc = self.convert("中北大学")
        self.assertFalse(any(r["source_pointer"] == "/kaoqingDetail2026/0" for r in doc["quality"]["unassigned_records"]))
        self.assertTrue(any(r["source_pointer"] == "/kaoqingDetail2026/0" and r["match_method"] == "unique_college_normalized" for r in doc["records"].values()))

    def test_non408_annotation_keeps_explicit_809_subject(self):
        self.assertEqual(migrate.exam_components("非408(809信号与系统)")["professional_code"], "809")
        self.assertIsNone(migrate.exam_components("非408")["professional_code"])

    def test_multiple_explicit_program_codes_cannot_fall_back_to_unique_college(self):
        source = copy.deepcopy(self.sources["湖北大学"])
        source["kaoqingDetail2026"][0]["program"] = "085410/085404"
        doc = self.convert("湖北大学", source)
        self.assertTrue(any(r["source_pointer"] == "/kaoqingDetail2026/0" for r in doc["quality"]["unassigned_records"]))

    def test_summary_counts_follow_eight_school_manifest(self):
        summary = migrate.render_summary([self.convert(name) for name in self.sources])
        self.assertTrue("8 所学校、15 个招生项目" in summary, "总览仍在使用旧的两校固定规模")

    def test_all_eight_sources_keep_every_raw_value_and_type(self):
        self.assertEqual(len(self.sources), 8)
        for name, source in self.sources.items():
            with self.subTest(school=name):
                doc = self.convert(name)
                expected = dict(leaves(source))
                self.assertEqual({r["source_pointer"] for r in doc["coverage"]}, set(expected))
                self.assertEqual(len(doc["coverage"]), len(expected))
                for entry in doc["coverage"]:
                    raw = expected[entry["source_pointer"]]
                    actual = pointer(doc, entry["target_pointer"])
                    self.assertEqual(actual, raw)
                    self.assertIs(type(actual), type(raw))


if __name__ == "__main__":
    unittest.main()
