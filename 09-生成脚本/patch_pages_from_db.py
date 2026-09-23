# -*- coding: utf-8 -*-
"""
patch_pages_from_db.py — 用仓库内已有数据补全 04/08 页面缺失字段（锚点外就地补值，幂等）

设计要点
  * 数据来源：仓库内**正本文件**（06/data/schools/*.json、yz408_catalog.json、dai408_scores.json）。
    统一库 kaoyan408.db 是这些文件的派生物，故此处直接读正本，避免与库重建互相干扰。
  * 只补空：**绝不覆盖页面里已有的非空值**（04-0826.html 是手工维护的真相源）。
  * 幂等：重复执行结果一致；每次改动前把原文件备份到 09-生成脚本/_bak/。
  * 不做假：无来源的字段（报录比 ratio、网络热度 net）一律不编造。

用法
  python 09-生成脚本/patch_pages_from_db.py            # 干跑，只报告将补什么
  python 09-生成脚本/patch_pages_from_db.py --apply    # 实际写入（先备份）
"""
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
D06 = os.path.join("06-院校数据库", "data")
HTML_04 = "04-终极版择校/全国408_085410双非热度版_终极版_20260826.html"
HTML_08 = "08-推荐器网页/kaoyan-recommender-full.html"
BAK = os.path.join("09-生成脚本", "_bak")
APPLY = "--apply" in sys.argv

NUM_RE = re.compile(r"\d+(?:\.\d+)?")
NUM_FIELDS = ["line2026", "plan2026", "retestCnt", "admitCnt",
              "admitMax", "admitMin", "admitAvg", "ratioRetest", "fill"]


def rd(p):
    return io.open(p, encoding="utf-8").read()


def wr(p, t):
    if not APPLY:
        return  # 干跑绝不落盘（此前版本这里漏了判断，导致干跑也写文件）
    os.makedirs(BAK, exist_ok=True)
    shutil.copy2(p, os.path.join(BAK, os.path.basename(p) + "." + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak"))
    io.open(p, "w", encoding="utf-8", newline="\n").write(t)


def firstnum(v):
    """从复合串里抽主值：'8(一志愿)+12调剂'→8.0；'约90(86+4专项)'→90.0；无数字→None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM_RE.search(str(v))
    return float(m.group(0)) if m else None


def as_int(v):
    f = firstnum(v)
    return None if f is None else int(f)


def lh_from(v):
    """06 的 linesByYear 是 {'2023': '318', ...} 字典；04 页 lh 是 3 元数组 [2023,2024,2025] —— 必须转换"""
    if isinstance(v, list):
        return v if any(x is not None for x in v) else None
    if isinstance(v, dict):
        arr = [as_int(v.get(str(y))) for y in (2023, 2024, 2025)]
        return arr if any(x is not None for x in arr) else None
    return None


def norm(s):
    return re.sub(r"[（()）\s·、\-]", "", str(s or ""))


def grab_raw(s, begin):
    """按括号配平抽出 var X= 后面的 JSON 原文（跳过字符串内的括号）"""
    a = s.index(begin) + len(begin)
    while s[a] in " \t\r\n":
        a += 1
    depth, instr, esc = 0, False, False
    for j in range(a, len(s)):
        ch = s[j]
        if instr:
            if esc:
                esc = False
            elif ch == chr(92):
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
                return a, j + 1
    raise ValueError("未闭合: " + begin)


# ---------------- 载入正本 ----------------
def load_schools06():
    """校名 → 字段最全的那个 unit"""
    out = {}
    d = os.path.join(D06, "schools")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        x = json.load(io.open(os.path.join(d, fn), encoding="utf-8"))
        units = x.get("units") or []
        if not units:
            continue
        best = max(units, key=lambda u: sum(1 for k in NUM_FIELDS if u.get(k) not in (None, "")))
        out[x["name"]] = best
    return out


def load_yz_plan():
    """校名 → 拟招 e26（085410 优先，其次其它 0854/0812）"""
    y = json.load(io.open(os.path.join(D06, "yz408_catalog.json"), encoding="utf-8"))
    pri, other = {}, {}
    for it in y["items"]:
        e = it.get("e26")
        if e is None:
            continue
        mc = str(it.get("mc") or "")
        if mc == "085410":
            pri.setdefault(it["s"], e)
        elif mc.startswith("0854") or mc.startswith("0812"):
            other.setdefault(it["s"], e)
    merged = dict(other)
    merged.update(pri)  # 085410 覆盖近专业
    return merged


def load_dai():
    """校名 → 2026 年记录（085410 优先，其次 0854/0812）"""
    d = json.load(io.open(os.path.join(D06, "dai408_scores.json"), encoding="utf-8"))
    pri, other = {}, {}
    for it in d["items"]:
        if it.get("y") != 2026:
            continue
        dc = str(it.get("dc") or "")
        if dc == "085410":
            pri.setdefault(it["s"], it)
        elif dc.startswith("0854") or dc.startswith("0812"):
            other.setdefault(it["s"], it)
    return pri, other


S06 = load_schools06()
YZ = load_yz_plan()
DAI_PRI, DAI_OTH = load_dai()
N06 = {}
for k in S06:
    N06.setdefault(norm(k), k)


def norm_key(name, table):
    """在 dict 里按精确→规范化顺序找键，返回键名或 None"""
    if name in table:
        return name
    nn = norm(name)
    for k in table:
        if norm(k) == nn:
            return k
    return None


stats = {}


def bump(k):
    stats[k] = stats.get(k, 0) + 1


def lookup_unit(name):
    return S06.get(name) or S06.get(N06.get(norm(name), ""))


def lookup_yz(name):
    k = norm_key(name, YZ)
    return None if k is None else YZ[k]


def lookup_dai(name):
    k = norm_key(name, DAI_PRI)
    if k is not None:
        return DAI_PRI[k]
    k = norm_key(name, DAI_OTH)
    return None if k is None else DAI_OTH[k]


# ---------------- 04 页 ----------------
h = rd(HTML_04)
a, b = grab_raw(h, "var S=")
S = json.loads(h[a:b])
a2, b2 = grab_raw(h, "var C=")
C = json.loads(h[a2:b2])
TOTAL = len(S) + len(C)
unmatched = []


PLACEHOLDER = ("", "—", "-", "－", "–", "N/A", "n/a", "无", "无数据")


def is_empty(v):
    """占位符与空串都视为"没有值"，可被补（页面里 '—' 是占位而非数据）"""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in PLACEHOLDER
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def patch_record(d):
    n = d.get("n")
    u = lookup_unit(n)
    if u is None:
        unmatched.append(n)
    yzp = lookup_yz(n)
    dai = lookup_dai(n)

    def fill(key, val, caster=None, tag=None):
        """仅当键缺失或为占位符/空时写入（不覆盖已有手工值）"""
        if val is None or val == "":
            return
        if caster:
            val = caster(val)
            if val is None:
                return
        if not is_empty(d.get(key)):
            return
        d[key] = val
        bump("%s ← %s" % (key, tag or "?"))

    if u:
        fill("l", u.get("line2026"), as_int, "06.line2026")
        fill("plan", u.get("plan2026"), lambda v: str(as_int(v)), "06.plan2026")
        fill("lh", u.get("linesByYear"), lh_from, "06.linesByYear")
        fill("fc", u.get("fill"), None, "06.fill")
        fill("rr", u.get("ratioRetest"), firstnum, "06.ratioRetest")
        fill("rec", u.get("retestCnt"), as_int, "06.retestCnt")
        fill("adm", u.get("admitCnt"), as_int, "06.admitCnt")
        fill("max_s", u.get("admitMax"), as_int, "06.admitMax")
        fill("min_s", u.get("admitMin"), as_int, "06.admitMin")
        fill("avg_s", u.get("admitAvg"), lambda v: round(firstnum(v), 1), "06.admitAvg")
        fill("scope", u.get("scope"), None, "06.scope")
    # 二级来源
    fill("plan", None if yzp is None else str(yzp), None, "yz408.e26")
    if dai:
        fill("rec", dai.get("retest"), as_int, "dai408.retest")
        fill("adm", dai.get("adm"), as_int, "dai408.adm")
        fill("max_s", dai.get("smax"), as_int, "dai408.smax")
        fill("min_s", dai.get("smin"), as_int, "dai408.smin")
        fill("avg_s", dai.get("savg"), lambda v: round(float(v), 1), "dai408.savg")
    # 复录比：可由 rec/adm 计算（仅当 rr 为空且两者都有）
    if d.get("rr") is None and d.get("rec") and d.get("adm"):
        d["rr"] = round(float(d["rec"]) / float(d["adm"]), 2)
        bump("rr ← 计算 rec/adm")


for d in S + C:
    patch_record(d)

newS = json.dumps(S, ensure_ascii=False, separators=(", ", ": "))
newC = json.dumps(C, ensure_ascii=False, separators=(", ", ": "))
if h[a:b] != newS:
    h = h[:a] + newS + h[b:]
    # C 段位置会因 S 段长度变化而偏移，重新定位
    a2, b2 = grab_raw(h, "var C=")
    h = h[:a2] + newC + h[b2:]
    wr(HTML_04, h)
    print("04 页 %s" % ("已写入" if APPLY else "待写入（干跑）"))
else:
    print("04 页无需改动（已是最新）")

# ---------------- 08 页 ----------------
h8 = rd(HTML_08)
c, e = grab_raw(h8, "var DATA=")
DATA = json.loads(h8[c:e])
n8 = 0
for d in DATA["S"] + DATA["C"]:
    if not is_empty(d.get("l")):
        continue
    u = lookup_unit(d.get("n"))
    v = as_int(u.get("line2026")) if u else None
    if v is not None:
        d["l"] = v
        n8 += 1
newDATA = json.dumps(DATA, ensure_ascii=False, separators=(", ", ": "))
if h8[c:e] != newDATA:
    h8 = h8[:c] + newDATA + h8[e:]
    wr(HTML_08, h8)
    print("08 页 %s（补 l %d 条）" % ("已写入" if APPLY else "待写入（干跑）", n8))
else:
    print("08 页无需改动")

# ---------------- 04 页：注入「重点院校专档」章节 + var DEEP ----------------
#   分层：05-院校专档/ 存正本 md；本页只放摘要卡 + 跳转链接（21 校约 30 KB）
#   幂等：以 <!-- /DEEP --> 与 /* ===== DEEP-END ===== */ 为界整段替换；不触碰 var S / var C
DEEP_JSON = os.path.join("05-院校专档", "_deep.json")
SEC_A = '<section id="deep">'
SEC_B = '<!-- /DEEP -->'
JS_A = '/* ===== DEEP-BEGIN ===== */'
JS_B = '/* ===== DEEP-END ===== */'

SEC_HEAD = """<section id="deep">
  <h2>八·五、重点院校专档（21 校 · 深度摘要）<span class="hint">核心 10 所完整版 · 其余 11 所精简版 · 正本见 05-院校专档/</span></h2>
  <div class="hm-toolbar">
    <button class="active" id="dp-core">只看核心 10 所</button>
    <button id="dp-all">展开全部 21 所</button>
    <span style="font-size:12px;color:var(--muted)">按数据丰富度排序；「未获取」= 底稿与联网取证均无该数据</span>
  </div>
  <div id="dp-nav" style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0"></div>
  <div id="deep-grid" class="card-stack"></div>"""

LIGHT_JSON = os.path.join("05-院校专档", "_light.json")


def _esc(t):
    return (str("" if t is None else t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def light_html(light):
    """其余院校轻量速览表（一表一校一行，静态生成，无需 JS）"""
    if not light or not light.get("schools"):
        return ""
    rows = light["schools"]
    h = ['<h3 style="margin-top:24px">其余 %d 所速览（轻量）'
         '<span class="hint">一表一校一行 · 未做深度专档的院校 · 完整表见 05-院校专档/其余院校速览.md</span></h3>'
         % len(rows),
         '<div class="cardsub">只带关键口径，不展开；需要深度的 21 所见上方卡片。'
         '数据来自统一库（06 择校库 + 研招网目录 + Dai408）；「未获取」= 库里确实没有，非漏填。</div>',
         '<div class="table-wrap" style="max-height:520px">',
         '<table style="min-width:1200px"><thead><tr>'
         '<th>院校</th><th>层次</th><th>省市</th><th>2026线</th><th>国家线</th><th>执行国家线</th>'
         '<th>拟招</th><th>复试</th><th>录取</th><th>录取均分</th><th>2027改考</th><th>王道</th>'
         '<th>数据档</th><th>备注</th></tr></thead><tbody>']

    def nz(v):
        return "未获取" if v is None or v == "" else v

    for x in rows:
        h.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td>"
            '<td class="num">%s</td><td class="num">%s</td><td>%s</td>'
            '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
            "<td>%s</td><td class=\"num\">%s</td><td>%s</td><td>%s</td></tr>" % (
                _esc(x["n"]), _esc(x["t"] or "—"),
                _esc((x["p"] or "—") + (("/" + x["r"]) if x["r"] else "")),
                nz(x["line"]), nz(x["nat"]),
                ("是" if x["is_nat"] else "否") if x["line"] is not None else "未获取",
                nz(x["plan"]), nz(x["retest"]), nz(x["admit"]), nz(x["avg"]),
                ("有 %d 条" % x["u27"]) if x["u27"] else "未获取",
                x["wd"] or "未获取",
                {"full": "有实质数据", "catalog_only": "仅目录", "link_only": "仅链接"}.get(x["lvl"], x["lvl"]),
                _esc(x["note"][:70] or "—")))
    h += ["</tbody></table></div>"]
    return "\n".join(h)

JS_CODE = """/* ===== DEEP-BEGIN ===== */
var _dpAll=false;
function dpNum(v){return (v===null||v===undefined||v==='')?'未获取':v;}
function dpTxt(s){return String(s==null?'':s).replace(/\\*\\*/g,'').replace(/`/g,'');}
function deepCard(d){
  var h='<div class="card" id="deep-'+esc(d.k)+'">';
  h+='<h3>'+esc(d.n)+' '+tierTag(d.t)+' <span class="tag" style="background:#5d7182">'+(d.depth==='full'?'完整版':'精简版')+'</span></h3>';
  h+='<div class="cardsub">'+[d.t,d.verdict?('定位 '+d.verdict):'定位 未获取','更新 '+(d.updated||'')].filter(Boolean).join(' · ')+'</div>';
  h+='<div class="dim-grid">';
  h+='<div class="dim"><div class="dt">一页结论</div><ul>'+((d.bullets&&d.bullets.length)?d.bullets.map(function(b){return '<li>'+esc(dpTxt(b))+'</li>';}).join(''):'<li>未获取</li>')+'</ul></div>';
  h+='<div class="dim"><div class="dt">关键数字</div>'+
     '<div class="row"><span>2026 复试线</span><b>'+dpNum(d.line)+(d.nat?('（国家线 '+d.nat+(d.gap>0?'，超 '+d.gap+' 分':(d.gap<0?'，低于 '+(-d.gap)+' 分':''))+'）'):'')+'</b></div>'+
     '<div class="row"><span>拟招 / 复试 / 录取</span><b>'+dpNum(d.plan)+' / '+dpNum(d.retest)+' / '+dpNum(d.admit)+'</b></div>'+
     '<div class="row"><span>录取最低 / 最高 / 均分</span><b>'+dpNum(d.min)+' / '+dpNum(d.max)+' / '+dpNum(d.avg)+'</b></div>'+
     '</div>';
  h+='<div class="dim"><div class="dt">正本</div><a href="../'+esc(d.md)+'" target="_blank" rel="noopener">打开完整专档 →</a></div>';
  h+='</div></div>';
  return h;
}
function renderDeep(){
  var box=document.getElementById('deep-grid'); if(!box) return;
  var nav=document.getElementById('dp-nav');
  var rows=(typeof DEEP==='undefined'?[]:DEEP).filter(function(d){return _dpAll||d.depth==='full';});
  if(nav) nav.innerHTML=rows.map(function(d){return '<a href="#deep-'+esc(d.k)+'" style="font-size:12px;padding:3px 9px;border:1px solid var(--rule);border-radius:999px;text-decoration:none;color:var(--accent)">'+esc(d.n)+'</a>';}).join('');
  box.innerHTML=rows.map(deepCard).join('')||'<div class="cardsub">专档尚未生成（跑 09-生成脚本/build_school_profiles.py --index）</div>';
  var b1=document.getElementById('dp-core'), b2=document.getElementById('dp-all');
  if(b1) b1.className=_dpAll?'':'active';
  if(b2) b2.className=_dpAll?'active':'';
}
function dpInit(){
  var b1=document.getElementById('dp-core'), b2=document.getElementById('dp-all');
  if(b1) b1.addEventListener('click',function(){_dpAll=false;renderDeep();});
  if(b2) b2.addEventListener('click',function(){_dpAll=true;renderDeep();});
  renderDeep();
}
dpInit();
/* ===== DEEP-END ===== */"""

if not os.path.isfile(DEEP_JSON):
    print("04 页专档章节：跳过（缺 %s，跑 build_school_profiles.py --index）" % DEEP_JSON)
else:
    _deep = json.load(io.open(DEEP_JSON, encoding="utf-8"))
    _light = json.load(io.open(LIGHT_JSON, encoding="utf-8")) if os.path.isfile(LIGHT_JSON) else None
    _sec = SEC_HEAD + "\n" + light_html(_light) + "\n</section>"
    _ds = json.dumps(_deep, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    _block = _sec + '\n<script>var DEEP=' + _ds + ';</script>\n' + SEC_B
    h4 = rd(HTML_04)
    if SEC_A in h4 and SEC_B in h4:
        _i, _j = h4.index(SEC_A), h4.index(SEC_B) + len(SEC_B)
        h4n = h4[:_i] + _block + h4[_j:]
    else:
        _a = h4.index('<section id="detail">')
        _b = h4.index("</section>", _a) + len("</section>")
        h4n = h4[:_b] + "\n\n" + _block + h4[_b:]
    if JS_A in h4n and JS_B in h4n:
        _i, _j = h4n.index(JS_A), h4n.index(JS_B) + len(JS_B)
        h4n = h4n[:_i] + JS_CODE + h4n[_j:]
    else:
        _k = h4n.rindex("</script>")
        h4n = h4n[:_k] + JS_CODE + "\n" + h4n[_k:]
    if h4n != h4:
        wr(HTML_04, h4n)
        print("04 页专档章节 %s（var DEEP %d 条：完整版 %d / 精简版 %d）" % (
            "已写入" if APPLY else "待写入（干跑）", len(_deep),
            sum(1 for d in _deep if d.get("depth") == "full"),
            sum(1 for d in _deep if d.get("depth") != "full")))
    else:
        print("04 页专档章节无需改动（var DEEP %d 条）" % len(_deep))

# ---------------- score_matrix.json（06 浏览器页实际读取的文件）----------------
#   该文件的生成器 build_score_matrix.py 已断链（ext/ 缺失），属**手工维护的派生文件**。
#   只做两件"不引入新事实"的事：① 用已有的 retestCnt/admitCnt 算复录比；② 用 yz408 的 e26 补拟招。
SM = os.path.join(D06, "score_matrix.json")
sm = json.load(io.open(SM, encoding="utf-8"))
sm_old = json.dumps(sm, ensure_ascii=False, separators=(",", ":"))
n_rr = n_pl = 0
for sch in sm.get("schools", []):
    for u in (sch.get("units") or []):
        if is_empty(u.get("ratioRetest")):
            a, b = firstnum(u.get("retestCnt")), firstnum(u.get("admitCnt"))
            if a and b:
                u["ratioRetest"] = round(a / b, 2)
                n_rr += 1
        if is_empty(u.get("plan2026")):
            v = lookup_yz(sch.get("name"))
            if v is not None:
                u["plan2026"] = str(v)
                n_pl += 1
if n_rr or n_pl:
    sm["patched"] = ("2026-09-23 patch_pages_from_db.py：补 ratioRetest(由 retestCnt/admitCnt 计算) "
                     "与 plan2026(来自 yz408_catalog)；本文件生成器 build_score_matrix.py 已断链，属手工维护的派生文件")
sm_new = json.dumps(sm, ensure_ascii=False, separators=(",", ":"))
if sm_new != sm_old:
    wr(SM, sm_new)
    print("score_matrix.json %s（补 ratioRetest %d 条 / plan2026 %d 条）"
          % ("已写入" if APPLY else "待写入（干跑）", n_rr, n_pl))
else:
    print("score_matrix.json 无需改动")

# ---------------- 报告 ----------------
print("\n=== 补入统计（04 页 %d 条记录）===" % TOTAL)
for k in sorted(stats, key=lambda x: -stats[x]):
    print("  %-28s %3d 条" % (k, stats[k]))
if unmatched:
    print("\n未在 06 主库匹配到的院校（%d 所，其字段仅可能来自 yz408/dai408）:" % len(unmatched))
    print("  " + ", ".join(sorted(set(unmatched))[:20]))

print("\n=== 04 页字段填充率（补后）===")
for k in ["l", "plan", "lh", "rec", "adm", "max_s", "min_s", "avg_s", "rr", "scope"]:
    got = sum(1 for d in S + C if d.get(k) not in (None, ""))
    print("  %-8s %3d / %d  (%.0f%%)" % (k, got, TOTAL, 100.0 * got / TOTAL))

if not APPLY:
    print("\n[干跑] 未写入任何文件。加 --apply 生效。")
