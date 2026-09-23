#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_school_profiles.py —— 重点院校「数据底稿」生成器（05-院校专档 工作流）

定位：**数据搬运工，不写叙述。** 从统一库把某校的全部数据搬成结构化 JSON，
      供后续写作（人工或 agent）引用 —— 写作方只准引用底稿，不得自行查库/推算/跨校搬数。

输入（正本，勿手改）：
  06-院校数据库/data/kaoyan408.db                     由 build_unified_db.py 生成
  07-考情资料/补充表格/*.xlsx                          逐人明细 / 同档横评 / 单校深挖

输出：
  05-院校专档/_数据底稿/<校名>.json                     每校一份（默认模式）
  05-院校专档/_index.json                              专档清单 + 行数 + sha1（--index 模式）
  05-院校专档/_deep.json                               04 页 var DEEP 用的摘要（--index 模式）
  05-院校专档/专档索引.xlsx                             21 行汇总（--index 模式）

用法：
  python 09-生成脚本/build_school_profiles.py             # 生成 21 份底稿
  python 09-生成脚本/build_school_profiles.py --index     # 扫描已写好的 md → _index/_deep/索引表

约定：幂等（sort_keys）、跨平台（os.path + 相对路径）、UTF-8 无 BOM + LF、不改任何 HTML。
"""
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "06-院校数据库", "data", "kaoyan408.db")
PROFILE_DIR = os.path.join(ROOT, "05-院校专档")
DRAFT_DIR = os.path.join(PROFILE_DIR, "_数据底稿")
XLSX_DIR = os.path.join(ROOT, "07-考情资料", "补充表格")

# ---------------- 21 所重点校（深度档：full=13 章节 / lite=8 区块） ----------------
SCHOOLS = [
    ("南京邮电大学", "full"), ("深圳大学", "full"), ("南京信息工程大学", "full"),
    ("成都信息工程大学", "full"), ("上海科技大学", "full"), ("杭州电子科技大学", "full"),
    ("湖北大学", "full"), ("山西大学", "full"), ("昆明理工大学", "full"), ("中北大学", "full"),
    ("浙江理工大学", "lite"), ("安徽理工大学", "lite"), ("天津工业大学", "lite"),
    ("苏州科技大学", "lite"), ("太原科技大学", "lite"), ("浙江农林大学", "lite"),
    ("佛山大学", "lite"), ("滁州学院", "lite"), ("成都理工大学", "lite"),
    ("中国民用航空飞行学院", "lite"), ("重庆科技大学", "lite"),
]

# B 区省份（用于判定国家线档位）
B_ZONE = {"内蒙古", "广西", "海南", "贵州", "云南", "西藏", "甘肃", "青海", "宁夏", "新疆"}

# 逐人/深挖 xlsx 与学校的映射：校名 -> [(xlsx 文件名, [Sheet 名] 或 None=全部)]
XLSX_MAP = {
    "中国民用航空飞行学院": [("2026计算机考研逐人数据_中飞院_成信工_重科大_V2.xlsx",
                             ["说明与来源", "中飞院-拟录取(含单科)", "各科均分总表"])],
    "成都信息工程大学": [("2026计算机考研逐人数据_中飞院_成信工_重科大_V2.xlsx",
                          ["说明与来源", "成信工-计算机学院", "成信工-人工智能学院", "各科均分总表"]),
                         ("成信工同档院校详细横评_2026.xlsx", None)],
    "重庆科技大学": [("2026计算机考研逐人数据_中飞院_成信工_重科大_V2.xlsx",
                      ["说明与来源", "重科大-一志愿", "各科均分总表"])],
    "成都理工大学": [("成都理工大学计算机考研深挖_2026.xlsx", None)],
    # 昆明理工：同档横评里含其要点，供写作复用
    "昆明理工大学": [("成信工同档院校详细横评_2026.xlsx", None)],
}

TABLES = ["offerings", "admissions", "score_lines", "score_quantiles", "score_bands",
          "tutors", "kaoqing", "updates_2027", "catalog", "wangdao_links", "sources",
          "conflicts", "stats_yoy", "dai408_records"]


def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def wr(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def rows(cur, sql, args=()):
    cur.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def national_line_map(cur):
    """year -> {'A区': n, 'B区': n}；缺档位记 None"""
    m = {}
    for r in cur.execute("SELECT year, zone, total_line, subject_408_line FROM national_lines").fetchall():
        m.setdefault(int(r[0]), {})[r[1]] = {"total": r[2], "s408": r[3]}
    return m


def read_xlsx(path, sheets=None):
    """读 xlsx 为 {sheet: {'headers': [...], 'rows': [[...]]}}；表头取首个非空行"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"_error": "openpyxl 未安装，跳过 xlsx 解析"}
    out = {}
    wb = load_workbook(path, read_only=True, data_only=True)
    names = sheets if sheets else wb.sheetnames
    for sn in names:
        if sn not in wb.sheetnames:
            continue
        ws = wb[sn]
        all_rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hdr_i, hdr = None, []
        for i, r in enumerate(all_rows[:8]):
            filled = [c for c in r if c not in (None, "")]
            if len(filled) >= 3:
                hdr_i, hdr = i, [("" if c is None else str(c)) for c in r]
                break
        body = []
        if hdr_i is not None:
            for r in all_rows[hdr_i + 1:]:
                if any(c not in (None, "") for c in r):
                    body.append([None if c is None else (c if isinstance(c, (int, float)) else str(c)) for c in r])
        out[sn] = {"headers": hdr, "rows": body, "n_rows": len(body)}
    wb.close()
    return out


def build_draft(cur, nlmap, name, depth):
    r = rows(cur, "SELECT * FROM schools WHERE name=?", (name,))
    if not r:
        return None, "不在统一库"
    s = r[0]
    k = s["school_key"]
    d = {
        "_meta": {
            "school": name, "school_key": k, "depth": depth,
            "generated": str(date.today()),
            "db": "06-院校数据库/data/kaoyan408.db",
            "generator": "09-生成脚本/build_school_profiles.py",
            "rules": {
                "source_tiers": {"T1": "官方一手", "T2": "官方转载", "T3": "第三方整理", "T4": "仓库内值"},
                "is_national_line_rule": "value ∈ {当年A区线, 当年B区线} → 执行国家线；**不得依赖 score_lines.basis**",
                "triplet_rule": "分数线必须按 (学校+专业+学院) 三元组呈现，禁止合并成一行",
                "null_rule": "缺失写「未获取」，禁止猜测 / 推算 / 跨校搬数",
                "no_fabrication": "底稿之外的数字只能联网取证并贴完整 URL",
            },
            "national_lines": nlmap,
        },
        "school": s,
    }
    for t in TABLES:
        d[t] = rows(cur, 'SELECT * FROM "%s" WHERE school_key=? ORDER BY id' % t, (k,)) \
            if t != "score_bands" else rows(cur, 'SELECT * FROM score_bands WHERE school_key=?', (k,))
    # score_lines 注入国家线判定
    zone = "B区" if (s.get("province") or "") in B_ZONE else "A区"
    for ln in d["score_lines"]:
        y = ln.get("year")
        nat = (nlmap.get(int(y)) or {}).get(zone) if y else None
        ln["zone"] = zone
        ln["national_line_value"] = nat["total"] if nat else None
        try:
            v = float(ln["value"]) if ln.get("value") is not None else None
        except (TypeError, ValueError):
            v = None
        ln["is_national_line"] = bool(v is not None and nat and abs(v - nat["total"]) < 0.5)
    # exam_subjects（挂 offering_id）
    d["exam_subjects"] = rows(
        cur, "SELECT e.*, o.college, o.major_code FROM exam_subjects e "
             "JOIN offerings o ON o.id=e.offering_id WHERE o.school_key=? ORDER BY e.offering_id", (k,))
    # 07 xlsx 逐人/深挖
    d["students"] = {}
    for fn, sheets in XLSX_MAP.get(name, []):
        p = os.path.join(XLSX_DIR, fn)
        if os.path.isfile(p):
            d["students"][fn] = read_xlsx(p, sheets)

    # ---------------- gaps ----------------
    gaps = []
    if not s.get("code_verified"):
        gaps.append("招生单位代码未验证（school_key 为 X- 前缀），需人工确认教育部代码")
    if not s.get("cs_rank"):
        gaps.append("CS 学科排名（cs_rank）未获取")
    if not s.get("region"):
        gaps.append("大区（region）未获取")
    for o in d["offerings"]:
        if not o.get("major_code"):
            gaps.append("offering 专业代码未识别：%s / %s" % (o.get("college") or "?", o.get("direction") or "?"))
    for ln in d["score_lines"]:
        if ln.get("national_line_value") is None:
            gaps.append("%s 年国家线（%s）未收录，无法判定是否执行国家线" % (ln.get("year"), zone))
    if not [ln for ln in d["score_lines"] if ln.get("year") == 2026]:
        gaps.append("2026 复试线未获取")
    if d["admissions"]:
        a = d["admissions"][0]
        for f, label in (("plan_value", "拟招"), ("retest_cnt_value", "复试数"),
                         ("admit_cnt_value", "录取数"), ("admit_min_value", "录取最低分"),
                         ("admit_max_value", "录取最高分"), ("admit_avg_value", "录取均分")):
            if a.get(f) is None:
                gaps.append("2026 %s 未获取" % label)
    if not d["tutors"]:
        gaps.append("导师未收录（tutors 表全库仅覆盖 16 校）")
    if not d["score_quantiles"]:
        gaps.append("无 CodeBrick 逐年分位数据")
    if not d["score_bands"]:
        gaps.append("无分数带分布数据")
    if not d["updates_2027"]:
        gaps.append("2027 改考动态未获取")
    if not d["catalog"]:
        gaps.append("研招网招生目录未收录")
    if not d["sources"]:
        gaps.append("无来源登记（sources 表）")
    for c in d["conflicts"]:
        gaps.append("冲突登记：%s（%s）" % (c.get("field"), c.get("status")))
    d["gaps"] = sorted(set(gaps))
    d["counts"] = {t: len(d[t]) for t in TABLES}
    d["counts"]["exam_subjects"] = len(d["exam_subjects"])
    d["counts"]["students_sheets"] = sum(len(v) for v in d["students"].values())
    return d, None


# ---------------- --index 模式：扫 md 出 _index / _deep / 索引表 ----------------
SEC_ONE_PAGE = re.compile(r"^##\s*[〇零一二三四五六七八九十\d]*[、.．]?\s*一页结论", re.M)


def parse_md(path):
    t = io.open(path, encoding="utf-8").read()
    lines = t.split("\n")
    m = SEC_ONE_PAGE.search(t)
    bullets = []
    if m:
        rest = t[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        body = rest[:nxt.start()] if nxt else rest
        for ln in body.split("\n"):
            s = ln.strip()
            if re.match(r"^(\d+[.、)]|[-*])\s+", s):
                bullets.append(re.sub(r"^(\d+[.、)]|[-*])\s+", "", s))
            if len(bullets) >= 5:
                break
    verdict = None
    for ln in lines:
        if "定位" in ln and re.search(r"[冲稳保]", ln):
            mm = re.search(r"[「『\[]?([冲稳保])[」』\]]?\s*档?", ln)
            if mm:
                verdict = mm.group(1)
                break
    if verdict is None:      # 「不适合 22408 考生」「直接排除」这类也是有效结论
        for ln in lines:
            if "定位" in ln and re.search(r"不适合|排除|不匹配|无 408", ln):
                verdict = "排除"
                break
    return {"bullets": bullets, "verdict": verdict,
            "n_lines": len(lines), "n_h2": len(re.findall(r"^##\s", t, re.M)),
            "sha1": hashlib.sha1(t.encode("utf-8")).hexdigest(),
            "has_comment": "<!--" in t,
            "n_url": len(re.findall(r"https?://", t)),
            "n_tier_mark": len(re.findall(r"【T[1-4]】", t))}


def do_index(cur, nlmap):
    con_names = {}
    for n, depth in SCHOOLS:
        r = rows(cur, "SELECT school_key, code, province, region, tier, is985, is211 FROM schools WHERE name=?", (n,))
        con_names[n] = (r[0] if r else {}), depth
    idx, deep, missing = [], [], []
    for n, depth in SCHOOLS:
        srow, _ = con_names[n]
        k = srow.get("school_key") or ("X-" + n)
        # 找 md
        md_path = None
        d = os.path.join(PROFILE_DIR, n)
        if os.path.isdir(d):
            cands = [f for f in os.listdir(d) if f.endswith(".md") and f != "README.md"]
            # 同一校可能有多版（如成信工 _20260903 历史基线 / _20260923 现行正本）→ 取日期最新那版
            def _ver(f):
                mm = re.search(r"_(\d{8})\.md$", f)
                return mm.group(1) if mm else "00000000"
            if cands:
                md_path = os.path.join(d, sorted(cands, key=_ver)[-1])
        if not md_path:
            missing.append(n)
            continue
        info = parse_md(md_path)
        rel = os.path.relpath(md_path, ROOT).replace(os.sep, "/")
        idx.append({"name": n, "school_key": k, "depth": depth, "md": rel,
                    "lines": info["n_lines"], "n_h2": info["n_h2"], "sha1": info["sha1"],
                    "has_comment": info["has_comment"], "n_url": info["n_url"],
                    "n_tier_mark": info["n_tier_mark"]})
        # deep 摘要
        a = rows(cur, "SELECT * FROM admissions WHERE school_key=?", (k,))
        a = a[0] if a else {}
        zone = "B区" if (srow.get("province") or "") in B_ZONE else "A区"
        nat = (nlmap.get(2026) or {}).get(zone)
        line = None
        for ln in rows(cur, "SELECT value, year, major_code FROM score_lines "
                            "WHERE school_key=? AND year=2026", (k,)):
            try:
                line = float(ln["value"])
                break
            except (TypeError, ValueError):
                pass
        natv = nat["total"] if nat else None
        deep.append({
            "n": n, "k": k, "t": srow.get("tier") or "", "depth": depth,
            "verdict": info["verdict"], "subj": "",
            "line": int(line) if line is not None else None, "nat": natv,
            "gap": (int(line) - natv) if (line is not None and natv) else None,
            "plan": a.get("plan_value"), "retest": a.get("retest_cnt_value"),
            "admit": a.get("admit_cnt_value"), "avg": a.get("admit_avg_value"),
            "min": a.get("admit_min_value"), "max": a.get("admit_max_value"),
            "bullets": info["bullets"], "md": rel, "updated": str(date.today()).replace("-", ""),
        })
    wr(os.path.join(PROFILE_DIR, "_index.json"),
       jdump({"nSchools": len(idx), "generated": str(date.today()),
              "missing": missing, "schools": idx}))
    wr(os.path.join(PROFILE_DIR, "_deep.json"), jdump(deep))
    # 专档索引.xlsx
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "专档索引"
        ws.append(["#", "院校", "招生单位代码", "层次", "深度档", "行数", "章节数",
                   "来源标注数", "URL 数", "2026线", "国家线", "线差", "定位", "文件"])
        for i, (ix, dp) in enumerate(zip(idx, deep), 1):
            ws.append([i, ix["name"], dp["k"], dp["t"], ix["depth"], ix["lines"], ix["n_h2"],
                       ix["n_tier_mark"], ix["n_url"], dp["line"], dp["nat"], dp["gap"],
                       dp["verdict"] or "", ix["md"]])
        for col, w in zip("ABCDEFGHIJKLMN", [4, 20, 14, 12, 8, 7, 8, 10, 7, 8, 8, 7, 7, 60]):
            ws.column_dimensions[col].width = w
        wb.save(os.path.join(PROFILE_DIR, "专档索引.xlsx"))
        xlsx_ok = True
    except ImportError:
        xlsx_ok = False
    print("✓ _index.json：%d 校（缺 %d：%s）" % (len(idx), len(missing), missing or "无"))
    print("✓ _deep.json：%d 条" % len(deep))
    print("✓ 专档索引.xlsx：%s" % ("已生成" if xlsx_ok else "跳过（openpyxl 未安装）"))
    bad = [i for i in idx if (i["depth"] == "full" and i["lines"] < 220) or
           (i["depth"] == "lite" and i["lines"] < 90) or i["has_comment"]]
    if bad:
        print("⚠ 未达标的：")
        for b in bad:
            print("   %-18s %d 行 %s" % (b["name"], b["lines"],
                                        "（含未清理的 HTML 注释）" if b["has_comment"] else ""))
    else:
        print("✓ 全部达标（完整版 ≥220 行 / 精简版 ≥90 行 / 无残留注释）")
    return 0


# ---------------- --light 模式：其余院校轻量速览（一表一校一行） ----------------
HTML_04 = os.path.join(ROOT, "04-终极版择校", "全国408_085410双非热度版_终极版_20260826.html")


def grab_js_array(path, var):
    """从 HTML 里抠出 var X=[...] 的 JSON（括号配平）"""
    t = io.open(path, encoding="utf-8").read()
    key = "var " + var + "="
    if key not in t:
        return []
    a = t.index(key) + len(key)
    while t[a] in " \t\r\n":
        a += 1
    depth, ins, esc = 0, False, False
    for j in range(a, len(t)):
        c = t[j]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
            continue
        if c == '"':
            ins = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return json.loads(t[a:j + 1].replace("<\\/", "</"))
    return []


def do_light(cur, nlmap):
    """为「04 页 var S 覆盖、但没有深度专档」的院校生成轻量速览（一校一行）。"""
    done = {n for n, _ in SCHOOLS}
    S = grab_js_array(HTML_04, "S")
    C = grab_js_array(HTML_04, "C")
    seen, order = set(), []
    for d in S + C:
        n = d.get("n")
        if n and n not in seen:
            seen.add(n)
            order.append((n, d))
    todo = [(n, d) for n, d in order if n not in done]
    rows_out = []
    for n, d in todo:
        rs = rows(cur, "SELECT * FROM schools WHERE name=?", (n,))
        if not rs:
            continue
        r = rs[0]
        k = r["school_key"]
        a = rows(cur, "SELECT * FROM admissions WHERE school_key=?", (k,))
        a = a[0] if a else {}
        line = None
        for x in rows(cur, "SELECT value, year FROM score_lines WHERE school_key=? AND year=2026", (k,)):
            try:
                line = int(float(x["value"]))
                break
            except (TypeError, ValueError):
                pass
        zone = "B区" if (r["province"] or "") in B_ZONE else "A区"
        nat = (nlmap.get(2026) or {}).get(zone)
        natv = nat["total"] if nat else None
        lv = rows(cur, "SELECT data_level FROM v_school_all WHERE school_key=?", (k,))
        rows_out.append({
            "n": n, "k": k, "t": r["tier"] or "", "p": r["province"] or "", "r": r["region"] or "",
            "sc": d.get("t") or "", "lvl": (lv[0]["data_level"] if lv else ""),
            "line": line, "nat": natv,
            "is_nat": bool(line is not None and natv is not None and line == natv),
            "plan": a.get("plan_value"), "retest": a.get("retest_cnt_value"),
            "admit": a.get("admit_cnt_value"), "avg": a.get("admit_avg_value"),
            "u27": len(rows(cur, "SELECT id FROM updates_2027 WHERE school_key=?", (k,))),
            "wd": len(rows(cur, "SELECT id FROM wangdao_links WHERE school_key=?", (k,))),
            "note": (r["note"] or "").replace("\n", " ")[:120],
            "in_s": n in {x.get("n") for x in S},
        })
    rows_out.sort(key=lambda x: (-(x["line"] or 0), x["n"]))
    wr(os.path.join(PROFILE_DIR, "_light.json"),
       jdump({"generated": str(date.today()),
              "source": "04 页 var S+C 覆盖、但没有深度专档的院校（一表一校一行）",
              "nSchools": len(rows_out), "schools": rows_out}))
    # markdown 表
    md = ["# 其余院校速览（轻量）", "",
          "> 本文件为**轻量速览**：每校一行，只带关键口径。需要深度的 21 所见 `05-院校专档/<校名>/`。",
          "> 数据来源：统一库 `kaoyan408.db`（`06` 择校库 + 研招网目录 + Dai408）；口径见 [`docs/口径.md`](../docs/口径.md)。",
          "> 生成脚本：`09-生成脚本/build_school_profiles.py --light`｜生成日期 %s" % date.today(), "",
          "| 院校 | 层次 | 省市 | 2026线 | 国家线 | 是否执行国家线 | 拟招 | 复试 | 录取 | 录取均分 | 2027改考 | 王道链接 | 数据档 | 备注 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows_out:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            x["n"], x["t"] or "—", (x["p"] or "—") + (x["r"] and "/" + x["r"] or ""),
            x["line"] if x["line"] is not None else "未获取",
            x["nat"] if x["nat"] is not None else "未获取",
            ("是" if x["is_nat"] else "否") if x["line"] is not None else "未获取",
            x["plan"] if x["plan"] is not None else "未获取",
            x["retest"] if x["retest"] is not None else "未获取",
            x["admit"] if x["admit"] is not None else "未获取",
            x["avg"] if x["avg"] is not None else "未获取",
            ("有 %d 条" % x["u27"]) if x["u27"] else "未获取",
            x["wd"] or "未获取",
            {"full": "有实质数据", "catalog_only": "仅目录", "link_only": "仅链接"}.get(x["lvl"], x["lvl"]),
            (x["note"][:60] or "—").replace("|", "/")))
    wr(os.path.join(PROFILE_DIR, "其余院校速览.md"), "\n".join(md) + "\n")
    print("✓ _light.json + 其余院校速览.md：%d 所（04 页 S+C 共 %d 所，已做专档 %d 所）"
          % (len(rows_out), len(order), len(done)))
    return 0


def main():
    if not os.path.isfile(DB):
        print("✗ 未找到 %s\n  请先运行：python 09-生成脚本/build_unified_db.py" % DB)
        return 1
    con = sqlite3.connect(DB)
    cur = con.cursor()
    nlmap = national_line_map(cur)
    print("国家线表：%s" % json.dumps(nlmap, ensure_ascii=False))
    for y in sorted(nlmap):
        if "A区" not in nlmap[y] or "B区" not in nlmap[y]:
            print("  ⚠ %d 年缺档位：%s（相关年份无法判定是否执行国家线）" % (y, sorted(nlmap[y])))

    if "--index" in sys.argv:
        rc = do_index(cur, nlmap)
        con.close()
        return rc

    if "--light" in sys.argv:
        rc = do_light(cur, nlmap)
        con.close()
        return rc

    ok, fail = 0, []
    for name, depth in SCHOOLS:
        d, err = build_draft(cur, nlmap, name, depth)
        if d is None:
            fail.append((name, err)); continue
        wr(os.path.join(DRAFT_DIR, name + ".json"), jdump(d))
        ok += 1
    con.close()
    print()
    print("✓ 底稿 %d / %d 份 → 05-院校专档/_数据底稿/" % (ok, len(SCHOOLS)))
    if fail:
        for n, e in fail:
            print("  ✗ %s：%s" % (n, e))
    # 概览
    print()
    print("%-20s %-5s %5s %5s %5s %5s %5s %5s %5s" % ("院校", "深度", "offr", "线", "招录", "分位", "导师", "改考", "缺口"))
    for name, depth in SCHOOLS:
        p = os.path.join(DRAFT_DIR, name + ".json")
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        c = d["counts"]
        print("%-20s %-5s %5d %5d %5d %5d %5d %5d %5d" % (
            name, depth, c["offerings"], c["score_lines"], c["admissions"],
            c["score_quantiles"], c["tutors"], c["updates_2027"], len(d["gaps"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
