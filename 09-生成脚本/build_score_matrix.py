#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_score_matrix.py — 把仓库内三套院校数据合并成「院校数据总库」单一数据源

输入：
  06-院校数据库/data/meta.json + data/schools/*.json      177 校择校库（复试线/拟招/复试数/录取数/最高最低均分/复录比）
  10-录取分数统计/data/schools_index.json + data/schools/*.json   96 校 CodeBrick 逐年逐项目分位数
  ../../ext/408-offerings.json                              研招网 408 官方目录快照（外部源，带出处）

输出：
  06-院校数据库/data/score_matrix.json    合并后的主数据（学校 → units[] + programs[]）
  06-院校数据库/data/yz408_catalog.json   研招网 408 官方目录（独立文件，标注外部出处）

用法：
  python 09-生成脚本/build_score_matrix.py
"""
import json
import os
import re
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（本地工作副本）
DB6 = os.path.join(ROOT, "06-院校数据库")
DB10 = os.path.join(ROOT, "10-录取分数统计")
EXT = os.path.join(ROOT, "ext", "408-offerings.json")
EXT_DAI = os.path.join(ROOT, "ext", "awarer", "universities.json")

NUM = ("line2026", "plan2026", "retestCnt", "admitCnt",
       "admitMax", "admitMin", "admitAvg", "ratioRetest", "ratioApply",
       "heatNet", "heatComp", "nn408avg", "lineUltimate2026", "wdCount")


def num(v):
    """尽量转数字；'约90(86+4专项)' / '103+6专项' 这类取首个整数并标记近似。"""
    if v is None or v == "":
        return None, False
    if isinstance(v, (int, float)):
        return v, False
    s = str(v).strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None, False
    val = float(m.group(0))
    approx = bool(re.search(r"[约~≈]", s)) or bool(re.search(r"\+", s)) or bool(re.search(r"\(|（", s))
    return (int(val) if val == int(val) else val), approx


def norm(n):
    """校名归一：全角括号、空格、'大学/学院'后缀差异"""
    s = (n or "").replace("(", "（").replace(")", "）").replace(" ", "")
    s = s.replace("（", "").replace("）", "")
    return s


def norm_loose(n):
    """去括号内容：中国石油大学（华东）→ (中国石油大学, 华东)"""
    s = (n or "").replace("(", "（").replace(")", "）").replace(" ", "")
    if "（" in s and "）" in s:
        i = s.index("（")
        return s[:i], s[i + 1:s.index("）")]
    return s, None


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_unit(u):
    """把 06 库的一个 unit 压平成页面可用的行"""
    out = {"college": u.get("college") or "", "direction": u.get("direction") or ""}
    if u.get("subjectClass"):
        out["subj"] = u["subjectClass"]
    for k in NUM:
        v, approx = num(u.get(k))
        if v is not None:
            out[k] = v
            if approx:
                out.setdefault("_approx", []).append(k)
    # 原文（拟招/复试数/录取数常带 "86+4专项" 这类说明）
    for k, dst in (("plan2026", "planRaw"), ("retestCnt", "retestRaw"),
                   ("admitCnt", "admitRaw"), ("admitMax", "maxRaw"),
                   ("admitMin", "minRaw"), ("admitAvg", "avgRaw")):
        if u.get(k):
            out[dst] = str(u[k])
    if u.get("linesByYear"):
        out["lines"] = {str(k): v for k, v in u["linesByYear"].items()}
    if u.get("fill"):
        out["fill"] = u["fill"]
    if u.get("aiTag"):
        out["ai"] = u["aiTag"]
    if u.get("nnRate"):
        out["nnRate"] = u["nnRate"]
    if u.get("scope"):
        out["scope"] = u["scope"]
    if u.get("note"):
        out["note"] = u["note"]
    if u.get("srcLabel"):
        out["src"] = u["srcLabel"]
    if u.get("kaoqingUrl"):
        out["kqUrl"] = u["kaoqingUrl"]
    if u.get("nnUrl"):
        out["nnUrl"] = u["nnUrl"]
    return out


def build_program(p):
    """把 CodeBrick 一个项目压平成页面可用的行；subjects 用定长数组省体积"""
    ORDER = [("s408", 0), ("math", 1), ("english", 2), ("politics", 3), ("total", 4)]
    years = []
    for y in (p.get("stats") or {}).get("years", []):
        row = {"y": y.get("year")}
        if y.get("exam408Type"):
            row["t"] = y["exam408Type"]
        for src, dst in (("enrolledCount", "enr"), ("retestCount", "ret"),
                         ("retestEliminationRate", "elim"), ("nationalTotalLine", "natT"),
                         ("national408Line", "nat4"), ("retestLineTotal", "rline"),
                         ("admitMinTotal", "amin")):
            if y.get(src) is not None:
                row[dst] = y[src]
        subj = {}
        for s in y.get("subjects") or []:
            if not s.get("quantilesAvailable"):
                continue
            # [min, p25, median, p75, max, mean]
            subj[s["key"]] = [s.get("min"), s.get("p25"), s.get("median"),
                              s.get("p75"), s.get("max"), s.get("mean")]
        if subj:
            row["q"] = subj
        if y.get("warnings"):
            row["w"] = y["warnings"]
        if y.get("sourceUrl"):
            row["u"] = y["sourceUrl"]
        years.append(row)
    years.sort(key=lambda r: r.get("y") or 0)
    return {
        "name": p.get("programName") or "",
        "type": p.get("admitType") or "",
        "n": p.get("recordCount"),
        "years": years,
    }


def build_dai408():
    """把 Dai408（awarer.top）的院校×专业×年份录取统计压平成页面可用的行。

    字段（原始）：
      school_id, name, province, college, level, direction, direction_code,
      degree_type(学硕/专硕), exam_subject(11408/22408/…), tuition_fee, subjects(复试形式),
      year, plan_exam(统考拟招), actual_admission(实际录取), retest_count(复试人数),
      admitted_count(录取人数), avg_score(平均分), min_score(最低分), max_score(最高分),
      median_total(总分中位), median_major(408中位), median_math(数学中位),
      score_line_politics/english/math/major(单科线)
    """
    if not os.path.exists(EXT_DAI):
        return None
    raw = load_json(EXT_DAI)
    LEVEL = {1: "985", 2: "211", 3: "双一流", 4: "普通"}
    items = []
    n_zero_fixed = 0
    for u in raw.get("items", []):
        for d in u.get("directions") or []:
            row = {
                "s": d.get("name") or u.get("name"),
                "p": d.get("province") or u.get("province"),
                "lv": LEVEL.get(d.get("level"), "普通"),
                "c": d.get("college") or "",
                "d": d.get("direction") or "",
                "dc": d.get("direction_code") or "",
                "dt": d.get("degree_type") or "",
                "y": d.get("year"),
                "sid": d.get("school_id"),
            }
            if d.get("exam_subject"):
                row["ex"] = d["exam_subject"]
            if d.get("tuition_fee"):
                row["fee"] = d["tuition_fee"]
            if d.get("subjects"):
                row["rt"] = "+".join(d["subjects"])
            # 源数据存在「复试 0 人 / 录取 0 人 / 分数全 0」的占位行，
            # 这类 0 不是真实分数，若不剔除会把「最低分 0」排到榜首污染排序与统计。
            placeholder = ((d.get("retest_count") or 0) == 0
                           and (d.get("admitted_count") or 0) == 0
                           and (d.get("max_score") or 0) == 0)
            if placeholder:
                n_zero_fixed += 1
            else:
                for src, dst in (("plan_exam", "plan"), ("actual_admission", "act"),
                                 ("retest_count", "retest"), ("admitted_count", "adm")):
                    if d.get(src) is not None:
                        row[dst] = d[src]
                for src, dst in (("min_score", "smin"), ("max_score", "smax"),
                                 ("avg_score", "savg"), ("median_total", "smed"),
                                 ("median_major", "m408"), ("median_math", "mmath")):
                    if d.get(src) is not None:
                        row[dst] = d[src]
            if d.get("plan_exam") is not None and placeholder:
                row["plan"] = d["plan_exam"]
            # 单科线：政治/英语/数学/专业课
            sl = [d.get("score_line_politics"), d.get("score_line_english"),
                  d.get("score_line_math"), d.get("score_line_major")]
            if any(x is not None for x in sl):
                row["line"] = sl
            items.append(row)
    items.sort(key=lambda r: (r["s"], r["c"], r["d"], r.get("y") or 0))
    return {
        "schema": "dai408-scores/v1",
        "source": "Dai408 · 408 计算机考研院校录取数据库（公益参考版）",
        "sourceUrl": "https://awarer.top/",
        "fetchedAt": datetime.date.today().isoformat(),
        "note": ("数据由 awarer.top 基于各校公开复试/拟录取名单聚合，本站仅作汇总转载并保留出处。"
                 "口径：最低/最高/平均分为录取者初试总分；408中位/数学中位为单科中位数；"
                 "单科线为该专业当年复试的单科分数线（政治/英语/数学/专业课）。"
                 "level: 985/211/双一流/普通；exam_subject 为初试科目组合。"
                 "已剔除源数据中 %d 条「复试0人/录取0人/分数全0」的占位行分数与人数（保留专业目录信息）。" % n_zero_fixed),
        "nUniversities": raw.get("total"),
        "nRecords": len(items),
        "nPlaceholderFixed": n_zero_fixed,
        "items": items,
    }


def main():
    # ---------- 1. 择校库（06） ----------
    meta = load_json(os.path.join(DB6, "data", "meta.json"))
    schools = {}
    for it in meta["schools"]:
        j = load_json(os.path.join(DB6, "data", "schools", it["file"]))
        units = [build_unit(u) for u in (j.get("units") or [])]
        kq = []
        for r in j.get("kaoqingDetail2026") or []:
            row = {}
            for k_src, k_dst in (("college", "college"), ("program", "program"),
                                 ("batch", "batch"), ("subjects", "subj"), ("tier", "tier")):
                if r.get(k_src):
                    row[k_dst] = r[k_src]
            for k in ("line2026", "plan", "retestCnt", "admitCnt", "ratioRetest",
                      "ratioApply", "admitMax", "admitMin", "admitAvg"):
                v, _ = num(r.get(k))
                if v is not None:
                    row[k] = v
            if r.get("verify"):
                row["verify"] = r["verify"]
            if r.get("scope"):
                row["scope"] = r["scope"]
            if r.get("url"):
                row["url"] = r["url"]
            kq.append(row)
        s = {
            "name": it["name"],
            "cat": it.get("inCategory") or "",
            "lib": it["file"],
            "units": units,
        }
        if kq:
            s["kq"] = kq
        if j.get("updates2027"):
            s["u27"] = [{"prog": x.get("prog") or x.get("program") or "",
                         "from": x.get("from") or "", "to": x.get("to") or "",
                         "yr": x.get("yr") or "", "note": x.get("note") or "",
                         "src": x.get("src") or ""} for x in j["updates2027"]]
        if j.get("tutors"):
            s["tut"] = j["tutors"]
        if j.get("conflicts"):
            s["conf"] = j["conflicts"]
        if j.get("wangdaoLinks"):
            s["wd"] = j["wangdaoLinks"]
        schools[norm(it["name"])] = s

    # ---------- 2. CodeBrick（10） ----------
    cb_index = load_json(os.path.join(DB10, "data", "schools_index.json"))
    cb_dir = os.path.join(DB10, "data", "schools")
    cb_by_norm = {}
    cb_unmatched = []
    for it in cb_index:
        sid = it["id"]
        fp = os.path.join(cb_dir, "%s.json" % sid)
        if not os.path.exists(fp):
            continue
        d = load_json(fp)
        key = norm(it["name"])
        cb_by_norm[key] = {"idx": it, "data": d}
        if key not in schools:
            loose, _ = norm_loose(it["name"])
            schools.setdefault(loose, None)
            cb_unmatched.append((key, it["name"], loose))

    # ---------- 3. 合并 ----------
    matched = 0
    for key, cb in cb_by_norm.items():
        target = schools.get(key)
        if target is None:
            loose, _ = norm_loose(cb["idx"]["name"])
            target = schools.get(loose)
        if target is None:
            # CodeBrick 独有：新建一条
            it = cb["idx"]
            target = {"name": it["name"], "cat": "CB-分数统计", "units": []}
            schools[key] = target
        else:
            matched += 1
        target["cbId"] = cb["idx"]["id"]
        target["csRank"] = cb["idx"].get("csRank")
        target["prov"] = cb["idx"].get("location") or target.get("prov")
        target["tags"] = {"is985": cb["idx"].get("is985"), "is211": cb["idx"].get("is211"),
                          "isDFC": cb["idx"].get("isDoubleFirstClass")}
        target["cbYears"] = [cb["idx"].get("minYear"), cb["idx"].get("maxYear")]
        target["cbN"] = cb["idx"].get("recordCount")
        target["programs"] = [build_program(p) for p in cb["data"].get("programs", [])]

    # 清理占位
    schools = {k: v for k, v in schools.items() if v}

    # ---------- 4. 研招网 408 官方目录 ----------
    yz = None
    if os.path.exists(EXT):
        raw = load_json(EXT)
        items = []
        for it in raw.get("items", []):
            sub = [s.get("code") for s in (it.get("subjects") or [])]
            row = {
                "s": it.get("schoolName"), "code": it.get("schoolCode"),
                "p": it.get("region"), "c": it.get("collegeName"),
                "mc": it.get("majorCode"), "mn": it.get("majorName"),
                "dt": it.get("degreeType"), "sm": it.get("studyMode"),
            }
            if it.get("directionName"):
                d = it["directionName"]
                row["dir"] = d if len(d) <= 60 else d[:60] + "…"
            if it.get("plannedEnrollment"):
                row["plan"] = it["plannedEnrollment"]
            if it.get("enrollment2026") is not None:
                row["e26"] = it["enrollment2026"]
            if it.get("enrollment2027") is not None:
                row["e27"] = it["enrollment2027"]
            if sub:
                row["sub"] = sub
            items.append(row)
        yz = {
            "schema": "yz408-catalog/v1",
            "source": raw.get("source"),
            "sourceUrl": raw.get("sourceUrl"),
            "syncedAt": raw.get("syncedAt"),
            "coverage": raw.get("coverage"),
            "count": raw.get("count"),
            "schoolCount": raw.get("schoolCount"),
            "items": items,
        }

    # ---------- 5. 汇总输出 ----------
    out_schools = []
    for k, s in schools.items():
        row = {"name": s["name"]}
        for a, b in (("cat", "cat"), ("prov", "prov"), ("lib", "lib"),
                     ("cbId", "cbId"), ("csRank", "csRank"), ("cbN", "cbN")):
            if s.get(a) is not None:
                row[b] = s[a]
        if s.get("tags"):
            row["tags"] = s["tags"]
        if s.get("cbYears"):
            row["cbYears"] = s["cbYears"]
        for a in ("units", "kq", "u27", "tut", "conf", "wd", "programs"):
            if s.get(a):
                row[a] = s[a]
        out_schools.append(row)
    out_schools.sort(key=lambda r: r["name"])

    matrix = {
        "schema": "score-matrix/v1",
        "built": datetime.date.today().isoformat(),
        "sources": [
            {"id": "lib06", "label": "本仓库择校库（177 校）",
             "desc": "2026 复试线/历年线/拟招/复试数/录取数/录取最高·最低·均分/复录比/2027改考/导师/N诺明细",
             "path": "06-院校数据库/data/schools/"},
            {"id": "cb", "label": "CodeBrick 录取分数统计（96 校）",
             "desc": "2024–2026 逐年逐项目分位数（408/数学/英语/政治/总分的 min·p25·中位·p75·max·均值），爬取于 2026-09-06",
             "url": "https://www.codebrick.tech/practice/school-admit", "path": "10-录取分数统计/data/schools/"},
        ],
        "stats": {
            "nSchools": len(out_schools),
            "nUnits": sum(len(r.get("units") or []) for r in out_schools),
            "nKq": sum(len(r.get("kq") or []) for r in out_schools),
            "nPrograms": sum(len(r.get("programs") or []) for r in out_schools),
            "nYearRows": sum(len(p.get("years") or []) for r in out_schools for p in (r.get("programs") or [])),
            "nWithCb": sum(1 for r in out_schools if r.get("cbId") is not None),
            "nWith27": sum(1 for r in out_schools if r.get("u27")),
            "nWithTut": sum(1 for r in out_schools if r.get("tut")),
        },
        "schools": out_schools,
    }

    dst = os.path.join(DB6, "data", "score_matrix.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, separators=(",", ":"))
    print("写出 %s  %.0f KB" % (dst, os.path.getsize(dst) / 1024))
    print("  schools=%d units=%d kq=%d programs=%d yearRows=%d cbMatched=%d/%d" % (
        matrix["stats"]["nSchools"], matrix["stats"]["nUnits"], matrix["stats"]["nKq"],
        matrix["stats"]["nPrograms"], matrix["stats"]["nYearRows"], matched, len(cb_by_norm)))

    if yz:
        dst2 = os.path.join(DB6, "data", "yz408_catalog.json")
        with open(dst2, "w", encoding="utf-8") as f:
            json.dump(yz, f, ensure_ascii=False, separators=(",", ":"))
        print("写出 %s  %.0f KB  (%d 校 / %d 条)" % (
            dst2, os.path.getsize(dst2) / 1024, yz["schoolCount"], len(yz["items"])))

    dai = build_dai408()
    if dai:
        dst3 = os.path.join(DB6, "data", "dai408_scores.json")
        with open(dst3, "w", encoding="utf-8") as f:
            json.dump(dai, f, ensure_ascii=False, separators=(",", ":"))
        print("写出 %s  %.0f KB  (%d 校 / %d 条)" % (
            dst3, os.path.getsize(dst3) / 1024, dai["nUniversities"], dai["nRecords"]))


if __name__ == "__main__":
    main()
