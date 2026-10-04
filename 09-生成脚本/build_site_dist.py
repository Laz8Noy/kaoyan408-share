#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_site_dist.py —— 从仓库里装配一份「可直接托管」的静态站点产物 dist/

为什么需要它：
  仓库 main 现在 1300+ 文件 / 58 MB，其中 `12-408名词罗盘` 独占 39 MB（406 个 .woff 约
  12.9 MB 浏览器根本不下、`project/` 是 Vite 源码、`sources/` 的 PDF 与
  `project/public/sources/` 同 blob 重复）。任何有 50 MiB 产物上限的托管（含 Qoder Sites）
  整仓直推都会被拒。本脚本**不删仓库任何文件**，只把该上线的东西按原相对层级拷进 dist/，
  因为页面之间用相对路径互链（如 浏览器 里 fetch("../10-录取分数统计/data/schools/"+id)），
  层级一变形就全断。

用法：
  python 09-生成脚本/build_site_dist.py            # 装配 dist/
  python 09-生成脚本/build_site_dist.py --dry-run  # 只列清单与体积，不落盘
  python 09-生成脚本/build_site_dist.py --clean    # 先删掉上一次本脚本产出的 dist/（有标记文件才敢删）

托管时：projectRoot 指向仓库根，webDirectory 填 "dist"（平台要求输出目录必须存在 index.html
且不得等于项目根）。
"""
import argparse
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist")
MARKER = ".dist-manifest.json"

# 顶层白名单：只有这些目录/文件会进产物
INCLUDE_TOP = {
    "index.html", "robots.txt", ".nojekyll",
    "02-院校数据", "03-川渝408", "04-终极版择校", "05-院校专档",
    "06-院校数据库", "08-推荐器网页", "10-录取分数统计",
    "11-408专业课交互课件", "12-408名词罗盘",
}
# 明确不上线的（源码、脚本、原始资料、派生库），列出来是为了"为什么不上"有据可查
EXCLUDE_TOP = {
    "01-导师与规划": "含具名导师个人信息，需单独确认公开范围",
    "07-考情资料": "考情原始存档（已去标识化但体积大、非页面），不上线",
    "09-生成脚本": "构建脚本与门禁，属仓库内部工具，不对外发布",
    "docs": "Markdown 在静态托管上是裸文本/下载，页面里已改为指向 GitHub 渲染版",
    "README.md": "仓库门面文档，站点不需要",
    "CONTRIBUTING.md": "贡献规范，站点不需要",
    "LICENSE": "可保留但当前产物不放",
    ".gitignore": "版本控制文件", ".gitattributes": "版本控制文件",
}
# 文件级排除：命中即跳过（相对 dist 的路径前缀 / 后缀）
EXCLUDE_PATH_PREFIX = ("12-408名词罗盘/project/", "12-408名词罗盘/sources/",
                       "05-院校专档/_数据底稿/")
EXCLUDE_SUFFIX = (".woff", ".ttf", ".db", ".xlsx", ".md", ".py", ".jsonl", ".bak")
# 但 .json 数据要保留（懒加载靠它），所以后缀规则里不含 .json；md 走单独例外
KEEP_SUFFIX_ANYWAY = (".html", ".css", ".js", ".json", ".woff2", ".svg", ".png", ".jpg",
                      ".ico", ".map", ".txt", ".pdf")

LIMIT_MIB = 50.0


def keep(rel):
    """rel: 正斜杠、相对仓库根的路径"""
    top = rel.split("/")[0]
    if rel not in INCLUDE_TOP and top not in INCLUDE_TOP:
        return False, "顶层不在白名单"
    for p in EXCLUDE_PATH_PREFIX:
        if rel.startswith(p):
            return False, "排除目录 %s" % p
    low = rel.lower()
    if low.endswith(EXCLUDE_SUFFIX):
        # 例外：07 已整体排除；这里主要挡 .woff/.md/.xlsx/.py/.db
        if low.endswith(KEEP_SUFFIX_ANYWAY) and not low.endswith((".woff", ".ttf")):
            return True, ""
        return False, "按后缀排除"
    return True, ""


def collect():
    picked, skipped = [], {}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "dist", "_bak",
                                                "__pycache__", ".qoder")]
        rel_base = os.path.relpath(base, ROOT).replace(os.sep, "/")
        if rel_base == ".":
            rel_base = ""
        for f in files:
            rel = (rel_base + "/" + f) if rel_base else f
            ok, why = keep(rel)
            if ok:
                picked.append(rel)
            else:
                skipped[why] = skipped.get(why, 0) + 1
    return picked, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true")
    a = ap.parse_args()

    picked, skipped = collect()
    total = sum(os.path.getsize(os.path.join(ROOT, p)) for p in picked)
    print("入选 %d 个文件，共 %.2f MiB（上限 %.0f MiB）" % (len(picked), total / 1048576.0, LIMIT_MIB))
    print("排除统计：", json.dumps(skipped, ensure_ascii=False))
    by_top = {}
    for p in picked:
        t = p.split("/")[0]
        by_top[t] = by_top.get(t, [0, 0])
        by_top[t][0] += 1
        by_top[t][1] += os.path.getsize(os.path.join(ROOT, p))
    for t, (n, b) in sorted(by_top.items(), key=lambda x: -x[1][1]):
        print("   %-24s %5d 个  %7.2f MiB" % (t, n, b / 1048576.0))
    if total / 1048576.0 > LIMIT_MIB:
        print("✗ 仍超上限，需要再裁（先考虑 12 号目录字体与 04/02/03 的历史版本页）")
        return 1
    if a.dry_run:
        print("\n（--dry-run，未写盘）")
        return 0

    if a.clean and os.path.isdir(OUT):
        if os.path.isfile(os.path.join(OUT, MARKER)):
            shutil.rmtree(OUT)
            print("✓ 已清空上一次产出的 dist/")
        else:
            print("✗ dist/ 存在但没有 %s，不是本脚本产出的，拒绝删除" % MARKER)
            return 1

    os.makedirs(OUT, exist_ok=True)
    n = 0
    for rel in picked:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst) or OUT, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    io.open(os.path.join(OUT, MARKER), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"generator": "09-生成脚本/build_site_dist.py", "files": n,
                    "bytes": total, "note": "本目录是产物，勿手改；删除前可凭此标记识别"},
                   ensure_ascii=False, indent=2))
    print("✓ 已装配 %s（%d 个文件）" % (os.path.relpath(OUT, ROOT).replace(os.sep, "/"), n))
    # 自检：入口与懒加载目标必须都在产物里，否则上线后是白屏/取数失败
    need = ["index.html", "06-院校数据库/索引.html", "06-院校数据库/院校数据浏览器.html",
            "06-院校数据库/data/school_browser.json", "06-院校数据库/data/score_matrix.json",
            "robots.txt"]
    miss = [x for x in need if not os.path.isfile(os.path.join(OUT, x))]
    if miss:
        print("✗ 产物缺关键文件：%s" % ", ".join(miss))
        return 1
    print("✓ 关键入口与数据齐备；托管时 webDirectory 填 \"dist\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
