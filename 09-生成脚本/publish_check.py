# -*- coding: utf-8 -*-
"""
publish_check.py — 考研数据发布流程的统一门禁（只读检查 + 幂等重生物派生索引）。

用法：仓库根目录执行  python 09-生成脚本/publish_check.py
退出码：0=PASS（可提交推送）；1=有 FAIL 项（先按提示修复）。

检查项：
  C1 浏览器索引再生（调用 build_school_browser_data.py，其内部 assert 即门禁）
  C2 懒加载路径完整（索引里每条 file/cb.id 指向的 JSON 真实存在）
  C3 xlsx 与主网页同步（总览"2026复试线"逐行比对 HTML var S，失步提示跑 make_final_xlsx_v2）
  C4 仓库卫生（本机路径/用户名泄露[Windows 盘符 + /Users/ 双形态]、README 相对链接死链、html 本地 href 死链）
  C5 全部 .py 语法冒烟
  C6 git 工作区状态汇总（不 fetch，离线可跑）
  C7 生成脚本输入存在性（拦"脚本还在、输入已消失"的静默断链；已断链脚本仅 INFO）
  C8 字段类型一致性 + 数值可解析（拦同字段类型漂移、数值列混入不可解析文本）
  C9 规模口径对账（源数据实际值必须能在 docs/口径.md 中找到）
  C10 页面内嵌院校集合 ⊆ 统一库（库不存在则跳过，*.db 按约定不入库）
  C11 全仓死链（覆盖所有 tracked html/md，不只 index/浏览器页/根 README）
  C12 来源分级（sources.tier 无空值且取值合法）+ 冲突裁定规则文件存在
  C13 索引页 ↔ 搜索索引 JSON ↔ 统一库 三者口径一致（索引页是派生产物，最易失步）
  C14 重点院校专档（05-院校专档）索引 ↔ 正文 md ↔ 04 页 var DEEP ↔ 统一库 四者一致
  C15 其余院校轻量速览：_light.json ↔ 04 页速览表 ↔ 深度专档集合 互斥且都在库内
"""
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

B = chr(92)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DB_DIR = "06-院校数据库/data"
CB_DIR = os.path.join("10-录取分数统计", "data")
HTML_04 = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.html"
XLSX_04 = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.xlsx"
INDEX = os.path.join(DB_DIR, "school_browser.json")
RESULTS = []


def grabjs_opt(s, begin):
    """grabjs 的安全版：变量不存在时返回 []（供 var DEEP 这类可选注入用）"""
    try:
        return grabjs(s, begin)
    except ValueError:
        return []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("— " + detail if detail else ""))


def grabjs(s, begin):
    a = s.index(begin) + len(begin)
    while s[a] in " \t\r\n":
        a += 1
    depth, instr, esc = 0, False, False
    for j in range(a, len(s)):
        ch = s[j]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return json.loads(s[a:j + 1])
    raise ValueError("未闭合: " + begin)


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")


# C1 索引再生
r = sh([sys.executable, "-X", "utf8", os.path.join("09-生成脚本", "build_school_browser_data.py")])
check("C1 索引再生+内部断言", r.returncode == 0, (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "")
if r.returncode != 0:
    print(r.stdout, r.stderr)

# C2 懒加载路径完整
idx = json.load(open(INDEX, encoding="utf-8"))
miss = []
for rec in idx["schools"]:
    if rec.get("file") and not os.path.exists(os.path.join("06-院校数据库", rec["file"])):
        miss.append(rec["name"] + ":06")
    cb = rec.get("cb")
    if cb and not os.path.exists(os.path.join(CB_DIR, "schools", str(cb["id"]) + ".json")):
        miss.append(rec["name"] + ":CB")
check("C2 懒加载目标文件齐全(%d条)" % len(idx["schools"]), not miss, "缺失: " + ", ".join(miss[:5]) if miss else "")

# C3 xlsx 与网页同步（多重集逐行比对，容忍同名同学院多行）
try:
    import collections
    import openpyxl
    html = io.open(HTML_04, encoding="utf-8").read()
    S = grabjs(html, "var S=")
    hs = collections.Counter((d["n"], d.get("c") or "", None if d.get("l") is None else float(d["l"])) for d in S)
    wb = openpyxl.load_workbook(XLSX_04, read_only=True)
    ws = wb["总览"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = [str(h) for h in rows[0]]
    iname, icol, iline = hdr.index("院校"), hdr.index("学院"), hdr.index("2026复试线")
    xs = collections.Counter()
    for row in rows[1:]:
        x = row[iline]
        x = None if x in (None, "—", "") else float(x)
        xs[(str(row[iname]), str(row[icol] or ""), x)] += 1
    diff = (hs - xs) + (xs - hs)
    check("C3 xlsx与主网页同步(总览%d行)" % (len(rows) - 1), not diff,
          ("差异: " + str(list(diff.items())[:3]) + " → 跑 make_final_xlsx_v2.py") if diff else "")
except Exception as e:  # noqa: BLE001
    check("C3 xlsx与主网页同步", False, str(e))

# C4 卫生：泄露 + 死链
# 泄露扫描用 Python 直读（git grep 传 C:\ 形态参数会被 MSYS 转换弄坏正则；且默认漏扫 untracked）
def leaked_files():
    # core.quotePath=false：否则 git 把中文路径转成八进制转义，全部 open 失败被静默跳过（09-14 实测）
    files = sh(["git", "-c", "core.quotePath=false", "ls-files", "-co", "--exclude-standard"]).stdout.splitlines()
    # 双形态：Windows 盘符路径（C:\Users\...）与类 Unix 家目录（/Users/...、/home/...）
    pat = re.compile(
        r"[A-Za-z]:" + B * 2 + r"+Users" + B * 2 + r"|/(?:Users|home)/[^\s<>)]*",
        re.I)
    hits = []
    for f in files:
        if not os.path.isfile(f) or os.path.getsize(f) > 3 * 1024 * 1024:
            continue
        try:
            t = io.open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if "publish_check.py" in f.replace("\\", "/").split("/")[-1]:
            continue  # 扫描器不自咬（内含关键词字面量）
        found = []
        for m in pat.finditer(t):
            # 同一 token 片段内出现过 :// 说明是 URL 路径（如 https://x.edu.cn/Home/Detail/7819），非本机路径
            pre = t[max(0, m.start() - 160):m.start()]
            if "://" in re.split(r"""[\s"'<>()\[\],]""", pre)[-1]:
                continue
            found.append(m.group(0)[:60])
        if found or "some work" in t.lower():
            hits.append(f + (" :: " + found[0] if found else ""))
    return hits


leaked = leaked_files()
from urllib.parse import unquote
dead = []
link_pat = re.compile(r'href="([^"]+)"')
md_pat = re.compile(r'\]\(([^)\s]+)\)')
for page in ["index.html", "06-院校数据库/院校数据浏览器.html"]:
    base = os.path.dirname(page) or "."
    for m in link_pat.finditer(io.open(page, encoding="utf-8").read()):
        u = unquote(m.group(1))
        if u.startswith(("http", "mailto", "#", "javascript")):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(base, u))):
            dead.append(page + " → " + u)
md = io.open("README.md", encoding="utf-8").read()
for m in md_pat.finditer(md):
    u = m.group(1)
    if u.startswith(("http", "mailto", "#")):
        continue
    if not os.path.exists(os.path.normpath(u.split("#")[0])):
        dead.append("README.md → " + u)
check("C4 无本机路径泄露/无死链", not leaked and not dead,
      "; ".join((["泄露:" + ",".join(leaked[:3])] if leaked else []) + (["死链:" + ",".join(dead[:5])] if dead else [])))

# C5 语法冒烟
fails = []
for d in ["09-生成脚本", os.path.join("06-院校数据库", "tools")]:
    for f in os.listdir(d):
        if f.endswith(".py"):
            p = os.path.join(d, f)
            if sh([sys.executable, "-X", "utf8", "-m", "py_compile", p]).returncode != 0:
                fails.append(p)
check("C5 全部 .py 语法可编译", not fails, ",".join(fails))

# C6 git 状态（信息性报告：列未提交项，提交前人工确认清单）
st = sh(["git", "status", "--porcelain"])
lines = [l for l in (st.stdout or "").splitlines() if l.strip()]
print("INFO C6 未提交改动 %d 项: %s" % (len(lines), "; ".join(l[:60] for l in lines[:8])))

# C7 生成脚本输入存在性（自动扫描仓库相对路径字面量）
# 目的：拦住"脚本还在、输入已消失"的静默断链（如 ext/ 缺失导致 score_matrix 系列不可再生）
ARCHIVED_SCRIPTS = {
    "build_score_matrix.py": "ext/ 目录整体缺失（外部快照不可再生）",
    "build_final_html.py": "依赖已改名/删除的 01 目录与主文档",
    "make_final_xlsx.py": "含未替换占位符 + 旧目录名",
    "build_final.py": "依赖已删的 md_conv.py 与库外素材",
    "build_408.py": "依赖 2026-09-13 已删的 20260813 一代产物",
    "integrate_three_sources.py": "引用旧目录；重跑会覆盖人工扩容",
    "make_shuangfei_xlsx.py": "引用库外素材目录",
    "build_plan_v2.py": "已退役（产出对应已删除的 01-择校与规划）",
    "validate_db.py": "SCH 指向库外脱敏路径",
    "etl_build_db.py": "引用库外归档路径；重跑会回退复核",
    "update_verify_0903.py": "重跑会回退 09-03 复核",
}
_HEAD_OK = {d for d in os.listdir(".") if os.path.isdir(d) and not d.startswith(".")}
_HEAD_OK |= {"ext", "deliverables", "schema", "docs", "data", "sources"}
_LIT = re.compile(r"""["']([^"'\n]{3,140}?\.(?:json|xlsx|xls|html|htm|md|csv|pdf))["']""")


def _script_inputs(src):
    """抽出脚本里形如 <顶层目录>/<文件名>.<ext> 的仓库相对输入路径（跳过占位符/URL/绝对路径）"""
    out = set()
    for m in _LIT.finditer(src):
        s = m.group(1)
        if s.startswith(("http", "mailto", "#", "%", "-")) or "<" in s or ">" in s:
            continue
        s = s.replace(B, "/")
        if re.match(r"^[A-Za-z]:", s) or s.startswith("/") or "/" not in s:
            continue
        head = s.split("/")[0]
        if head in _HEAD_OK or re.match(r"^\d\d-", head):
            out.add(s)
    return out


broken_active, broken_archived = [], []
for d in ["09-生成脚本", os.path.join("06-院校数据库", "tools")]:
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        src = io.open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
        for p in sorted(_script_inputs(src)):
            if os.path.exists(p):
                continue
            (broken_archived if f in ARCHIVED_SCRIPTS else broken_active).append("%s -> %s" % (f, p))
check("C7 现役脚本输入存在性", not broken_active, "; ".join(broken_active[:4]))
if broken_archived:
    print("INFO C7 已断链脚本 %d 处（已在 09-生成脚本/README.md 登记，不阻断）: %s"
          % (len(broken_archived), "; ".join(broken_archived[:4])))

# C8 字段类型一致性 + 数值纯净度（拦"同字段 str/number 漂移"与"数值列混入不可解析文本"）
NUM_FIELDS_06 = ["line2026", "plan2026", "retestCnt", "admitCnt", "admitMax", "admitMin",
                 "admitAvg", "nn408avg", "nnRate", "heatNet", "heatComp", "wdCount",
                 "wdYears", "ratioRetest", "ratioApply"]
# 允许的定性取值：无数字但有明确语义（页面/DB 按"待核"或 national_line 处理）
QUALI_OK = {"国家线", "国家线(NC)", "待定", "待确认", "未公布", "无", "—", "-"}
_hasnum = re.compile(r"\d")
_sdir = os.path.join("06-院校数据库", "data", "schools")
_sfiles = sorted(f for f in os.listdir(_sdir) if f.endswith(".json")) if os.path.isdir(_sdir) else []
_drift, _unparsable, _kinds = [], [], {}
for fn in _sfiles:
    try:
        d = json.load(io.open(os.path.join(_sdir, fn), encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _drift.append("%s 解析失败(%s)" % (fn, e))
        continue
    for u in (d.get("units") or []):
        for k, v in u.items():
            if v is not None:
                _kinds.setdefault(k, set()).add(type(v).__name__)
        for k in NUM_FIELDS_06:
            v = u.get(k)
            if v is None:
                continue
            if not isinstance(v, str):
                _drift.append("%s.%s 类型=%s（应为字符串或 null）" % (fn, k, type(v).__name__))
            elif not _hasnum.search(v) and v.strip() not in QUALI_OK:
                _unparsable.append("%s.%s=%r" % (fn, k, v[:24]))
for k, ts in sorted(_kinds.items()):
    if len(ts) > 1:
        _drift.append("%s 存在类型漂移 %s" % (k, sorted(ts)))
check("C8 字段类型一致 + 数值可解析(%d校/%d字段)" % (len(_sfiles), len(_kinds)),
      not _drift and not _unparsable, "; ".join((_drift + _unparsable)[:3]))

# C9 规模口径对账（源数据实际值必须能在 docs/口径.md 中找到）
def _cnt(p):
    return len([x for x in os.listdir(p) if x.endswith(".json")]) if os.path.isdir(p) else -1


_facts = {
    "06 主库校数": _cnt(os.path.join("06-院校数据库", "data", "schools")),
    "10 分数库校数": _cnt(os.path.join("10-录取分数统计", "data", "schools")),
}
try:
    _facts["浏览器索引校数"] = json.load(io.open(INDEX, encoding="utf-8")).get("nSchools")
except Exception:  # noqa: BLE001
    _facts["浏览器索引校数"] = -1
try:
    _facts["合并视图校数"] = (json.load(io.open(os.path.join(DB_DIR, "score_matrix.json"), encoding="utf-8")).get("stats") or {}).get("nSchools")
except Exception:  # noqa: BLE001
    _facts["合并视图校数"] = -1
_kj = io.open(os.path.join("docs", "口径.md"), encoding="utf-8").read()
_drift = ["%s=%s 未出现在 docs/口径.md" % (k, v) for k, v in _facts.items() if str(v) not in _kj]
check("C9 规模口径与 docs/口径.md 一致", not _drift, "; ".join(_drift))

# C10 页面内嵌院校集合 与 统一库 的一致性（库不存在则跳过；库有页面无=INFO 可补）
_db = os.path.join(DB_DIR, "kaoyan408.db")
if not os.path.exists(_db):
    print("INFO C10 统一库不存在（*.db 按约定不入库）；本地跑 09-生成脚本/build_unified_db.py 可启用页面↔库比对")
else:
    import sqlite3
    _con = sqlite3.connect(_db)
    _dbnames = {r[0] for r in _con.execute("SELECT name FROM schools")}
    _con.close()
    _page = io.open(HTML_04, encoding="utf-8").read()
    _pnames = {d.get("n") for d in (grabjs(_page, "var S=") + grabjs(_page, "var C=")
                                    + grabjs_opt(_page, "var DEEP=")) if d.get("n")}
    _ghost = sorted(_pnames - _dbnames)
    check("C10 页面院校均在统一库内(页面%d 库%d)" % (len(_pnames), len(_dbnames)), not _ghost,
          ("页面有而库无: " + ", ".join(_ghost[:5])) if _ghost else "")

# C11 全仓死链（不止 index/浏览器页/根 README，覆盖所有 tracked html 与 md）
_tracked = sh(["git", "-c", "core.quotePath=false", "ls-files", "*.html", "*.md"]).stdout.splitlines()
_dead11 = []
for f in _tracked:
    if not os.path.isfile(f) or os.path.getsize(f) > 4 * 1024 * 1024:
        continue
    # 模板文件（05-院校专档/_模板_*.md）里的相对链接是按「被复制到 05-院校专档/<校名>/ 之后」
    # 的位置写的（`../../04-终极版择校/`），在模板自身位置必然不可达 → 跳过。
    # 它们生成的正文里的链接由 C14 所在的 05 目录一起走 C11 校验。
    if os.path.basename(f).startswith("_模板_"):
        continue
    t = io.open(f, encoding="utf-8", errors="ignore").read()
    base = os.path.dirname(f) or "."
    if f.lower().endswith(".md"):
        # Markdown 链接语法只对 .md 生效（否则压缩 JS 里的 ](0,n,e) 数组调用会被误判）
        for m in md_pat.finditer(t):
            u = m.group(1)
            if u.startswith(("http", "mailto", "#")) or any(c in u for c in "+{}$`%"):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, u.split("#")[0]))):
                _dead11.append("%s -> %s" % (f, u))
        continue
    if "录取名单原始材料" in f:
        continue  # 归档的网页原文快照：内部链接指向原站绝对路径，不属本仓死链范畴
    for m in re.finditer(r'(?:href|src)="([^"]+)"', t):
        u = unquote(m.group(1))
        if not u or u.startswith(("http", "mailto", "#", "javascript", "data:", "/")):
            continue  # 根绝对路径属原站 URL，非本仓相对链接
        # 跳过 JS 拼接/模板片段（如 '<a href="'+esc(x)+'">'、'${y}'）与含空白的非路径值
        if any(c in u for c in "+{}$`%") or re.search(r"\s", u):
            continue
        # 必须像路径：含 / 或带已知扩展名（过滤掉 "0" 这类数据值）
        if "/" not in u and not re.search(r"\.(?:html?|md|json|png|jpe?g|svg|gif|css|js|pdf|xlsx?|csv|woff2?)$", u, re.I):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(base, u.split("#")[0].split("?")[0]))):
            _dead11.append("%s -> %s" % (f, u))
check("C11 全仓死链(%d 个 html/md)" % len(_tracked), not _dead11, "; ".join(sorted(set(_dead11))[:4]))

# C12 来源分级与冲突裁定规则（数据可信度的守门）
POLICY_MD = os.path.join("docs", "数据源与冲突裁定.md")
TIERS = {"T1-官方", "T2-官方转载", "T3-第三方整理", "T4-其他", "T4-仓库内"}
_p12 = []
if not os.path.exists(POLICY_MD):
    _p12.append("缺规则文件 docs/数据源与冲突裁定.md")
if os.path.exists(_db):
    _con = sqlite3.connect(_db)
    _n_null = _con.execute("SELECT COUNT(*) FROM sources WHERE tier IS NULL").fetchone()[0]
    if _n_null:
        _p12.append("sources.tier 有 %d 条为空" % _n_null)
    _bad = [t for (t,) in _con.execute("SELECT DISTINCT tier FROM sources WHERE tier IS NOT NULL") if t not in TIERS]
    if _bad:
        _p12.append("tier 取值非法: %s" % _bad)
    _ds = [r for r in _con.execute("SELECT id,url,fetched_at,license FROM dataset_sources")
           if not r[1] or not r[2] or not r[3]]
    if _ds:
        _p12.append("dataset_sources 缺 url/fetched_at/license: %s" % [r[0] for r in _ds])
    _con.close()
else:
    print("INFO C12 统一库不存在，跳过 sources.tier 校验；规则文件存在性仍检查")
check("C12 来源分级 + 冲突裁定规则", not _p12, "; ".join(_p12))

# C13 索引页 ↔ 搜索索引 JSON ↔ 统一库 三者一致（索引页是派生产物，最易失步）
_idx_html = os.path.join("06-院校数据库", "索引.html")
_idx_json = os.path.join("06-院校数据库", "data", "搜索索引.json")
_idx_msg, _idx_ok = "", True
if not (os.path.isfile(_idx_html) and os.path.isfile(_idx_json)):
    _idx_ok, _idx_msg = False, "索引页或索引 JSON 缺失（跑 build_search_index.py）"
else:
    try:
        _j = json.load(io.open(_idx_json, encoding="utf-8"))
        _h = io.open(_idx_html, encoding="utf-8", errors="ignore").read()
        _m = re.search(r"var IDX\s*=\s*(\{)", _h)
        if not _m:
            _idx_ok, _idx_msg = False, "索引页未内嵌 IDX（模板占位符未替换？）"
        else:
            # 从 HTML 里把内嵌 JSON 抠出来，与独立 JSON 文件比对关键口径
            _a = _m.start(1)
            _d, _ins, _esc, _end = 0, False, False, None
            for _i in range(_a, len(_h)):
                _c = _h[_i]
                if _ins:
                    if _esc:
                        _esc = False
                    elif _c == "\\":
                        _esc = True
                    elif _c == '"':
                        _ins = False
                    continue
                if _c == '"':
                    _ins = True
                elif _c in "[{":
                    _d += 1
                elif _c in "]}":
                    _d -= 1
                    if _d == 0:
                        _end = _i + 1
                        break
            _e = json.loads(_h[_a:_end].replace("<\\/", "</"))
            _keys = ("nSchools", "nMajors", "nOfferings", "nFull", "nCatalogOnly", "nLinkOnly")
            _bad = ["%s %s≠%s" % (k, _e["meta"][k], _j["meta"][k]) for k in _keys
                    if _e["meta"][k] != _j["meta"][k]]
            _emb = len(_e.get("schools", []))
            _fil = len(_j.get("schools", []))
            if _emb != _fil:
                _bad.append("内嵌 schools %d≠文件 %d" % (_emb, _fil))
            # 若统一库存在，再与库核对
            _dbp = os.path.join("06-院校数据库", "data", "kaoyan408.db")
            _dbs = ""
            if os.path.isfile(_dbp):
                try:
                    _cn = sqlite3.connect(_dbp)
                    _n = _cn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
                    _cn.close()
                    if _n != _j["meta"]["nSchools"]:
                        _bad.append("库 schools %d≠索引 %d（需重跑 build_search_index.py）"
                                    % (_n, _j["meta"]["nSchools"]))
                    _dbs = "；已与库核对(%d)" % _n
                except sqlite3.Error as _ex:  # noqa: BLE001
                    _dbs = "；库读取失败(%s)" % _ex
            else:
                _dbs = "；库不存在，跳过库核对"
            _idx_ok = not _bad
            _idx_msg = ("; ".join(_bad[:3]) if _bad
                        else "%d 校 / %d 专业 / %d 组合%s" % (_j["meta"]["nSchools"],
                                                             _j["meta"]["nMajors"],
                                                             _j["meta"]["nOfferings"], _dbs))
    except Exception as _ex:  # noqa: BLE001
        _idx_ok, _idx_msg = False, "解析失败：%s" % _ex
check("C13 索引页↔索引JSON↔统一库 口径一致", _idx_ok, _idx_msg)

# C14 重点院校专档（05-院校专档）—— _index.json ↔ 正文 md ↔ 04 页 var DEEP ↔ 统一库 四者一致
_pidx = os.path.join("05-院校专档", "_index.json")
_bad14, _info14 = [], ""
if not os.path.isfile(_pidx):
    _bad14.append("缺 05-院校专档/_index.json（跑 build_school_profiles.py --index）")
else:
    try:
        _pi = json.load(io.open(_pidx, encoding="utf-8"))
        _n14 = _pi.get("nSchools", 0)
        if _n14 != 21:
            _bad14.append("nSchools=%s（应为 21）" % _n14)
        if _pi.get("missing"):
            _bad14.append("缺正文：%s" % "、".join(_pi["missing"][:5]))
        _nfull = 0
        for _it in _pi.get("schools", []):
            _p14 = _it["md"]
            if not os.path.isfile(_p14):
                _bad14.append("md 不存在：%s" % _p14)
                continue
            _t14 = io.open(_p14, encoding="utf-8").read()
            _ln14 = len(_t14.split("\n"))
            _lo14 = 220 if _it.get("depth") == "full" else 90
            if _ln14 < _lo14:
                _bad14.append("%s 仅 %d 行（%s 档需 ≥%d）" % (_it["name"], _ln14, _it.get("depth"), _lo14))
            if "<!--" in _t14:
                _bad14.append("%s 残留 HTML 注释" % _it["name"])
            if hashlib.sha1(_t14.encode("utf-8")).hexdigest() != _it.get("sha1"):
                _bad14.append("%s sha1 与 _index.json 不符（重跑 --index）" % _it["name"])
            if _it.get("depth") == "full":
                _nfull += 1
        if _nfull != 10:
            _bad14.append("full 档 %d 所（应为 10）" % _nfull)
        # var DEEP ↔ _index.json ↔ 统一库
        _h4 = io.open(HTML_04, encoding="utf-8").read()
        _dp = grabjs_opt(_h4, "var DEEP=")
        if not _dp:
            _bad14.append("04 页无 var DEEP（跑 patch_pages_from_db.py --apply）")
        else:
            _dn = {d.get("n") for d in _dp if d.get("n")}
            _in14 = {_it["name"] for _it in _pi.get("schools", [])}
            if _dn != _in14:
                _bad14.append("var DEEP 与 _index.json 校名不一致（DEEP 多 %s / 少 %s）"
                              % (sorted(_dn - _in14)[:3], sorted(_in14 - _dn)[:3]))
            if os.path.isfile(_db):
                _cn = sqlite3.connect(_db)
                _nms = {r[0] for r in _cn.execute("SELECT name FROM schools")}
                _cn.close()
                _gh14 = sorted(_dn - _nms)
                if _gh14:
                    _bad14.append("var DEEP 有而库无：%s" % "、".join(_gh14[:3]))
        _info14 = "%d 校（full %d）/ 缺正文 %d" % (_n14, _nfull, len(_pi.get("missing") or []))
    except Exception as _ex:  # noqa: BLE001
        _bad14.append("解析失败：%s" % _ex)
check("C14 院校专档 索引/正文/页面/库 四者一致", not _bad14,
      ("; ".join(_bad14[:3]) if _bad14 else _info14))

# C15 其余院校轻量速览：_light.json ↔ 04 页速览表 ↔ 深度专档集合 互斥且都在库内
_plight = os.path.join("05-院校专档", "_light.json")
_bad15, _info15 = [], ""
if not os.path.isfile(_plight):
    _bad15.append("缺 05-院校专档/_light.json（跑 build_school_profiles.py --light）")
else:
    try:
        _li = json.load(io.open(_plight, encoding="utf-8"))
        _ln15 = _li.get("nSchools", 0)
        _lset = {x["n"] for x in _li.get("schools", [])}
        if _ln15 != len(_lset):
            _bad15.append("nSchools=%s 与去重后 %s 不符" % (_ln15, len(_lset)))
        _h15 = io.open(HTML_04, encoding="utf-8").read()
        _title = "其余 %d 所速览（轻量）" % _ln15
        if _title not in _h15:
            _bad15.append("04 页无「%s」（跑 patch_pages_from_db.py --apply）" % _title)
        # 与深度专档互斥
        if os.path.isfile(_pidx):
            try:
                _dset = {x["name"] for x in json.load(io.open(_pidx, encoding="utf-8")).get("schools", [])}
                _both = sorted(_lset & _dset)
                if _both:
                    _bad15.append("同时出现在深度专档与速览表：%s" % "、".join(_both[:3]))
            except Exception:  # noqa: BLE001
                pass
        # 都在统一库内
        if os.path.isfile(_db):
            _cn15 = sqlite3.connect(_db)
            _nms15 = {r[0] for r in _cn15.execute("SELECT name FROM schools")}
            _cn15.close()
            _gh15 = sorted(_lset - _nms15)
            if _gh15:
                _bad15.append("速览表有而库无：%s" % "、".join(_gh15[:3]))
        _info15 = "%d 所（与深度专档互斥、均在库内）" % _ln15
    except Exception as _ex:  # noqa: BLE001
        _bad15.append("解析失败：%s" % _ex)
check("C15 其余院校速览表 与库/深度专档 一致", not _bad15,
      ("; ".join(_bad15[:3]) if _bad15 else _info15))

nfail = sum(1 for _, ok, _ in RESULTS if not ok)
print("=" * 46)
print(("发布门禁：PASS，可 commit + push" if nfail == 0 else "发布门禁：FAIL %d 项，先修复" % nfail))
sys.exit(0 if nfail == 0 else 1)
