# -*- coding: utf-8 -*-
"""
inject_codebrick_pages.py — 把 10-录取分数统计（CodeBrick 聚合分位数）整合进两主网页。

A = 04-终极版择校/全国408_085410双非热度版_终极版_20260826.html
    - 注入 var CB + cbOf/cbCell/cbLi 助手
    - 总览主表新增「408分位(CB)」列（校名匹配；同校多个408项目按录取样本数加权合并，取最新年份）
    - 顺带修复：408均分/录取率两列表头排序索引错位（点408均分实际按备注排的 bug）
    - 「八、各校详情」卡片加 CodeBrick 分位 dim
    - SRCS 来源：修「川渝OCR deliverables/ 旧路径」→ 仓库路径；追加 CodeBrick 条目
B = 08-推荐器网页/kaoyan-recommender-full.html
    - DATA 加 CB；结果行院校格加小字「408分位 中位 [p25–p75] (年份,CodeBrick)」
    - 脚注说明分位口径

校名匹配：全角括号规范化 + 前缀容错。双非主线多数校不在 CodeBrick 96 校(全211+)池，
「—」属正常，页面提示已注明。

用法：仓库根目录执行  python 09-生成脚本/inject_codebrick_pages.py
幂等：检测到 `var CB=` / `"CB":` 已注入则跳过对应文件。
"""
import json
import os
import sys

PATH_A = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.html"
PATH_B = "08-推荐器网页/kaoyan-recommender-full.html"
DATA_DIR = "10-录取分数统计/data"


def norm(n):
    return (n or "").replace("(", "（").replace(")", "）")


def build_cb():
    idx = json.load(open(os.path.join(DATA_DIR, "schools_index.json"), encoding="utf-8"))
    cb = {}
    for it in idx:
        p = os.path.join(DATA_DIR, "schools", f"{it['id']}.json")
        if not os.path.exists(p):
            continue
        s = json.load(open(p, encoding="utf-8"))
        cands = []  # (year, s408, enrolled, type, retest)
        for prog in s.get("programs", []):
            for yo in prog.get("stats", {}).get("years", []):
                s408 = next((sub for sub in yo.get("subjects", [])
                             if sub.get("key") == "s408" and sub.get("quantilesAvailable")), None)
                if s408:
                    ec = yo.get("enrolledCount") or s408.get("count") or 0
                    cands.append((yo["year"], s408, ec, yo.get("exam408Type"), yo.get("retestCount") or 0))
        if not cands:
            continue
        y = max(c[0] for c in cands)
        sel = [c for c in cands if c[0] == y]

        def wavg(key):
            acc = tw = 0
            for _, sub, ec, _t, _r in sel:
                v = sub.get(key)
                if v is None or not ec:
                    continue
                acc += v * ec
                tw += ec
            return round(acc / tw) if tw else None

        mins = [c[1].get("min") for c in sel if c[1].get("min") is not None]
        maxs = [c[1].get("max") for c in sel if c[1].get("max") is not None]
        types = sorted({c[3] for c in sel if c[3]})
        rec = {"y": y, "med": wavg("median"), "p25": wavg("p25"), "p75": wavg("p75"),
               "lo": int(min(mins)) if mins else None, "hi": int(max(maxs)) if maxs else None,
               "ad": sum(c[2] for c in sel), "rc": sum(c[4] for c in sel),
               "np": len(sel), "types": "/".join(types) if types else "408"}
        if rec["med"] is None:
            continue
        cb[norm(s["name"])] = rec
    return cb


CB_JS_TMPL = """// ===== CodeBrick 408 分位（来源：10-录取分数统计，各校最新年份的全部408项目按录取样本数加权合并）=====
var CB=__CB__;
function cbNorm(n){return (n||"").replace(/\\(/g,"（").replace(/\\)/g,"）");}
function cbOf(d){
  if(typeof d==="string")d={n:d};
  var n=cbNorm(d.n);var r=CB[n]||CB[d.n];if(r)return r;
  for(var k in CB){if(n&&(k.indexOf(n)===0||n.indexOf(k)===0))return CB[k];}
  return null;
}
function cbCell(d){
  var q=cbOf(d);
  if(!q)return '<td class="num"><span class="na">—</span></td>';
  var t=q.y+"年408分位（CodeBrick聚合：408项目×"+q.np+"，录取样本n≈"+q.ad+"，复试n≈"+q.rc+"，口径 "+(q.types||"408")+"）\\n中位 "+q.med+"，p25–p75 "+q.p25+"–"+q.p75+"，全距 "+q.lo+"–"+q.hi;
  return '<td class="num" title="'+t+'">'+q.med+' <span style="font-size:11px;color:var(--muted)">['+q.p25+"–"+q.p75+"]</span></td>";
}
function cbLi(q){
  if(!q)return "";
  return "<li>"+q.y+"年 408 分位（CodeBrick，"+q.np+"个408项目，录取n≈"+q.ad+"）：中位 <b>"+q.med+"</b> · p25–p75 "+q.p25+"–"+q.p75+" · 全距 "+q.lo+"–"+q.hi+(q.types?" · 口径 "+q.types:"")+"</li>";
}"""


def replace_once(src, old, new, tag):
    cnt = src.count(old)
    if cnt != 1:
        raise AssertionError(f"[{tag}] 锚点出现 {cnt} 次（应为1）：{old[:60]!r}")
    return src.replace(old, new)


def main():
    cb = build_cb()
    print(f"CB 构建：{len(cb)} 校（CodeBrick 96 校索引）")
    cb_json = json.dumps(cb, ensure_ascii=False, separators=(",", ":"))
    print(f"CB JSON {len(cb_json)/1024:.1f} KB")

    # ---- 与 A 校名匹配预览 ----
    A = open(PATH_A, encoding="utf-8").read()
    a_names = set()
    for line in A.split("\n"):
        s = line.strip()
        for pre in ('{"n": "', 'var S=[{"n": "', 'var C=[{"n": "'):
            if s.startswith(pre):
                a_names.add(norm(s[len(pre):s.index('", "', len(pre))]))
                break
    hit = sorted(n for n in a_names if n in cb)
    print(f"A 校名 ∩ CB = {len(hit)} 校精确命中；示例：{hit[:6]}")

    # ---------- A ----------
    if "var CB=" in A:
        print("A 已注入 CB，跳过")
    else:
        a = A
        # 1. var CB + 助手：插在 C 数组尾、K 映射头之间
        a = replace_once(a, "];\n// ===== 初试科目映射",
                         "];\n" + CB_JS_TMPL.replace("__CB__", cb_json) + "\n// ===== 初试科目映射", "A-CB")
        # 2. OV_COLS 新列（插到 王道考情 与 备注 之间）
        a = replace_once(a, '["王道考情","#",26],\n  ["备注","#",23]',
                         '["王道考情","#",26],["408分位(CB)","num",27],\n  ["备注","#",23]', "A-OVCOLS")
        # 3. ovRow 单元格
        a = replace_once(a, "    wdCell(d)+\n    '<td class=\"score-cell\">'",
                         "    wdCell(d)+\n    cbCell(d)+\n    '<td class=\"score-cell\">'", "A-OVROW")
        # 4. 排序：修 24/25 错位（实际位置 23=408均分、24=录取率）+ 新增 26=CB中位数
        a = replace_once(a, "    if(ov.sort===24)return d.nn&&d.nn.a408!=null?d.nn.a408:-9999;\n    if(ov.sort===25)return d.nn&&d.nn.lr!=null?d.nn.lr:-9999;",
                         "    if(ov.sort===23)return d.nn&&d.nn.a408!=null?d.nn.a408:-9999;\n    if(ov.sort===24)return d.nn&&d.nn.lr!=null?d.nn.lr:-9999;\n    if(ov.sort===26){var _q=cbOf(d);return _q?_q.med:-9999;}", "A-SORT")
        # 5. 详情卡 dim
        a = replace_once(a, "    dcVerdict(main)+",
                         "    (cbOf(main)?'<div class=\"dim\"><div class=\"dt\">CodeBrick 408 分位</div><ul>'+cbLi(cbOf(main))+\"</ul></div>\":\"\")+\n    dcVerdict(main)+", "A-DCCARD")
        # 6. 主表 hint 注明 CB 口径
        a = replace_once(a, "可按大区/层次/AI 方向/线差筛选排序</span>",
                         "可按大区/层次/AI 方向/线差筛选排序 · 「408分位(CB)」为 CodeBrick 聚合录取分位数（211/985 参照池，双非多数无此项属正常）</span>", "A-HINT")
        # 7. SRCS：旧 deliverables 路径 → 仓库路径；追加 CodeBrick
        a = replace_once(a, '["川渝王道考情OCR提取(2026-08-25,30校184行)","deliverables/20260825-川渝王道考情提取/"]',
                         '["川渝王道考情OCR提取(2026-08-25,30校184行)","07-考情资料/川渝王道考情提取/"],\n["CodeBrick考研录取分数统计(96校聚合分位数,2026-09-06抓取)","https://www.codebrick.tech/practice/school-admit"]', "A-SRCS")
        open(PATH_A, "w", encoding="utf-8", newline="\n").write(a)
        print("A 注入完成 ✓")

    # ---------- B ----------
    B = open(PATH_B, encoding="utf-8").read()
    if '"CB":' in B:
        print("B 已注入 CB，跳过")
    else:
        b = B
        # 1. DATA 加 CB
        lines = b.split("\n")
        di = next(i for i, l in enumerate(lines) if l.startswith("var DATA="))
        data = json.loads(lines[di][len("var DATA="):].rstrip(";"))
        data["CB"] = cb
        lines[di] = "var DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
        b = "\n".join(lines)
        # 2. 助手函数（放在 esc 后）
        b = replace_once(b, 'function esc(s){return String(s==null?"—":s);}',
                         'function esc(s){return String(s==null?"—":s);}\n'
                         'function cbOf(d){var m=DATA.CB||{};var n=(d.n||"").replace(/\\(/g,"（").replace(/\\)/g,"）");return m[n]||m[d.n]||null;}', "B-CBOF")
        # 3. 结果行院校格加小字
        b = replace_once(b, '\'<td class="school">\'+esc(d.n)+(d._grp==="C"?\' <span class="tier">对照</span>\':"")+\'</td>\'+',
                         '\'<td class="school">\'+esc(d.n)+\'<br><span style="font-size:11px;color:#888">\'+(function(){var q=cbOf(d);return q?("408分位 "+q.med+" ["+q.p25+"–"+q.p75+"] ("+q.y+"·CodeBrick)"):("408分位 —");})()+\'</span>\'+(d._grp==="C"?\' <span class="tier">对照</span>\':"")+\'</td>\'+', "B-SCHOOL")
        # 4. 脚注口径说明
        b = replace_once(b, "线差 = 我的预估分 − 该校 2026 复试线。",
                         "408 分位：CodeBrick 聚合录取分数统计（仓库 10-录取分数统计），同校多个 408 项目按录取样本加权合并、取最新年份；双非多数院校不在该参照池，显示「—」属正常。线差 = 我的预估分 − 该校 2026 复试线。", "B-FOOT")
        open(PATH_B, "w", encoding="utf-8", newline="\n").write(b)
        print("B 注入完成 ✓")

    # ---- 校验 A/B S、C 记录仍一致 ----
    a2 = open(PATH_A, encoding="utf-8").read()
    A_S = []
    for line in a2.split("\n"):
        s = line.strip()
        if s.startswith('{"n":'):
            A_S.append(json.loads(s.rstrip(",")))
        elif s.startswith('var S=[{"n":') or s.startswith('var C=[{"n":'):
            A_S.append(json.loads(s[s.index("[") + 1:].rstrip(",")))
    b2 = open(PATH_B, encoding="utf-8").read()
    dl = next(l for l in b2.split("\n") if l.startswith("var DATA="))
    d2 = json.loads(dl[len("var DATA="):].rstrip(";"))
    key = lambda r: norm(r["n"] + "|" + str(r.get("c")) + "|" + str(r.get("d")))
    mA = {key(r): r for r in A_S}
    mB = {key(r): r for r in d2["S"] + d2["C"]}
    assert len(mA) == len(mB) == 186, f"记录数 {len(mA)}/{len(mB)}"
    drift = [k for k in mA if json.dumps(mA[k], sort_keys=True, ensure_ascii=False) != json.dumps(mB[k], sort_keys=True, ensure_ascii=False)]
    assert not drift, f"A/B 漂移: {drift[:3]}"
    print("A/B S+C 186 条语义一致 ✓")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
