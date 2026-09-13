# -*- coding: utf-8 -*-
"""
build_school_browser_data.py — 生成「院校数据浏览器」页的索引数据。

输入（唯一真相源，均为仓库内已有机读数据）：
  06-院校数据库/data/meta.json + data/schools/*.json   （177 校：报录比/复录比/最高最低分/复试线/拟招…）
  10-录取分数统计/data/schools_index.json + data/schools/*.json（96 校 CodeBrick 逐年分位统计）
  04-终极版择校/…20260826.xlsx 五个明细 sheet（2027改考动态/导师研究方向/N诺新增候选校/调剂院校/重点院校——
    这三类信息部分院校尚未回流 06 JSON，脚本统一合并入索引；库外院校自动建"信息补充"记录，信息零丢失）

输出：
  06-院校数据库/data/school_browser.json
    每校一条紧凑记录（表头展示字段 + 懒加载文件路径 + CodeBrick 匹配与逐年总分概览）。
    浏览器页 06-院校数据库/院校数据浏览器.html fetch 本索引渲染总表；
    点行进详情时再懒加载该校完整原始 JSON（索引不复制明细，避免双源漂移）。

校名匹配：全角括号规范化 + 去括号后缀容错（与 inject_codebrick_pages.py 同思路）。

用法：仓库根目录执行  python 09-生成脚本/build_school_browser_data.py
幂等：纯派生覆盖输出，不改动任何输入。
"""
import json
import os
import sys

DB_DIR = "06-院校数据库/data"
CB_DIR = os.path.join("10-录取分数统计", "data")
XLSX_PATH = os.path.join("04-终极版择校", "全国408_085410双非热度版_终极版_20260826.xlsx")
OUT = os.path.join(DB_DIR, "school_browser.json")

# xlsx 明细 sheet → 索引记录上的字段名（"全部入页"：页面不再要求读者开 xlsx）
XLSX_SHEETS = {
    "2027改考动态": "u27",
    "导师研究方向": "tut",
    "N诺新增候选校": "nnC",
    "调剂院校": "tj",
    "重点院校": "key",
}
TUT_HDR = "导师及研究方向（含Agent/大模型/具身智能关键词）"
ROW_KEYS = {
    "u27": [("专业/范围", "prog"), ("原科目", "from"), ("新科目", "to"),
            ("生效年份", "yr"), ("来源", "src"), ("备注", "note")],
    "nnC": [("省份", "prov"), ("院系", "college"), ("专业", "program"), ("初试", "subjects"),
            ("复试线", "line"), ("复试人数", "retest"), ("调剂人数", "adj"),
            ("复试总分均分", "avgTotal"), ("408均分", "avg408"), ("政治均分", "avgPol"),
            ("英语均分", "avgEng"), ("数学均分", "avgMath"), ("录取人数", "admit"),
            ("录取均分", "admitAvg"), ("录取率", "rate"), ("报录比(N诺=复试/录取)", "ratio"),
            ("备注", "note")],
    "tj": [("初试科目", "subj"), ("2026线", "line"), ("一志愿/调剂", "yz"), ("来源", "src")],
    "key": [("学院", "college"), ("初试科目", "subjects"), ("方向", "dir"), ("2026线", "line"),
            ("拟招", "plan"), ("AI方向", "ai"), ("备注", "note")],
}
# 06 JSON nnCandidates 长键 → 索引短键
NN_JSON_MAP = {"province": "prov", "retestCnt": "retest", "adjCnt": "adj",
               "admitCnt": "admit", "ratioNN": "ratio"}

NUM_KEYS = ["line2026", "plan", "retestCnt", "admitCnt",
            "ratioRetest", "ratioApply", "admitMax", "admitMin", "admitAvg"]


def norm(n):
    return (n or "").replace("(", "（").replace(")", "）").replace(" ", "")


def norm_loose(n):
    """去括号内容容错：中国石油大学（华东）→ 中国石油大学 + 华东标记"""
    base = norm(n)
    if "（" in base:
        i = base.index("（")
        return base[:i], base[i + 1:base.index("）")] if "）" in base else ""
    return base, None


def num(v):
    """'325'/'325.0'/325 → float；None/''/非数字 → None"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick_headline(kq_rows, unit_rows):
    """选数值最全的一行作为表头行；kaoqingDetail2026 优先于 units。"""
    best, best_score = None, -1
    for src, rows in (("kq", kq_rows), ("u", unit_rows)):
        for r in rows:
            vals = {
                "line2026": num(r.get("line2026")),
                "plan": num(r.get("plan") if r.get("plan") is not None else r.get("plan2026")),
                "retestCnt": num(r.get("retestCnt")),
                "admitCnt": num(r.get("admitCnt")),
                "ratioRetest": num(r.get("ratioRetest")),
                "ratioApply": num(r.get("ratioApply")),
                "admitMax": num(r.get("admitMax")),
                "admitMin": num(r.get("admitMin")),
                "admitAvg": num(r.get("admitAvg")),
                "college": r.get("college") or "",
                "subjects": r.get("subjects") or r.get("subjectClass") or "",
                "linesByYear": r.get("linesByYear") or None,
            }
            score = sum(v is not None for k, v in vals.items() if k in NUM_KEYS) * 2
            if src == "kq":
                score += 1
            if score > best_score:
                best, best_score = vals, score
    if best is None or best_score <= 0:
        return None
    for k in NUM_KEYS:
        if best.get(k) in (None, ""):
            best.pop(k, None)
    if not best.get("college"):
        best.pop("college", None)
    if not best.get("subjects"):
        best.pop("subjects", None)
    if not best.get("linesByYear"):
        best.pop("linesByYear", None)
    return best


def cb_years(school_obj):
    """逐年总分概览：跨项目按年聚合 最低/最高(总分)、拟录取数、复试数。"""
    years = {}
    for prog in school_obj.get("programs", []):
        for yr in (prog.get("stats") or {}).get("years", []):
            y = str(yr.get("year"))
            slot = years.setdefault(y, {"min": None, "max": None, "enr": 0, "ret": 0})
            tot = next((s for s in yr.get("subjects", []) if s.get("key") == "total"), None)
            if tot:
                if tot.get("min") is not None:
                    slot["min"] = tot["min"] if slot["min"] is None else min(slot["min"], tot["min"])
                if tot.get("max") is not None:
                    slot["max"] = tot["max"] if slot["max"] is None else max(slot["max"], tot["max"])
            slot["enr"] += yr.get("enrolledCount") or 0
            slot["ret"] += yr.get("retestCount") or 0
    return {k: v for k, v in sorted(years.items())} or None


def _row_item(field, row):
    """xlsx 行 / JSON 条目 → 索引短键 dict。tut 为字符串。"""
    if field == "tut":
        return (row.get(TUT_HDR) or row.get("tut_src") or "").strip() or None
    keys = ROW_KEYS[field]
    item = {}
    for zh, short in keys:
        v = row.get(zh)
        v = "" if v is None else str(v).strip()
        if v and v != "—":
            item[short] = v
    return item if item else None


def _identity(field, item):
    if field == "tut":
        return item
    if field == "u27":
        return (item.get("prog", ""), item.get("to", ""))
    if field == "nnC":
        return (item.get("college", ""), item.get("program", ""))
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def read_xlsx_sheets():
    if not os.path.exists(XLSX_PATH):
        print("!! 未找到 04 xlsx，明细 sheet 合并跳过")
        return {}
    import openpyxl
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True)
    sheets = {}
    for name, field in XLSX_SHEETS.items():
        body = []
        rows = list(wb[name].iter_rows(values_only=True))
        hdr = [str(h) for h in rows[0]]
        for r in rows[1:]:
            if not r or r[0] in (None, ""):
                continue
            body.append(dict(zip(hdr, r)))
        sheets[field] = body
    wb.close()
    return sheets


def merge_xlsx(records, sheets, extras):
    """把 04 xlsx 五个明细 sheet + 06 JSON 已有 updates2027/nnCandidates/tutors
    合并进对应记录；匹配不到的院校新建"信息补充"记录。幂等去重按字段身份键。"""
    by = {}
    for r in records:
        by.setdefault(norm(r["name"]), r)
        base, _ = norm_loose(norm(r["name"]))
        by.setdefault(base, r)  # 前缀容错（同名首个）
    created = 0
    merged_rows = 0
    for field, rows in sorted(sheets.items()):
        for row in rows:
            sname = norm(str(row.get("院校") or ""))
            rec = by.get(sname) or by.get(norm_loose(sname)[0])
            if rec is None:
                rec = {"name": str(row.get("院校")), "file": None, "cat": "信息补充",
                       "prov": row.get("省份") or row.get("大区") or None,
                       "region": None, "tier": row.get("层次") or None,
                       "nRows": 0, "hl": None, "cb": None, "subs": []}
                records.append(rec)
                by[sname] = by[norm_loose(sname)[0]] = rec
                created += 1
            item = _row_item(field, row)
            if item is None:
                continue
            lst = rec.setdefault(field, [])
            if all(_identity(field, x) != _identity(field, item) for x in lst):
                lst.append(item)
                merged_rows += 1
    # JSON 已有条目补齐（xlsx 缺该 (prog,to)/(college,program)/导师串时）
    for field in ("u27", "nnC", "tut"):
        for name, items in extras.get(field, {}).items():
            rec = by.get(norm(name)) or by.get(norm_loose(norm(name))[0])
            if rec is None:
                continue
            lst = rec.setdefault(field, [])
            for item in items:
                if all(_identity(field, x) != _identity(field, item) for x in lst):
                    lst.append(item)
                    merged_rows += 1
    return created, merged_rows


def main():
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    meta = json.load(open(os.path.join(DB_DIR, "meta.json"), encoding="utf-8"))
    assert meta.get("nSchools") == len(meta.get("schools", [])), "meta.json 计数与列表不一致"
    n_db = len(meta["schools"])

    # CodeBrick 索引 + 逐年聚合
    cb_idx = json.load(open(os.path.join(CB_DIR, "schools_index.json"), encoding="utf-8"))
    cb_by_norm, cb_collisions = {}, set()
    cb_years_by_id = {}
    for it in cb_idx:
        key = norm(it["name"])
        if key in cb_by_norm:
            cb_collisions.add(key)
        cb_by_norm[key] = it
        p = os.path.join(CB_DIR, "schools", "%s.json" % it["id"])
        if os.path.exists(p):
            cb_years_by_id[it["id"]] = cb_years(json.load(open(p, encoding="utf-8")))

    loose = {}
    for key, it in cb_by_norm.items():
        if "（" in key:
            base, tag = norm_loose(key)
            loose.setdefault((base, tag), it)

    def match_cb(name):
        key = norm(name)
        if key in cb_by_norm:
            return cb_by_norm[key]
        base, tag = norm_loose(name)
        return loose.get((base, tag))

    records, matched, matched_cb = [], 0, set()
    cov = {k: 0 for k in NUM_KEYS}
    extras = {"u27": {}, "nnC": {}, "tut": {}}  # 06 JSON 已有明细 → 合并期去重补齐
    for s in meta["schools"]:
        school = json.load(open(os.path.join(DB_DIR, "schools", s["file"]), encoding="utf-8"))
        units = school.get("units", [])
        kq = school.get("kaoqingDetail2026", [])
        subs = sorted({u.get("subjectClass") for u in units if u.get("subjectClass")}
                      | {k.get("subjects") for k in kq if k.get("subjects")})
        for u27 in (school.get("updates2027") or []):
            if isinstance(u27, dict):
                item = _row_item("u27", u27)
                if item:
                    extras["u27"].setdefault(s["name"], []).append(item)
        for nc in (school.get("nnCandidates") or []):
            if isinstance(nc, dict):
                item = {NN_JSON_MAP.get(k, k): v for k, v in nc.items()
                        if k != "school" and v not in (None, "", "—")}
                item = {k: ("" if v is None else str(v)) for k, v in item.items()}
                if any(v for v in item.values()):
                    extras["nnC"].setdefault(s["name"], []).append(item)
        for t in (school.get("tutors") or []):
            if isinstance(t, str) and t.strip():
                extras["tut"].setdefault(s["name"], []).append(t.strip())
        prov = next((u.get("province") for u in units if u.get("province")), None)
        region = next((u.get("region") for u in units if u.get("region")), None)
        tier = next((u.get("tier") for u in units if u.get("tier")), None)
        hl = pick_headline(kq, units)
        if hl:
            for k in NUM_KEYS:
                if k in hl:
                    cov[k] += 1
        cb = match_cb(s["name"])
        rec = {
            "name": s["name"],
            "file": "data/schools/" + s["file"],
            "cat": s.get("inCategory"),
            "prov": prov, "region": region, "tier": tier,
            "nRows": len(kq) + len(units),
            "hl": hl,
            "subs": subs,
        }
        if cb:
            matched += 1
            matched_cb.add(cb["id"])
            rec["cb"] = {"id": cb["id"], "name": cb["name"], "loc": cb.get("location"),
                         "rank": cb.get("csRank"), "p": cb.get("programCount"),
                         "n": cb.get("recordCount"), "yrs": cb_years_by_id.get(cb["id"])}
        else:
            rec["cb"] = None
        records.append(rec)

    # 仅存在于 CodeBrick 分数库的院校（多为 985/211，不在 06 择校库）也入表，保证"两套都要"
    only_cb = 0
    for it in cb_idx:
        if it["id"] in matched_cb:
            continue
        only_cb += 1
        tier = ("985" if it.get("is985") else "211" if it.get("is211")
                else "双一流" if it.get("isDoubleFirstClass") else "其他")
        records.append({
            "name": it["name"],
            "file": None,
            "cat": "CB-分数统计",
            "prov": it.get("location"), "region": None, "tier": tier,
            "nRows": 0,
            "hl": None,
            "subs": [],
            "cb": {"id": it["id"], "name": it["name"], "loc": it.get("location"),
                   "rank": it.get("csRank"), "p": it.get("programCount"),
                   "n": it.get("recordCount"), "yrs": cb_years_by_id.get(it["id"])},
        })

    # 04 xlsx 五个明细 sheet + JSON 已有条目 → 合并进记录（"全部入页"）
    created, merged = merge_xlsx(records, read_xlsx_sheets(), extras)
    stat2 = lambda f: sum(1 for r in records if r.get(f))
    n27, nnn, ntt = stat2("u27"), stat2("nnC"), stat2("tut")

    out = {
        "schema": "school-browser/v2",
        "built_by": "09-生成脚本/build_school_browser_data.py",
        "nSchools": len(records),
        "nCbMatched": matched,
        "coverage": dict(cov, u27=n27, nnC=nnn, tut=ntt),
        "note": "派生索引，仅供列表展示；明细以 data/schools/*.json 与 10-录取分数统计 原始 JSON 懒加载为准。报录比官方普遍不公布，空值属正常。u27/tut/nnC/tj/key 来自 04 xlsx 明细 sheet 合并。",
        "schools": records,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT)
    print("输入: 06 库 %d 校 + CB 独有 %d 校 + xlsx 补充新建 %d 校 = 索引 %d 条；两库匹配 %d/%d CB 校" %
          (n_db, only_cb, created, len(records), matched, len(cb_idx)))
    print("明细合并: 新并入条目 %d；u27 校=%d nnC 校=%d tut 校=%d" % (merged, n27, nnn, ntt))
    print("覆盖率(表头非空校数):", json.dumps(cov, ensure_ascii=False))
    print("输出 %s (%.1f KB)" % (OUT, size / 1024.0))
    if cb_collisions:
        print("!! CB 归一后同名冲突:", sorted(cb_collisions))
    assert len(records) >= n_db + len(cb_idx) - matched, "记录数 < 两库并集，异常"
    assert matched >= 30, "CB 匹配数异常偏低，检查校名归一"
    assert n27 >= 30 and ntt >= 14 and nnn >= 70, "明细 sheet 合并数量异常（xlsx 结构变了？）"
    assert size > 60 * 1024, "输出异常小"
    print("OK")


if __name__ == "__main__":
    main()
