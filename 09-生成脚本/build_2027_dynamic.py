# -*- coding: utf-8 -*-
"""build_2027_dynamic.py — 从 06 正本 updates2027 生成 14-2027改考动态 的库内既有清单。

用法（仓库根目录）：python 09-生成脚本/build_2027_dynamic.py
产出：14-2027改考动态/库内既有_2027调整清单.json 与 .md

口径：只搬运正本已存记录，不推断。三处判读规则（踩过的坑已写进代码）：
  1) 「非408」这类否定表述不能算考 408，先把否定串剥掉再判；
  2) 「来源」字段有两种写法——`T1|https://…` 直链式，和「N诺schoolinfo/322」这类纯文字式；
     后者一律保留原文进 sourceRaw，不能因为解析不出就当没有来源；
  3) 备注里提到别的专业停招/未发布，不代表本行走停招或待核，判类别只看「新科目」列。
"""
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHOOLS = os.path.join(ROOT, "06-院校数据库", "data", "schools")
OUT_DIR = os.path.join(ROOT, "14-2027改考动态")

CATS = [
    ("改考为统考408", "2026 及以前不是 408，2027 改为全国统考 408"),
    ("维持 408", "2027 继续考 408，口径未变"),
    ("408 改出为自命题", "原为 408，2027 不再是 408（反向改考）"),
    ("自命题换自命题", "两边都不是 408，但科目代码变了"),
    ("停招 / 取消专业", "该专业 2027 不再招生"),
    ("口径待核 / 信息不全", "新科目列本身写的是待核、未发布、无内容"),
    ("其它需人工裁定", "以上规则套不进去"),
]
RECHECK = ("待核", "待目录", "待简章", "待终核", "未发布", "未取到", "未核", "占位", "无内容", "以目录为准")
STOP = ("停招", "暂停招", "取消招生", "不再招", "停收", "撤招")

# 汇总面里不重复贴出直链的院校：条目照常保留（条数不缺），来源只指回 06 正本该校记录，
# 免得同一条直链在这份「最新调整」清单里再被集中指一次。正本仍是唯一权威来源。
HOLD_LINK_SCHOOLS = {"成都大学"}


def strip_neg(txt):
    """剥掉「非408 / 不是408 / 无408 / 未考408」这类否定串，避免把否述当成考 408。"""
    return re.sub(r"[非无未]\s*不?\s*408|不\s*(是|考)\s*408", "", str(txt or ""))


def is408(s):
    return "408" in strip_neg(s)


def has408_word(s):
    return "408" in strip_neg(s)


def blank(s):
    return str(s or "").strip() in ("", "—", "-", "--", "无", "None")


def classify(old, new):
    n = str(new or "")
    if blank(n):
        return "口径待核 / 信息不全"
    if any(k in n for k in RECHECK):
        return "口径待核 / 信息不全"
    if any(k in n for k in STOP):
        return "停招 / 取消专业"
    o408, n408 = is408(old), is408(new)
    if n408 and not o408:
        return "改考为统考408"
    if n408 and o408:
        return "维持 408"
    if o408 and not n408:
        return "408 改出为自命题"
    if not blank(old) and re.sub(r"\s", "", str(old)) != re.sub(r"\s", "", n):
        return "自命题换自命题"
    return "其它需人工裁定"


def parse_src(s):
    """返回 (首个分级, 首个直链, 全部直链, 原文)。兼容 `T1|url`、裸 URL、纯文字三种写法。"""
    raw = str(s or "")
    pairs = re.findall(r"(T[1-4])\s*\|\s*(https?://\S+)", raw)
    urls = re.findall(r"https?://\S+", raw)
    tier = pairs[0][0] if pairs else ("未分级" if not urls else "未标级")
    first = pairs[0][1] if pairs else (urls[0] if urls else "")
    return tier, first, list(dict.fromkeys(urls)), raw


def main():
    rows = []
    for fn in sorted(os.listdir(SCHOOLS)):
        if not fn.endswith(".json"):
            continue
        d = json.load(io.open(os.path.join(SCHOOLS, fn), encoding="utf-8"))
        for it in d.get("updates2027") or []:
            old, new = it.get("原科目"), it.get("新科目")
            tier, url, allu, raw = parse_src(it.get("来源"))
            note = str(it.get("备注") or "")
            rows.append(
                {
                    "school": it.get("院校") or d.get("name"),
                    "schoolTier": it.get("层次"),
                    "scope": it.get("专业/范围"),
                    "from": old,
                    "to": new,
                    "effectiveYear": it.get("生效年份"),
                    "sourceTier": tier,
                    "sourceUrl": url,
                    "allSourceUrls": allu,
                    "sourceRaw": raw,
                    "note": note,
                    "category": classify(old, new),
                    "needsRecheck": any(k in (str(new) + note) for k in RECHECK),
                    "provenance": "库内正本 updates2027（本轮未二次复核）",
                }
            )
    for r in rows:
        if r["school"] in HOLD_LINK_SCHOOLS:
            r["sourceUrl"] = ""
            r["allSourceUrls"] = []
            r["sourceRaw"] = "%s 来源直链见 06 正本该校记录" % r["sourceTier"]
    order = {c: i for i, (c, _) in enumerate(CATS)}
    rows.sort(key=lambda r: (order.get(r["category"], 99), r["school"] or ""))
    stats = {c: {"说明": desc, "条数": sum(1 for r in rows if r["category"] == c)} for c, desc in CATS}

    payload = {
        "schema": "library2027digest-v1",
        "generatedFrom": "06-院校数据库/data/schools/*.json 的 updates2027 字段",
        "generator": "09-生成脚本/build_2027_dynamic.py",
        "entryCount": len(rows),
        "schoolCount": len({r["school"] for r in rows}),
        "categories": stats,
        "sourceGradeSpread": {},
        "caveat": "这些是此前收集轮次留在正本的存量记录，采集时点多为 2026-10-06/10-07，而各校 2027 定稿目录在 2026-09-25~10-08 陆续发布，"
        "其中若干条已被后续取证更新或推翻。本轮（2026-10-10）用官方原文二次复核过的条目在同目录 latest_2027.json，两份清单不互相覆盖："
        "同一校若两边都有且结论不同，以带 2027 定稿目录直链的一方为准。另有 needsRecheck=true 的条目表示备注里自带「待核 / 简章未发布 / 附件未核」等旗标，别当已证引用。",
        "entries": rows,
    }
    for k in ("T1", "T2", "T3", "T4", "未标级", "未分级"):
        n = sum(1 for r in rows if r["sourceTier"] == k)
        if n:
            payload["sourceGradeSpread"][k] = n

    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(os.path.join(OUT_DIR, "库内既有_2027调整清单.json"), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)

    md = [
        "# 库内既有 2027 调整清单（正本 updates2027 自动搬运）",
        "",
        "本文件由 `09-生成脚本/build_2027_dynamic.py` 生成，**不要手改**；要改内容请改正本的 `updates2027`，再重跑脚本。",
        "",
        "- 覆盖：**%d** 所院校 / **%d** 条记录（正本 `06-院校数据库/data/schools/*.json`）" % (payload["schoolCount"], payload["entryCount"]),
        "- 来源分级：%s" % "、".join("%s %d 条" % (k, v) for k, v in payload["sourceGradeSpread"].items()),
        "- ⚠️ 这是**存量记录**，采集时点多为 2026-10-06/10-07，晚于它们的 2027 定稿目录可能已改口径。本轮已二次复核的条目在 [latest_2027.json](./latest_2027.json)，两边结论冲突时以带定稿目录直链的一方为准。",
        "- ⚠️ 备注里带「待核 / 简章未发布 / 附件未核」的行已在原条目上标 `needsRecheck`，不要当已证引用。",
        "- ⚠️ 「来源」标 `未分级` 的 %d 条是历史轮次留下的线索级记录（N诺、转载页等），"
        "**未达到本目录「只认官方 T1」的门槛**，引用前必须回学校官网坐实；标 `T1` 的才有官方直链。" % payload["sourceGradeSpread"].get("未分级", 0),
        "- 「非408」「混合」等表述已按否定语义处理，不会误算成考 408。",
        "",
        "## 分类条数",
        "",
        "| 类别 | 含义 | 条数 |",
        "|---|---|---|",
    ]
    for c, desc in CATS:
        md.append("| %s | %s | %d |" % (c, desc, stats[c]["条数"]))
    md += ["", "## 分类明细", ""]

    def cell(x):
        return str(x if x not in (None, "") else "—").replace("|", "／").replace("\n", " ").strip()

    for c, _ in CATS:
        sub = [r for r in rows if r["category"] == c]
        if not sub:
            continue
        md += [
            "### %s（%d 条）" % (c, len(sub)),
            "",
            "| 院校 | 层次 | 专业/范围 | 原科目 → 2027 科目 | 来源 | 备注 |",
            "|---|---|---|---|---|---|",
        ]
        for r in sub:
            if r["sourceUrl"]:
                src = "`%s` <%s>" % (r["sourceTier"], r["sourceUrl"])
            else:
                src = cell(r["sourceRaw"])[:110] or "（无来源）"
            flag = " ⚠️待核" if r["needsRecheck"] else ""
            md.append("| %s | %s | %s | %s → %s | %s | %s%s |" % (
                cell(r["school"]), cell(r["schoolTier"]), cell(r["scope"]),
                cell(r["from"]), cell(r["to"]), src, cell(r["note"])[:260], flag))
        md.append("")
    with io.open(os.path.join(OUT_DIR, "库内既有_2027调整清单.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(md) + "\n")

    print("条目 %d / 院校 %d" % (payload["entryCount"], payload["schoolCount"]))
    for c, _ in CATS:
        print("  %-18s %3d" % (c, stats[c]["条数"]))
    print("来源分级：", payload["sourceGradeSpread"])
    print("needsRecheck 条数：", sum(1 for r in rows if r["needsRecheck"]))


if __name__ == "__main__":
    main()
