#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
desensitize_admission_lists.py —— 把 07 号目录的拟录取/复试名单去标识化

背景（2026-10-04 线上评审发现）：
  `07-考情资料/录取名单原始材料/gz_retest_raw.html` 是贵州大学计算机学院复试结果公示的
  原文存档，表格里逐行含**考生编号 + 考生姓名**（341 行）。整个仓库由 GitHub Pages 根目录
  直发，该文件 200 可直链访问，且全站无 noindex —— 等于把真实考生姓名挂在公开流量上。

本脚本做三件事（默认干跑，加 --apply 才落盘）：
  1. HTML：按「列内容特征」精确清空 考生编号（15 位数字）与 考生姓名（2-4 个汉字且该列
     表头含"姓名"）两类单元格，其余数据（序号/专业代码/专业名称/初试/复试/录取结果）全部保留，
     页面仍可用作考情复核依据。
  2. PDF：官方名单 PDF 无法在保留原貌的前提下去名，整份移到仓库外本地留存目录
     （~/kaoyan-本地留存/07-录取名单原始材料/），移前逐个校验 SHA1，校验不过就不动。
  3. 记录：在目录内生成 `_脱敏记录.md`，写明每个文件的 before/after SHA1、命中列、规则与
     **git 历史里仍能找到原件**这一事实（要彻底清除需 filter-repo + 强推，属另一决策）。

用法：
  python 09-生成脚本/desensitize_admission_lists.py            # 干跑：只报命中数
  python 09-生成脚本/desensitize_admission_lists.py --apply     # 真正改写 + 搬移 PDF
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "07-考情资料", "录取名单原始材料")
ARCHIVE = os.path.join(os.path.expanduser("~"), "kaoyan-本地留存", "07-录取名单原始材料")

BANNER = ("<!-- 本文件已去标识化：考生编号与考生姓名两类单元格内容被清空（2026-10-04，"
          "由 09-生成脚本/desensitize_admission_lists.py 生成）。"
          "原件 SHA1 与规则见同目录 _脱敏记录.md。 -->")

CAND_NUM = re.compile(r"^\d{15}$")                      # 教育部考生编号：15 位
CN_NAME = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")         # 姓名：2-4 个汉字
CELL = re.compile(r"(<t[dh][^>]*>)(.*?)(</t[dh]>)", re.S)


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def inner_text(html):
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


def blank_cell(inner):
    """保留原有标签结构，只把文本换成占位符"""
    return re.sub(r">[^<>]+<", "><", inner).replace("&nbsp;", "")


def splice(row_html, cells, edits):
    """按 (cell_index, 新 inner) 重建整行，其余字节原样保留"""
    out, pos = [], 0
    for i, c in enumerate(cells):
        out.append(row_html[pos:c.start(2)])
        out.append(edits[i] if i in edits else c.group(2))
        pos = c.end(2)
        out.append(row_html[pos:c.end(3)])
        pos = c.end(3)
    out.append(row_html[pos:])
    return "".join(out)


def sanitize_html(raw):
    """返回 (新文本, 清空编号数, 清空姓名数, 是否识别到表头列)

    判定刻意保守，避免误伤分析用字段：
      · 考生编号 = 整格恰好 15 位数字（专业代码 6 位、分数 ≤4 位，撞不上）
      · 考生姓名 = 紧跟在考生编号那一格之后的 2-4 个汉字（"软件工程"这类 4 字专业名
        因为不在编号右侧相邻位，不会被清）
      · 表头里含「姓名」/「编号」的格，文字后加「（已脱敏）」，列位不塌陷
    """
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    n_id = [0]
    n_name = [0]
    seen_head = [False]

    def fix_row(m):
        row_html = m.group(0)
        cells = list(CELL.finditer(row_html))
        if not cells:
            return row_html
        texts = [inner_text(c.group(2)) for c in cells]
        edits = {}
        ki = None
        for i, t in enumerate(texts):
            if CAND_NUM.match(t):
                ki = i
                break
        if ki is not None:
            edits[ki] = blank_cell(cells[ki].group(2)) + "已脱敏"
            n_id[0] += 1
            j = ki + 1
            if j < len(texts) and CN_NAME.match(texts[j]):
                edits[j] = blank_cell(cells[j].group(2)) + "已脱敏"
                n_name[0] += 1
        for i, t in enumerate(texts):
            if i in edits or not t or len(t) > 8:
                continue
            if "姓名" in t or "考生编号" in t:
                edits[i] = cells[i].group(2).replace(t, t + "（已脱敏）")
                seen_head[0] = True
        return splice(row_html, cells, edits) if edits else row_html

    text = re.sub(r"<tr\b.*?</tr>", fix_row, text, flags=re.S)
    if n_id[0] or n_name[0]:
        text = re.sub(r"(<title>.*?</title>)", r"\1\n" + BANNER, text, count=1, flags=re.S)
    return text, n_id[0], n_name[0], seen_head[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正改写 HTML 并搬移 PDF")
    a = ap.parse_args()
    if not os.path.isdir(SRC):
        print("✗ 目录不存在：%s" % SRC)
        return 1

    rec = []
    for fn in sorted(os.listdir(SRC)):
        p = os.path.join(SRC, fn)
        if not os.path.isfile(p) or fn.startswith("_"):
            continue
        raw = io.open(p, "rb").read()
        before = sha1(raw)
        if fn.lower().endswith(".html"):
            new, n_id, n_name, heads = sanitize_html(raw)
            rec.append({"file": fn, "sha1_before": before,
                        "sha1_after": sha1(new.encode("utf-8")),
                        "cleared_id": n_id, "cleared_name": n_name,
                        "header_hit": heads, "action": "HTML 去标识化" if (n_id or n_name) else "HTML 未命中（无逐人字段）"})
            print("  %-24s 编号 %3d 格 / 姓名 %3d 格  表头命中=%s  %s"
                  % (fn, n_id, n_name, heads, "改写" if a.apply else "干跑"))
            if a.apply and (n_id or n_name):
                io.open(p, "w", encoding="utf-8", newline="\n").write(new)
        elif fn.lower().endswith(".pdf"):
            rec.append({"file": fn, "sha1_before": before, "sha1_after": "（已移出仓库）",
                        "cleared_id": "-", "cleared_name": "-", "header_hit": "-",
                        "action": "PDF 含逐人姓名且无法保真去名 → 移到本地留存目录"})
            print("  %-24s PDF → 移到 %s  %s" % (fn, ARCHIVE, "搬移" if a.apply else "干跑"))
            if a.apply:
                os.makedirs(ARCHIVE, exist_ok=True)
                dst = os.path.join(ARCHIVE, fn)
                if os.path.exists(dst) and sha1(io.open(dst, "rb").read()) != before:
                    print("    ✗ 留存目录已有同名不同内容文件，跳过：%s" % dst)
                    continue
                shutil.copy2(p, dst)
                if sha1(io.open(dst, "rb").read()) != before:
                    print("    ✗ 复制后 SHA1 不一致，保留仓库原件：%s" % fn)
                    continue
                os.remove(p)
                rec[-1]["action"] += "（已校验 SHA1 后删除仓库副本）"
        else:
            print("  %-24s 其他类型，未处理" % fn)

    if a.apply:
        lines = ["# 录取名单原始材料 · 去标识化记录", "",
                 "> 由 `09-生成脚本/desensitize_admission_lists.py` 生成。", "",
                 "## 为什么做", "",
                 "本目录是各校官网公示页的原文存档（`docs/口径.md` 里的 L1 官方级来源）。",
                 "其中逐人列出了**考生编号**与**考生姓名**，而整仓由 GitHub Pages 根目录直发、",
                 "文件可直链访问，等于把真实考生姓名挂在公开流量上。", "",
                 "## 做了什么", "",
                 "| 文件 | 处理 | 清空单元格 | 原件 SHA1 | 结果 SHA1 |", "|---|---|---|---|---|"]
        for r in rec:
            lines.append("| `%s` | %s | 编号 %s / 姓名 %s | `%s` | `%s` |"
                         % (r["file"], r["action"], r["cleared_id"], r["cleared_name"],
                            r["sha1_before"][:12], str(r["sha1_after"])[:12]))
        lines += ["", "## 规则", "",
                  "- 只按**表头含「姓名」/「编号」**的列判定，再按内容特征（15 位数字 / 2-4 汉字）清空该格文本；",
                  "  序号、专业代码、专业名称、初试分、复试分、录取结果等分析用字段全部保留。",
                  "- PDF 无法在保留原貌的前提下去名，整份移到仓库外 `~/kaoyan-本地留存/07-录取名单原始材料/`，",
                  "  移前移后各算一次 SHA1，不一致就不删仓库副本。", "",
                  "## 仍然存在的暴露面（重要）", "",
                  "**Git 历史里能直接取到原件**：`git log --diff-filter=D` 找到删除提交，",
                  "再 `git show <删除前提交>:<路径>` 即可还原含姓名的原始页与 PDF。",
                  "要彻底清除必须 `git filter-repo` 抹历史 + 强推（破坏性，所有 clone 需重做），",
                  "并另行向 Google/Bing 提交已收录快照的移除请求。本仓库当前**未做**历史改写。", ""]
        io.open(os.path.join(SRC, "_脱敏记录.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines))
        print("✓ 已写 %s" % os.path.join(SRC, "_脱敏记录.md"))
    else:
        print("\n（干跑，未写盘。加 --apply 生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
