# -*- coding: utf-8 -*-
"""
publish_check.py — 考研数据发布流程的统一门禁（只读检查 + 幂等重生物派生索引）。

用法：仓库根目录执行  python 09-生成脚本/publish_check.py
退出码：0=PASS（可提交推送）；1=有 FAIL 项（先按提示修复）。

检查项：
  C1 浏览器索引再生（调用 build_school_browser_data.py，其内部 assert 即门禁）
  C2 懒加载路径完整（索引里每条 file/cb.id 指向的 JSON 真实存在）
  C3 xlsx 与主网页同步（总览"2026复试线"逐行比对 HTML var S，失步提示跑 make_final_xlsx_v2）
  C4 仓库卫生（本机路径/用户名泄露、README 相对链接死链、html 本地 href 死链）
  C5 全部 .py 语法冒烟
  C6 git 工作区状态汇总（不 fetch，离线可跑）
"""
import io
import json
import os
import re
import subprocess
import sys

B = chr(92)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DB_DIR = "06-院校数据库/data"
CB_DIR = os.path.join("10-录取分数统计", "data")
HTML_04 = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.html"
XLSX_04 = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.xlsx"
INDEX = os.path.join(DB_DIR, "school_browser.json")
RESULTS = []


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

# C4 卫生：泄露 + 死链（排除本脚本：其内含检测关键词字面量，扫描器不自咬）
leak = sh(["git", "grep", "-l", "-i", "some work", "--", ".", ":(exclude)09-生成脚本/publish_check.py"])
leak2 = sh(["git", "grep", "-l", "华硕", "--", ".", ":(exclude)09-生成脚本/publish_check.py"])
leaked = sorted(set((leak.stdout or "").split() + (leak2.stdout or "").split()))
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

nfail = sum(1 for _, ok, _ in RESULTS if not ok)
print("=" * 46)
print(("发布门禁：PASS，可 commit + push" if nfail == 0 else "发布门禁：FAIL %d 项，先修复" % nfail))
sys.exit(0 if nfail == 0 else 1)
