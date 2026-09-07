# -*- coding: utf-8 -*-
"""
apply_verify_0903_pages.py — 把 09-03 复核修正（06-院校数据库/conflicts_registry.json）
同步进两个主网页：
  A = 04-终极版择校/全国408_085410双非热度版_终极版_20260826.html
  B = 08-推荐器网页/kaoyan-recommender-full.html

背景：两页内嵌 S/C 数组是 08-26 快照，09-03 对 12 条冲突逐条复核后修正只落进了
06-院校数据库 JSON，未回流页面。本脚本以显式变更清单 + assert 锚点做"原地定点"修改
（严禁重跑 integrate_three_sources.py，会丢 09-06 人工扩容）。

用法：在仓库根目录执行  python 09-生成脚本/apply_verify_0903_pages.py
幂等：已应用过的变更（旧值不匹配且新值已在）会计为 skipped，可安全重跑。
"""
import json
import sys

PATH_A = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.html"
PATH_B = "08-推荐器网页/kaoyan-recommender-full.html"

# ---- S/C 记录级变更：match=(n, c, d)；set=直接置值；note_set=整句替换；note_add=追加 ----
REC_CHANGES = [
    # 1/2. 长春理工大学：N诺 ad=322 为均分类错位值，官方实际录取 42（registry: 长春理工）
    {"m": ("长春理工大学", "人工智能学院", "01计算机类方向"),
     "set": {"nn.ad": None},
     "note_add": "；N诺『录取322』为均分类错位值勿采信，官方2026拟录取42人（01计38+02自4）"},
    {"m": ("长春理工大学", "人工智能学院", "02自动化类方向"),
     "set": {"nn.ad": None},
     "note_add": "；两方向合计录取42人（官方核实）"},
    # 3. 山东科技大学：科目=英二数二+813电路（非408）；N诺300与官方不符
    {"m": ("山东科技大学", "计算机科学与工程学院", "不区分研究方向"),
     "note_set": ("除自划专业外执行A区国家线",
                  "085410=英二数二+813电路（官方目录，非408）；执行A区国家线264，N诺300与官方不符")},
    # 4. 广东工业大学·自动化学院：809非408，264=国家线；301是调剂要求分（registry: 广工）
    {"m": ("广东工业大学", "自动化学院", "不区分研究方向"),
     "set": {"l": 264},
     "note_set": ("自动化学院调剂通知要求初试总分≥301",
                  "自动化学院085410考英二数二+809信号与系统（非408），线264为A区国家线；301系调剂要求分非复试线")},
    # 5. 广东工业大学·"另一招生学院"→确认为计算机学院 337/22408/拟招80（c 支持新旧值以便幂等重跑）
    {"m": ("广东工业大学", ("另一招生学院", "计算机学院"), "不区分研究方向"),
     "set": {"c": "计算机学院", "fc": "一志愿为主", "src": "官方", "plan": "80"},
     "note_set": ("2026两学院分别301/337；337学院归属待核",
                  "计算机学院085410自划线337，22408（英二数二408，官方目录拟招80）")},
    # 6-8. 深圳大学三行：官方目录核实全部学院085410=11408（registry: 深大）
    {"m": ("深圳大学", "人工智能学院", "不区分研究方向"),
     "note_set": ("人工智能学院复试线335",
                  "AI学院335；深大全部学院085410均英一数一408(11408)官方目录核实，22408考生请排除；另有计软332未单列")},
    {"m": ("深圳大学", "光明实验室", "不区分研究方向"),
     "note_set": ("；初试科目同AI学院待核", "；初试科目已核实英一数一408(11408)")},
    {"m": ("深圳大学", "大湾区国际创新学院", "人工智能（管理）"),
     "note_set": ("；初试科目待核", "；已核实英一数一408(11408)")},
    # 9. 天津工业大学：l 264→332（AI学院自划线，官方复试办法）
    {"m": ("天津工业大学", "人工智能学院", "不区分研究方向"),
     "set": {"l": 332},
     "note_set": ("2025线260、2026按A区国家线264",
                  "2025线260、2026 AI学院自划线332（原264系国家线误标，09-03按官方复试办法修正）")},
    # 10. 南京信息工程大学：2027 官宣 408→811信号与系统
    {"m": ("南京信息工程大学", "人工智能学院", "电子信息-人工智能"),
     "note_add": "；2027官宣改考811信号与系统（反向改考，勿按408复习）"},
    # 11-12. 成都信息工程大学两行：2027 官宣数一→数二 = 真22408
    {"m": ("成都信息工程大学", "计算机学院", "不区分研究方向"),
     "note_add": "；2027官宣085410数一301→数二302（改后真22408）"},
    {"m": ("成都信息工程大学", "人工智能学院", "不区分研究方向"),
     "note_add": "；2027官宣数一→数二（改后真22408；2026仍数一+408）"},
]


def set_nested(rec, path, val):
    keys = path.split(".")
    obj = rec
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = val


def get_nested(rec, path, default="__MISS__"):
    obj = rec
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return default
        obj = obj[k]
    return obj


def apply_rec_changes(rec, log, tag):
    """对一条 S/C 记录应用匹配到的变更；返回是否改动。"""
    changed = False
    for ch in REC_CHANGES:
        if not _key_match(rec, ch["m"]):
            continue
        n, c, d = ch["m"]
        c_disp = c if isinstance(c, str) else c[0]
        # set 字段
        for path, new in ch.get("set", {}).items():
            cur = get_nested(rec, path)
            if cur == new:
                log.append(f"  skip [{tag}] {n}|{c} {path} 已是 {new!r}")
                continue
            set_nested(rec, path, new)
            changed = True
            log.append(f"  set  [{tag}] {n}|{c} {path}: {cur!r} -> {new!r}")
        # note 整句替换 / 追加
        cur_note = rec.get("note", "")
        if "note_set" in ch:
            old, new = ch["note_set"]
            if old in cur_note:
                rec["note"] = cur_note.replace(old, new)
                changed = True
                log.append(f"  note [{tag}] {n}|{c} 替换片段")
            elif new.split("；")[-1] in cur_note or new in cur_note:
                log.append(f"  skip [{tag}] {n}|{c} note 已是新值")
            else:
                raise AssertionError(f"[{tag}] {n}|{c} note_set 锚点未找到：{cur_note[:80]}")
        if "note_add" in ch:
            add = ch["note_add"]
            if add in rec.get("note", ""):
                log.append(f"  skip [{tag}] {n}|{c} note_add 已存在")
            else:
                rec["note"] = rec.get("note", "") + add
                changed = True
                log.append(f"  note [{tag}] {n}|{c} 追加")
    return changed


# ---- A 页面文本级变更（静态表 / K 科目表 / 旧文案）----
TEXT_CHANGES_A = [
    # 南信大 817→811（官方2026-06-18通知，registry: 南信大）
    ("817信号与系统", "811信号与系统"),
    ("22408(2026)/817(2027)", "22408(2026)/811(2027)"),
    ("⚠️2027退回817自命题", "⚠️2027改考811自命题（官方通知2026-06）"),
    ("<td>811信号与系统</td><td>2027</td><td>新东方2026-07</td>",
     "<td>811信号与系统</td><td>2027</td><td>官方通知2026-06</td>"),
    # 旧文案与实际条数不符
    ("主体 67 行", "主体 148 条（141 校）"),
    ("可展开全部 60 所", "可展开全部 141 校"),
    # K 科目表修正
    ('"深圳大学": "待确认",', '"深圳大学": "11408",'),
    ('"广东工业大学": "待确认",',
     '"广东工业大学": "待确认",\n"广东工业大学|自动化学院": "非408",\n"广东工业大学|计算机学院": "22408",',
     '"广东工业大学|自动化学院"'),  # 旧串是新串子串，需 skip_if 防重复插入
]


_T_KEYS = frozenset(c["m"] for c in REC_CHANGES)


def _key_match(rec, m):
    n, c, d = m
    if rec.get("n") != n or rec.get("d") != d:
        return False
    return rec.get("c") in (c if isinstance(c, tuple) else (c,))


def rec_matches_target(rec):
    return any(_key_match(rec, m) for m in (c["m"] for c in REC_CHANGES))


def main():
    log = []
    hits = {"A": 0, "B": 0}

    # ---------- A：S 行（每行一条 JSON 记录，带 ", " 分隔风格） ----------
    with open(PATH_A, encoding="utf-8") as f:
        a_src = f.read()
    a_lines = a_src.split("\n")
    n_records = 0
    for i, line in enumerate(a_lines):
        s = line.strip()
        if not s.startswith('{"n":'):
            continue
        body = s.rstrip(",")
        try:
            rec = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not rec_matches_target(rec):
            continue
        n_records += 1
        if apply_rec_changes(rec, log, "A-S"):
            a_lines[i] = json.dumps(rec, ensure_ascii=False) + ("," if s.endswith(",") else "")
    if n_records != 12:
        raise AssertionError(f"A 页应匹配 12 条目标 S 记录，实际 {n_records}")
    a_new = "\n".join(a_lines)
    for entry in TEXT_CHANGES_A:
        old, new = entry[0], entry[1]
        skip_if = entry[2] if len(entry) > 2 else None
        if (skip_if or new.split("（")[0]) in a_new:
            log.append(f"  skip [A-文本] {old[:30]} 已是新值")
            continue
        cnt = a_new.count(old)
        if cnt != 1:
            raise AssertionError(f"A 文本锚点 {old[:40]!r} 出现 {cnt} 次（应为1）")
        a_new = a_new.replace(old, new)
    with open(PATH_A, "w", encoding="utf-8", newline="\n") as f:
        f.write(a_new)

    # ---------- B：var DATA 单行紧凑 JSON ----------
    with open(PATH_B, encoding="utf-8") as f:
        b_src = f.read()
    b_lines = b_src.split("\n")
    di = None
    for i, line in enumerate(b_lines):
        if line.startswith("var DATA="):
            di = i
            break
    assert di is not None, "B 未找到 var DATA 行"
    data = json.loads(b_lines[di][len("var DATA="):].rstrip(";"))
    n_b = 0
    for arr in ("S", "C"):
        for rec in data[arr]:
            if not rec_matches_target(rec):
                continue
            n_b += 1
            apply_rec_changes(rec, log, f"B-{arr}")
    assert n_b == 12, f"B 页应匹配 12 条目标记录，实际 {n_b}"
    b_lines[di] = "var DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(PATH_B, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(b_lines))

    # ---------- 校验 A/B S+C 数组语义一致 ----------
    a_after = open(PATH_A, encoding="utf-8").read().split("\n")

    def a_records(src_lines):
        recs = []
        for l in src_lines:
            s = l.strip()
            if s.startswith('{"n":'):
                recs.append(json.loads(s.rstrip(",")))
            elif s.startswith('var S=[{"n":') or s.startswith('var C=[{"n":'):
                recs.append(json.loads(s[s.index("[") + 1:].rstrip(",")))
        return recs

    A_S = a_records(a_after)
    B_S = data["S"] + data["C"]
    key = lambda r: (r["n"], r.get("c"), r.get("d"))
    mapA, mapB = {key(r): r for r in A_S}, {key(r): r for r in B_S}
    assert len(A_S) == len(mapA) == 186 and len(B_S) == 186, f"记录数异常 A={len(A_S)} B={len(B_S)}"
    assert set(mapA) == set(mapB), "A/B S+C 记录键集合不一致"
    diff = [k for k in mapA if json.dumps(mapA[k], sort_keys=True, ensure_ascii=False)
            != json.dumps(mapB[k], sort_keys=True, ensure_ascii=False)]
    assert not diff, f"A/B 记录内容漂移: {diff[:3]}"

    print(f"apply_verify_0903：A 改 {n_records} 条S记录+{len(TEXT_CHANGES_A)} 处文本；B 改 {n_b} 条；A/B S 数组语义一致 ✓")
    for l in log:
        print(l)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
