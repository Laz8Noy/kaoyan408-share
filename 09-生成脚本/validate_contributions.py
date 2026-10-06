# -*- coding: utf-8 -*-
"""
validate_contributions.py — 校验外来投稿 JSON（06-院校数据库/contributions/*.json）。

用法：仓库根目录执行  python 09-生成脚本/validate_contributions.py
退出码：0=全部合法（或无投稿文件）；1=存在不合法项。

投稿格式（contribution-v1）见根 README「🤝 数据征集」节。要点：
  - 顶层：schema / school / unitCode? / isNewSchool? / collectedAt / collector? / entries[] / notes?
  - entries[]: college? / major? / subjectClass? / fields[]（非空）
  - fields[] : field（白名单内）/ value（非空）/ basis? / source{title?, url, tier, date}
  - field 白名单 = 06 正本全部 units 对象键的并集（动态生成，随正本演进）
  - tier ∈ T1~T4（分级定义见 docs/数据源与冲突裁定.md）
"""
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRIB_DIR = os.path.join(ROOT, "06-院校数据库", "contributions")
SCHOOLS_DIR = os.path.join(ROOT, "06-院校数据库", "data", "schools")

SCHEMA = "contribution-v1"
TIERS = {"T1", "T2", "T3", "T4"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://\S+$")
NUMERIC_FIELDS = {
    "line2026", "lineUltimate2026", "plan2026", "admitCnt", "admitAvg",
    "admitMin", "admitMax", "retestCnt", "nn408avg", "nnRate",
    "fill", "heatNet", "heatComp", "wdCount",
}
BAD_VALUE = {"", "—", "-", "--", "?", "？", "TBD", "todo", "TODO"}


def load_library():
    """返回 (字段白名单, 校名集合)。白名单 = 所有 units 对象键的并集。"""
    whitelist, names = set(), set()
    for fn in os.listdir(SCHOOLS_DIR):
        if not fn.endswith(".json"):
            continue
        data = json.load(io.open(os.path.join(SCHOOLS_DIR, fn), encoding="utf-8"))
        names.add(data.get("name"))
        for unit in data.get("units") or []:
            whitelist.update(unit.keys())
    return whitelist, names


def validate_file(path, whitelist, names, errs):
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    try:
        data = json.load(io.open(path, encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        errs.append("%s: JSON 解析失败 %s" % (rel, ex))
        return 0
    n_fields = 0

    if data.get("schema") != SCHEMA:
        errs.append("%s: schema 必须为 %r，现为 %r" % (rel, SCHEMA, data.get("schema")))
    school = data.get("school")
    if not isinstance(school, str) or not school.strip():
        errs.append("%s: school 必填（非空字符串）" % rel)
    else:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem != school.strip():
            errs.append("%s: 文件名（%s）须与 school（%s）一致" % (rel, stem, school.strip()))
        if school not in names and not data.get("isNewSchool"):
            errs.append("%s: 校名 %r 不在 06 正本；库外新校须置 isNewSchool=true" % (rel, school))
    if data.get("isNewSchool") not in (None, True, False):
        errs.append("%s: isNewSchool 须为布尔" % rel)
    if not DATE_RE.match(str(data.get("collectedAt", ""))):
        errs.append("%s: collectedAt 缺失或格式非 YYYY-MM-DD" % rel)
    coll = data.get("collector")
    if coll is not None and not (isinstance(coll, dict) and isinstance(coll.get("name"), str) and coll["name"].strip()):
        errs.append("%s: collector 须为 {name: 非空字符串}" % rel)
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errs.append("%s: entries 必须为非空数组" % rel)
        return 0

    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            errs.append("%s: entries[%d] 须为对象" % (rel, i))
            continue
        scope = "entries[%d](%s/%s)" % (
            i, entry.get("college", "?"), entry.get("major", "?"))
        for opt in ("college", "major", "subjectClass"):
            if opt in entry and not isinstance(entry[opt], str):
                errs.append("%s: %s.%s 须为字符串" % (rel, scope, opt))
        fields = entry.get("fields")
        if not isinstance(fields, list) or not fields:
            errs.append("%s: %s.fields 必须为非空数组" % (rel, scope))
            continue
        seen = set()
        for j, item in enumerate(fields, 1):
            where = "%s %s.fields[%d]" % (rel, scope, j)
            if not isinstance(item, dict):
                errs.append("%s: 须为对象" % where)
                continue
            fname = item.get("field")
            if fname not in whitelist:
                errs.append("%s: field %r 不在 06 正本 units 字段白名单" % (where, fname))
            if fname in seen:
                errs.append("%s: field %r 在同一条目内重复" % (where, fname))
            seen.add(fname)
            value = item.get("value", None)
            if value is None or (isinstance(value, str) and value.strip() in BAD_VALUE):
                errs.append("%s: value 为空/占位符（空值不收，宁缺勿滥）" % where)
            elif fname in NUMERIC_FIELDS and not re.search(r"\d", str(value)):
                errs.append("%s: 数值字段 %r 的 value=%r 不含数字" % (where, fname, value))
            src = item.get("source")
            if not isinstance(src, dict):
                errs.append("%s: 缺 source 对象" % where)
                continue
            if not URL_RE.match(str(src.get("url", ""))):
                errs.append("%s: source.url 缺失或非 http(s) 直链" % where)
            if src.get("tier") not in TIERS:
                errs.append("%s: source.tier 须为 T1~T4，现为 %r" % (where, src.get("tier")))
            if not DATE_RE.match(str(src.get("date", ""))):
                errs.append("%s: source.date 缺失或格式非 YYYY-MM-DD" % where)
            n_fields += 1
    return n_fields


def main():
    if not os.path.isdir(CONTRIB_DIR):
        print("[跳过] 无 06-院校数据库/contributions/ 目录（尚无投稿通道内容）")
        return 0
    files = [f for f in os.listdir(CONTRIB_DIR)
             if f.endswith(".json") and not f.startswith(".")]
    if not files:
        print("[跳过] contributions/ 无投稿 JSON")
        return 0
    whitelist, names = load_library()
    if not whitelist:
        print("[FAIL] 06 正本为空，无法构建字段白名单")
        return 1
    errs, total = [], 0
    for fn in sorted(files):
        n = validate_file(os.path.join(CONTRIB_DIR, fn), whitelist, names, errs)
        total += n
        tag = "[FAIL]" if any(e.startswith("06-院校数据库/contributions/%s" % fn) for e in errs) else "[ok]"
        print("%s %s（%d 个字段记录）" % (tag, fn, n))
    for e in errs:
        print("  - " + e)
    print("校验 %d 个投稿文件 / %d 条字段记录：%s"
          % (len(files), total, "不合法 %d 处" % len(errs) if errs else "全部合法"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
