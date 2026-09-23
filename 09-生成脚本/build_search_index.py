#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_search_index.py —— 从统一院校库生成「搜索索引」+「可查询索引页」

输入（正本，勿手改）：
  06-院校数据库/data/kaoyan408.db        （由 build_unified_db.py 生成；本地派生、不入库）

输出：
  06-院校数据库/data/搜索索引.json        索引数据（扁平化，供程序化查询 / 外部工具消费）
  06-院校数据库/索引.html                 单文件索引页（索引内嵌，双击可离线打开；搜索框支持院校 / 专业 / 代码 / 学院）

设计要点：
  · 单一事实来源 = kaoyan408.db；本脚本只做「导出 + 渲染」，不含业务逻辑
  · 索引页把数据内嵌而非 fetch —— 保证 file:// 双击、GitHub Pages、离线三种场景都能用
  · 搜索维度：校名 / 校名别名 / 招生单位代码 / 专业代码 / 专业名 / 学院名 / 省份
  · 幂等：每次全量重建；不改动任何正本文件

用法：
  python 09-生成脚本/build_search_index.py            # 生成索引 + 页面
  python 09-生成脚本/build_search_index.py --json-only # 只导出 JSON
"""
import io
import json
import os
import re
import sqlite3
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D06 = os.path.join(ROOT, "06-院校数据库")
DB = os.path.join(D06, "data", "kaoyan408.db")
OUT_JSON = os.path.join(D06, "data", "搜索索引.json")
OUT_HTML = os.path.join(D06, "索引.html")

# 索引里每校保留的王道链接条数上限（全库 3530 条，全塞进页面没必要）
WD_CAP = 6


def jload(v):
    """DB 里的 JSON 字符串列 → Python 对象；失败返回原值"""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s or s[0] not in "[{":
        return v
    try:
        return json.loads(s)
    except ValueError:
        return v


def main():
    if not os.path.isfile(DB):
        print("✗ 未找到 %s\n  请先运行：python 09-生成脚本/build_unified_db.py" % DB)
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def q(sql, args=()):
        return [dict(r) for r in cur.execute(sql, args).fetchall()]

    # ---------- 1. 学校 ----------
    schools = {}
    for r in q("""SELECT school_key k, code, code_verified cv, name n, province p, province_raw pr,
                         region r, tier t, is985 a985, is211 a211, is_dfc dfc, cs_rank csr,
                         in_lib06 l6, in_lib10 l10, in_yz408 lyz, in_cb cb, cb_id cbid,
                         data_level lvl, n_offerings no, n_majors nm, n_lines nl, n_admissions na,
                         n_quantiles nq, n_tutors nt, n_kaoqing nk, n_updates2027 nu, n_conflicts nc
                    FROM v_school_all ORDER BY name"""):
        schools[r["k"]] = {
            "k": r["k"], "code": r["code"], "cv": r["cv"], "n": r["n"],
            "p": r["p"] or "", "r": r["r"] or "", "t": r["t"] or "",
            "f985": r["a985"], "f211": r["a211"], "dfc": r["dfc"],
            "csr": r["csr"], "lvl": r["lvl"],
            "lib": [r["l6"] or 0, r["l10"] or 0, r["lyz"] or 0, r["cb"] or 0],
            "cbid": r["cbid"],
            "cnt": {"o": r["no"], "m": r["nm"], "l": r["nl"], "a": r["na"], "q": r["nq"],
                    "tut": r["nt"], "kq": r["nk"], "u27": r["nu"], "cf": r["nc"]},
            "al": [],
        }

    # 别名（含校名自身）
    for r in q("SELECT school_key k, alias a FROM school_aliases"):
        s = schools.get(r["k"])
        if s is not None and r["a"] and r["a"] not in s["al"]:
            s["al"].append(r["a"])

    # ---------- 2. 专业字典 ----------
    majors = {}
    for r in q("""SELECT major_code c, major_name n, degree_type dt, category cat, n_yz408 nz
                    FROM majors ORDER BY n_yz408 DESC, major_code"""):
        majors[r["c"]] = {"c": r["c"], "n": r["n"], "dt": r["dt"] or "", "cat": r["cat"] or "",
                          "nz": r["nz"] or 0, "ns": 0, "sg": [], "co": []}
    # 补录代码（研招网目录未收录）的名称兜底
    for r in q("SELECT DISTINCT major_code c FROM offerings WHERE major_code IS NOT NULL"):
        if r["c"] and r["c"] not in majors:
            majors[r["c"]] = {"c": r["c"], "n": "（未收录专业）", "dt": "", "cat": "", "nz": 0,
                              "ns": 0, "sg": [], "co": []}

    # ---------- 3. offering：学校×专业×学院 ----------
    offerings = []
    for r in q("""SELECT o.id, o.school_key k, o.major_code c, o.major_source ms, o.college col,
                         o.direction dir, o.subject_class sc, o.ai_tag ai, o.src src, o.src_label sl,
                         o.scope, o.kaoqing_url, o.nn_college nnc, o.nn_prog nnp, o.nn_subjects nns,
                         o.wd_count wdc, o.cy_code cyc, o.cy_avg cya
                    FROM offerings o ORDER BY o.school_key, o.major_code"""):
        o = {"k": r["k"], "c": r["c"], "col": r["col"] or "", "dir": r["dir"] or "",
             "sc": r["sc"] or "", "ai": r["ai"] or "", "src": r["src"] or "",
             "ms": r["ms"] or "", "scope": r["scope"] or "", "nnc": r["nnc"] or "",
             "nnp": r["nnp"] or "", "nns": r["nns"] or "", "wdc": r["wdc"] or "",
             "cyc": r["cyc"] or "", "cya": r["cya"] or "", "id": r["id"]}
        offerings.append(o)
        s = schools.get(r["k"])
        if s is not None:
            s.setdefault("o", []).append({"c": r["c"], "col": o["col"], "dir": o["dir"],
                                          "sc": o["sc"], "ai": o["ai"], "id": r["id"]})
        m = majors.get(r["c"])
        if m is not None:
            m["ns"] += 1
            if r["k"] not in m["sg"]:
                m["sg"].append(r["k"])
            if r["col"] and r["col"] not in m["co"]:
                m["co"].append(r["col"])

    # ---------- 4. 各类明细（按 school_key 分组，避免每校重复冗余字段名） ----------
    lines = {}
    for r in q("""SELECT school_key k, major_code c, year y, value v, raw_value raw, value_kind vk
                    FROM score_lines ORDER BY school_key, year"""):
        lines.setdefault(r["k"], []).append([r["c"], r["y"], r["v"], r["raw"], r["vk"]])

    adm = {}
    for r in q("""SELECT school_key k, major_code c, year y, plan_value pv, plan p,
                         retest_cnt_value rv, retest_cnt r, admit_cnt_value av, admit_cnt a,
                         admit_min_value mnv, admit_min mn, admit_max_value mxv, admit_max mx,
                         admit_avg_value agv, admit_avg ag, ratio_retest rr, fill_value fv, fill f
                    FROM admissions ORDER BY school_key"""):
        adm.setdefault(r["k"], []).append([r["c"], r["y"], r["pv"], r["p"], r["rv"], r["r"],
                                           r["av"], r["a"], r["mnv"], r["mn"], r["mxv"], r["mx"],
                                           r["agv"], r["ag"], r["rr"], r["fv"], r["f"]])

    tut = {}
    for r in q("""SELECT school_key k, major_code c, school_name sn, dept d, name nm,
                         title ti, direction dir, url u, note nt, src s
                    FROM tutors ORDER BY school_key, id"""):
        tut.setdefault(r["k"], []).append([r["nm"], r["d"], r["ti"], r["dir"], r["u"], r["c"], r["nt"]])

    kq = {}
    for r in q("""SELECT school_key k, major_code c, college col, subjects sub, program pg,
                         batch b, year y, line_value lv, plan pl, retest_cnt rc, admit_cnt ac,
                         admit_max mx, admit_min mn, admit_avg ag, scope, url u, verify v
                    FROM kaoqing ORDER BY school_key"""):
        kq.setdefault(r["k"], []).append([r["col"], r["sub"], r["pg"], r["y"], r["lv"], r["pl"],
                                          r["rc"], r["ac"], r["mx"], r["mn"], r["ag"], r["scope"],
                                          r["u"], r["v"], r["c"]])

    u27 = {}
    for r in q("""SELECT school_key k, major_code c, scope, subject_old so, subject_new sn,
                         effective_year ey, source s, note nt
                    FROM updates_2027 ORDER BY school_key"""):
        u27.setdefault(r["k"], []).append([r["scope"], r["so"], r["sn"], r["ey"], r["s"], r["nt"], r["c"]])

    wd = {}
    for r in q("""SELECT school_key k, year_label y, url u FROM wangdao_links
                   ORDER BY school_key, year_label DESC"""):
        lst = wd.setdefault(r["k"], [])
        if len(lst) < WD_CAP:
            lst.append([r["y"], r["u"]])

    cat = {}
    for r in q("""SELECT school_key k, year y, major_code c, college col, scope,
                         exam_408_type ex, degree_type dt, note nt, source_level sl, source_url su
                    FROM catalog ORDER BY school_key, year"""):
        cat.setdefault(r["k"], []).append([r["y"], r["c"], r["col"], r["scope"], r["ex"], r["dt"], r["nt"], r["su"]])

    cf = {}
    for r in q("""SELECT school_key k, major_code c, scope, field f, old_value ov, new_value nv,
                         reason rs, claims cl, status st, action ac
                    FROM conflicts ORDER BY school_key"""):
        cf.setdefault(r["k"], []).append([r["f"], r["cl"], r["st"], r["ac"],
                                          r["c"], r["ov"], r["nv"], r["rs"]])

    subs = {}
    for r in q("""SELECT o.school_key k, e.subject_key sk, e.subject_label sl
                    FROM exam_subjects e JOIN offerings o ON o.id = e.offering_id"""):
        subs.setdefault(r["k"], [])
        if [r["sk"], r["sl"]] not in subs[r["k"]]:
            subs[r["k"]].append([r["sk"], r["sl"]])

    todo = {}
    for r in q("SELECT school_key k, field_name f, n_missing n FROM todo_patch ORDER BY school_key"):
        todo.setdefault(r["k"], []).append([r["f"], r["n"]])

    nlines = q("SELECT year y, subject_category sc, zone z, total_line t, subject_408_line s, src FROM national_lines ORDER BY year DESC")

    # ---------- 5. 统计 ----------
    meta = {
        "built": str(date.today()),
        "source": "kaoyan408.db（由 build_unified_db.py 从 06/10/研招网/01/07 多源合成）",
        "generator": "09-生成脚本/build_search_index.py",
        "nSchools": len(schools),
        "nMajors": len(majors),
        "nOfferings": len(offerings),
        "nAliases": sum(len(s["al"]) for s in schools.values()),
        "nFull": sum(1 for s in schools.values() if s["lvl"] == "full"),
        "nCatalogOnly": sum(1 for s in schools.values() if s["lvl"] == "catalog_only"),
        "nLinkOnly": sum(1 for s in schools.values() if s["lvl"] == "link_only"),
        "detailRows": {"score_lines": sum(len(v) for v in lines.values()),
                       "admissions": sum(len(v) for v in adm.values()),
                       "tutors": sum(len(v) for v in tut.values()),
                       "kaoqing": sum(len(v) for v in kq.values()),
                       "updates_2027": sum(len(v) for v in u27.values()),
                       "catalog": sum(len(v) for v in cat.values()),
                       "wangdao_links(截取)": sum(len(v) for v in wd.values())},
    }

    idx = {
        "meta": meta,
        "majors": [majors[c] for c in sorted(majors, key=lambda x: -majors[x]["nz"])],
        "schools": [schools[k] for k in sorted(schools, key=lambda x: schools[x]["n"])],
        "offerings": offerings,
        "d": {"lines": lines, "adm": adm, "tut": tut, "kq": kq, "u27": u27,
              "wd": wd, "cat": cat, "cf": cf, "subs": subs, "todo": todo,
              "nl": nlines},
    }

    payload = json.dumps(idx, ensure_ascii=False, separators=(",", ":"))
    io.open(OUT_JSON, "w", encoding="utf-8", newline="\n").write(payload)

    print("✓ 索引已导出 %s（%.0f KB）" % (os.path.relpath(OUT_JSON, ROOT).replace(os.sep, "/"),
                                        len(payload.encode("utf-8")) / 1024.0))
    print("  学校 %d ｜ 专业 %d ｜ 学校×专业×学院 %d ｜ 别名 %d" % (
        meta["nSchools"], meta["nMajors"], meta["nOfferings"], meta["nAliases"]))
    print("  数据档：full %d / catalog_only %d / link_only %d" % (
        meta["nFull"], meta["nCatalogOnly"], meta["nLinkOnly"]))
    print("  明细行：%s" % json.dumps(meta["detailRows"], ensure_ascii=False))

    if "--json-only" in sys.argv:
        con.close()
        return 0

    # 内嵌进 <script> 前必须转义 "</"，否则数据里若出现 </script> 会截断脚本块
    payload_html = payload.replace("</", "<\\/")
    html = TEMPLATE.replace("/*__INDEX__*/null", payload_html).replace("__WDCAP__", str(WD_CAP))
    io.open(OUT_HTML, "w", encoding="utf-8", newline="\n").write(html)
    print("✓ 索引页已生成 %s（%.0f KB）" % (os.path.relpath(OUT_HTML, ROOT).replace(os.sep, "/"),
                                          len(html.encode("utf-8")) / 1024.0))
    con.close()
    return 0


# ============================ 索引页模板 ============================
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>408 院校索引 · 搜索院校 / 专业</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--line:#e3e6ec;--tx:#1c2028;--tx2:#5b6472;--tx3:#8d97a6;
      --ac:#2f6bd8;--ac2:#eaf1fd;--ok:#1f9254;--warn:#c47f17;--bad:#c0392b;--rad:10px}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
a{color:var(--ac);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1400px;margin:0 auto;padding:18px 20px 60px}
header h1{margin:0 0 4px;font-size:22px;letter-spacing:.3px}
header .sub{color:var(--tx2);font-size:13px}
header .sub b{color:var(--tx)}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:16px 0 10px}
.search{position:relative;flex:1 1 380px;min-width:260px}
.search input{width:100%;padding:13px 42px 13px 40px;font-size:16px;border:1px solid var(--line);
  border-radius:var(--rad);background:var(--card);outline:none;transition:.15s}
.search input:focus{border-color:var(--ac);box-shadow:0 0 0 3px var(--ac2)}
.search .ico{position:absolute;left:13px;top:12px;color:var(--tx3);font-size:16px}
.search .clr{position:absolute;right:10px;top:9px;border:0;background:none;color:var(--tx3);
  font-size:18px;cursor:pointer;padding:2px 6px;border-radius:6px}
.search .clr:hover{background:var(--bg);color:var(--tx)}
select{padding:11px 10px;font-size:14px;border:1px solid var(--line);border-radius:var(--rad);
  background:var(--card);color:var(--tx);outline:none;max-width:180px}
.hint{color:var(--tx3);font-size:12.5px;margin:0 0 14px}
.hint kbd{background:#eceff4;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;
  padding:0 5px;font-size:11.5px;font-family:inherit}
.stat{display:flex;gap:18px;flex-wrap:wrap;color:var(--tx2);font-size:12.5px;margin-bottom:14px}
.stat b{color:var(--tx)}
.cols{display:grid;grid-template-columns:minmax(300px,420px) 1fr;gap:16px;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);overflow:hidden}
.panel>h2{margin:0;padding:11px 14px;font-size:13px;font-weight:600;color:var(--tx2);
  border-bottom:1px solid var(--line);background:#fafbfc;display:flex;justify-content:space-between}
#list{max-height:70vh;overflow:auto}
.row{padding:10px 14px;border-bottom:1px solid #f0f2f5;cursor:pointer;display:flex;
  justify-content:space-between;gap:10px;align-items:baseline}
.row:hover{background:#f8fafd}
.row.on{background:var(--ac2);box-shadow:inset 3px 0 0 var(--ac)}
.row .nm{font-weight:600}
.row .nm em{font-style:normal;background:#fff3bf;border-radius:3px;padding:0 1px}
.row .meta{color:var(--tx3);font-size:12px;text-align:right;white-space:nowrap}
.tag{display:inline-block;font-size:11px;line-height:17px;padding:0 6px;border-radius:4px;
  border:1px solid var(--line);color:var(--tx2);background:#fafbfc;margin-right:4px}
.tag.t985{background:#eaf1fd;border-color:#c3d8f7;color:#1d4fa8}
.tag.t211{background:#eef7f0;border-color:#c8e6d3;color:#1a7a44}
.tag.tdfc{background:#fdf3ea;border-color:#f5dcc2;color:#a35c12}
.tag.kind{background:#f2eefc;border-color:#dcd2f5;color:#5b3fa8}
#detail{padding:16px 18px;min-height:260px}
#detail .empty{color:var(--tx3);text-align:center;padding:70px 10px}
#detail h3{margin:0 0 2px;font-size:19px}
#detail .lead{color:var(--tx2);font-size:13px;margin-bottom:14px}
#detail .lead code{background:#f0f2f5;border-radius:4px;padding:1px 5px;font-size:12px}
.sec{margin:16px 0 0}
.sec>h4{margin:0 0 8px;font-size:13px;color:var(--tx2);border-left:3px solid var(--ac);
  padding-left:8px;display:flex;justify-content:space-between;align-items:baseline}
.sec>h4 span{color:var(--tx3);font-weight:400;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #f0f2f5;vertical-align:top}
th{color:var(--tx3);font-weight:600;background:#fafbfc;position:sticky;top:0}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{max-height:320px;overflow:auto;border:1px solid var(--line);border-radius:8px}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px 16px;font-size:12.5px}
.kv div{color:var(--tx2)}
.kv b{color:var(--tx)}
.note{color:var(--tx3);font-size:12px;margin-top:6px}
.empty-row{color:var(--tx3);font-size:12.5px;padding:8px 2px}
footer{margin-top:26px;color:var(--tx3);font-size:12px;border-top:1px solid var(--line);padding-top:12px}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>408 院校索引</h1>
  <div class="sub">数据来自统一院校库 <code>kaoyan408.db</code>（学校 → 专业 → 各类数据）·
    <b id="hd"></b></div>
</header>

<div class="bar">
  <div class="search">
    <span class="ico">⌕</span>
    <input id="q" type="search" placeholder="搜索院校 / 专业 / 招生单位代码 / 专业代码 / 学院…" autocomplete="off" autofocus>
    <button class="clr" id="clr" title="清空">×</button>
  </div>
  <select id="fProv"><option value="">全部省份</option></select>
  <select id="fTier"><option value="">全部层次</option></select>
  <select id="fLvl"><option value="">全部数据档</option></select>
</div>
<p class="hint">
  支持：<kbd>校名</kbd> <kbd>别名</kbd> <kbd>5 位招生单位代码</kbd> <kbd>6 位专业代码</kbd>
  <kbd>专业名</kbd> <kbd>学院名</kbd> · 输入 <kbd>085410</kbd> 或 <kbd>人工智能</kbd> 可看专业下所有院校
</p>
<div class="stat" id="stat"></div>

<div class="cols">
  <div class="panel">
    <h2><span id="listTitle">结果</span><span id="listCount"></span></h2>
    <div id="list"></div>
  </div>
  <div class="panel">
    <h2>详情</h2>
    <div id="detail"><div class="empty">← 左侧选择一所院校或一个专业</div></div>
  </div>
</div>

<footer>
  索引页由 <code>09-生成脚本/build_search_index.py</code> 从统一库自动生成，<b>请勿手改本文件</b>；
  数据修正请改正本（<code>06-院校数据库/data/schools/*.json</code> 等）后重跑构建脚本。
</footer>
</div>

<script>
var IDX = /*__INDEX__*/null;
if(!IDX){document.getElementById('detail').innerHTML='<div class="empty">索引未内嵌：请运行 09-生成脚本/build_search_index.py 重新生成</div>';}
else{(function(){
  var S=IDX.schools, M=IDX.majors, D=IDX.d, OF=IDX.offerings;
  var SM={}, MM={}; S.forEach(function(s){SM[s.k]=s}); M.forEach(function(m){MM[m.c]=m});
  var TIER_ORDER=['985','211','双一流','双非','普通'];

  /* ---------- 工具 ---------- */
  function esc(t){return String(t==null?'':t).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function norm(t){return String(t==null?'':t).toLowerCase()
    .replace(/[\s·、,，.。\-—_()（）\[\]【】\/]/g,'')}
  function hl(text,q){ if(!q) return esc(text);
    var t=String(text==null?'':text), n=norm(t), k=norm(q);
    if(!k||n.indexOf(k)<0) return esc(t);
    // 在原文里找与规范化位置对应的片段（简化：逐字符扫描）
    var out='',buf='',cnt=0,i=0;
    for(i=0;i<t.length;i++){
      var ch=t[i], cn=norm(ch);
      if(cn===''){ if(cnt>0&&cnt<k.length){cnt=0;out+=esc(buf);buf=''} out+=esc(ch); continue; }
      if(cnt<k.length&&cn===k[cnt]){buf+=ch;cnt++;
        if(cnt===k.length){out+='<em>'+esc(buf)+'</em>';buf='';cnt=0}
      }else{ if(cnt>0){out+=esc(buf);buf='';cnt=0}
        if(cn===k[0]){buf=ch;cnt=1}else{out+=esc(ch)} }
    }
    if(buf) out+=esc(buf);
    return out;
  }
  function num(v){return (v==null||v==='')?'—':v}
  function jstr(v){ if(v==null) return ''; if(typeof v==='string') return v;
    try{return JSON.stringify(v)}catch(e){return String(v)} }
  function claimsText(v){ var a=jstr(v);
    try{ var o=JSON.parse(a); if(Array.isArray(o)) return o.map(function(x){
      return (x&&x.src?x.src+':':'')+(x&&x.value!=null?x.value:JSON.stringify(x))}).join(' ｜ ');
      return a }catch(e){ return a } }

  /* ---------- 搜索 ---------- */
  function matchSchool(s,q){
    if(!q) return 0;
    var n=norm(s.n), k=norm(q);
    if(s.k===q||s.code===q) return 100;
    if(n===k) return 95;
    if(n.indexOf(k)===0) return 88;
    if(n.indexOf(k)>=0) return 80;
    for(var i=0;i<s.al.length;i++){ var a=norm(s.al[i]);
      if(a===k) return 78; if(a.indexOf(k)>=0) return 66; }
    if(s.code&&String(s.code).indexOf(q)===0) return 60;
    var os=s.o||[];
    for(var j=0;j<os.length;j++){
      if(os[j].col&&norm(os[j].col).indexOf(k)>=0) return 55;
      if(os[j].dir&&norm(os[j].dir).indexOf(k)>=0) return 50;
    }
    if(s.p&&norm(s.p).indexOf(k)>=0) return 40;
    return 0;
  }
  function matchMajor(m,q){
    if(!q) return 0;
    var k=norm(q);
    if(m.c===q) return 100;
    if(norm(m.n)===k) return 95;
    if(norm(m.n).indexOf(k)>=0) return 85;
    if(m.c.indexOf(q)===0) return 70;
    return 0;
  }
  function search(q){
    q=(q||'').trim();
    var res=[];
    if(!q){
      // 空查询：按数据丰富度给「有实质数据」的院校
      S.filter(function(s){return s.lvl==='full'}).forEach(function(s){
        res.push({t:'s',o:s,sc:0}) });
      return {rows:res,kind:'browse'};
    }
    var maj=[],sch=[];
    M.forEach(function(m){var sc=matchMajor(m,q); if(sc) maj.push({t:'m',o:m,sc:sc})});
    S.forEach(function(s){var sc=matchSchool(s,q); if(sc) sch.push({t:'s',o:s,sc:sc})});
    maj.sort(function(a,b){return b.sc-a.sc||b.o.nz-a.o.nz});
    sch.sort(function(a,b){return b.sc-a.sc||dense(b.o)-dense(a.o)});
    return {rows:maj.concat(sch),kind:'search'};
  }
  function dense(s){return (s.cnt.o||0)*10+(s.cnt.l||0)+(s.cnt.kq||0)+(s.cnt.tut||0)}

  /* ---------- 过滤 ---------- */
  function pass(s){
    var p=el('fProv').value,t=el('fTier').value,l=el('fLvl').value;
    if(p&&s.p!==p) return false;
    if(t&&s.t!==t) return false;
    if(l&&s.lvl!==l) return false;
    return true;
  }
  function el(id){return document.getElementById(id)}

  /* ---------- 渲染列表 ---------- */
  var cur=null;
  function render(){
    var q=el('q').value.trim();
    var r=search(q), rows=r.rows.filter(function(x){
      return x.t==='m' ? true : pass(x.o) });
    el('listTitle').textContent = r.kind==='browse' ? '有实质数据的院校' : '搜索结果';
    el('listCount').textContent = rows.length + ' 条';
    if(!rows.length){ el('list').innerHTML='<div class="empty-row" style="padding:20px 14px">没有匹配项。试试校名片段（如「郑州」）、专业代码（<b>085410</b>）或专业名（<b>人工智能</b>）。</div>'; return }
    var h='';
    rows.slice(0,600).forEach(function(x,i){
      if(x.t==='m'){ var m=x.o;
        h+='<div class="row" data-t="m" data-k="'+esc(m.c)+'">'+
           '<div><span class="tag kind">专业</span><span class="nm">'+hl(m.n,q)+
           ' <code>'+esc(m.c)+'</code></span><div class="meta" style="text-align:left;margin-top:2px">'+
           esc(m.dt||'')+(m.cat&&m.cat!==m.dt?' · '+esc(m.cat):'')+'</div></div>'+
           '<div class="meta">'+m.sg.length+' 校</div></div>';
      }else{ var s=x.o;
        h+='<div class="row" data-t="s" data-k="'+esc(s.k)+'">'+
           '<div><span class="nm">'+hl(s.n,q)+'</span> '+tierTags(s)+
           '<div class="meta" style="text-align:left;margin-top:2px">'+esc(s.p||'—')+
           (s.code?' · <code>'+esc(s.code)+'</code>':'')+'</div></div>'+
           '<div class="meta">'+denseTags(s)+'</div></div>';
      }
    });
    el('list').innerHTML=h;
    Array.prototype.forEach.call(el('list').querySelectorAll('.row'),function(d){
      d.onclick=function(){ pick(d.getAttribute('data-t'),d.getAttribute('data-k'),d) }});
    if(rows.length>600) el('list').innerHTML+='<div class="empty-row" style="padding:12px 14px">仅显示前 600 条，请细化搜索条件</div>';
  }
  function tierTags(s){
    var t='';
    if(s.f985) t+='<span class="tag t985">985</span>';
    if(s.f211) t+='<span class="tag t211">211</span>';
    if(s.dfc) t+='<span class="tag tdfc">双一流</span>';
    if(!t&&s.t) t+='<span class="tag">'+esc(s.t)+'</span>';
    return t;
  }
  function denseTags(s){
    var a=[];
    if(s.cnt.o) a.push(s.cnt.o+' 专业');
    if(s.cnt.l) a.push('线'+s.cnt.l);
    if(s.cnt.a) a.push('招录'+s.cnt.a);
    if(s.cnt.q) a.push('分位'+s.cnt.q);
    if(s.cnt.tut) a.push('导师'+s.cnt.tut);
    if(s.cnt.kq) a.push('考情'+s.cnt.kq);
    if(s.cnt.u27) a.push('改考'+s.cnt.u27);
    return a.length? a.join(' · ') : '<span style="color:var(--tx3)">仅目录/链接</span>';
  }
  function pick(t,k,node){
    Array.prototype.forEach.call(el('list').querySelectorAll('.row'),function(d){d.classList.remove('on')});
    if(node) node.classList.add('on');
    cur={t:t,k:k};
    el('detail').innerHTML = t==='m' ? majorDetail(k) : schoolDetail(k);
  }

  /* ---------- 详情：院校 ---------- */
  function schoolDetail(k){
    var s=SM[k]; if(!s) return '<div class="empty">未找到</div>';
    var h='<h3>'+esc(s.n)+'</h3><div class="lead">'+
      (s.code?'招生单位代码 <code>'+esc(s.code)+'</code>'+(s.cv?'':' <span class="tag" style="color:var(--warn);border-color:#f0dcc0">未验证</span>'):'代码未知')+
      ' · '+esc(s.p||'省份未知')+(s.r?' · '+esc(s.r):'')+(s.t?' · '+esc(s.t):'')+
      (s.csr?' · CS 排名 '+esc(s.csr):'')+'</div>';
    h+='<div class="sec"><h4>数据档案</h4><div class="kv">'+
       kv('数据档',({full:'有实质数据',catalog_only:'仅研招网目录',link_only:'仅链接'})[s.lvl]||s.lvl)+
       kv('学校×专业',s.cnt.o+' 条')+kv('复试线',s.cnt.l+' 条')+kv('招录',s.cnt.a+' 条')+
       kv('分数分位',s.cnt.q+' 条')+kv('导师',s.cnt.tut+' 位')+kv('考情',s.cnt.kq+' 条')+
       kv('2027改考',s.cnt.u27+' 条')+kv('冲突登记',s.cnt.cf+' 条')+
       kv('来源',(s.lib[0]?'06择校库 ':'')+(s.lib[1]?'10分数库 ':'')+(s.lib[2]?'研招网目录 ':'')+(s.lib[3]?'CodeBrick':''))+
       (s.al.length>1?kv('别名',esc(s.al.filter(function(a){return a!==s.n}).join('、')||'—')):'')+
       '</div></div>';

    // 专业
    var os=s.o||[];
    h+='<div class="sec"><h4>专业（学校 × 专业 × 学院）<span>'+os.length+' 条</span></h4>';
    if(!os.length) h+='<div class="empty-row">无专业明细（该校仅有目录或链接级数据）</div>';
    else{
      h+='<div class="scroll"><table><thead><tr><th>专业代码</th><th>专业名</th><th>学院 / 单位</th><th>研究方向</th><th>科目口径</th></tr></thead><tbody>';
      os.forEach(function(o){ var m=MM[o.c];
        h+='<tr><td class="num"><a href="javascript:void(0)" onclick="__pickM(\''+esc(o.c)+'\')">'+esc(o.c||'—')+'</a></td>'+
           '<td>'+esc(m?m.n:'—')+'</td><td>'+esc(o.col||'—')+'</td>'+
           '<td>'+esc(o.dir||'—')+'</td><td>'+esc(o.sc||'—')+'</td></tr>' });
      h+='</tbody></table></div>';
    }
    h+='</div>';

    // 复试线
    var L=D.lines[k]||[];
    h+='<div class="sec"><h4>历年复试线<span>'+L.length+' 条</span></h4>';
    if(!L.length) h+='<div class="empty-row">无</div>';
    else{ h+='<div class="scroll"><table><thead><tr><th>年份</th><th>专业</th><th>分数</th><th>原始值</th></tr></thead><tbody>';
      L.forEach(function(r){ h+='<tr><td class="num">'+num(r[1])+'</td><td>'+esc(r[0]||'—')+'</td>'+
        '<td class="num">'+num(r[2])+'</td><td>'+esc(r[3]||'—')+'</td></tr>' });
      h+='</tbody></table></div>'; }
    h+='</div>';

    // 招录
    var A=D.adm[k]||[];
    h+='<div class="sec"><h4>招录数据<span>'+A.length+' 条</span></h4>';
    if(!A.length) h+='<div class="empty-row">无</div>';
    else{ h+='<div class="scroll"><table><thead><tr><th>专业</th><th>年</th><th>拟招</th><th>复试数</th><th>录取数</th>'+
      '<th>最低</th><th>最高</th><th>均分</th><th>复录比</th></tr></thead><tbody>';
      A.forEach(function(r){ h+='<tr><td>'+esc(r[0]||'—')+'</td><td class="num">'+num(r[1])+'</td>'+
        '<td class="num">'+num(r[2])+'</td><td class="num">'+num(r[4])+'</td><td class="num">'+num(r[6])+'</td>'+
        '<td class="num">'+num(r[8])+'</td><td class="num">'+num(r[10])+'</td><td class="num">'+num(r[12])+'</td>'+
        '<td class="num">'+num(r[14])+'</td></tr>' });
      h+='</tbody></table></div>';
      var noted=A.filter(function(r){return r[3]||r[5]||r[7]});
      if(noted.length) h+='<div class="note">原始值含复合描述，例：'+
        esc(noted.slice(0,3).map(function(r){return r[3]||r[5]||r[7]}).join(' ｜ '))+'（已拆主值，原文保留在 *_note）</div>';
    }
    h+='</div>';

    // 导师
    var T=D.tut[k]||[];
    if(T.length){ h+='<div class="sec"><h4>导师<span>'+T.length+' 位</span></h4><div class="scroll">'+
      '<table><thead><tr><th>姓名</th><th>学院/单位</th><th>职称/职务</th><th>研究方向</th><th>来源</th></tr></thead><tbody>';
      T.forEach(function(r){ h+='<tr><td>'+esc(r[0]||'—')+'</td><td>'+esc(r[1]||'—')+'</td>'+
        '<td>'+esc(r[2]||'—')+'</td><td>'+esc(r[3]||'—')+'</td>'+
        '<td>'+(r[4]?'<a href="'+esc(r[4])+'" target="_blank" rel="noopener">链接</a>':'—')+'</td></tr>' });
      h+='</tbody></table></div></div>'; }

    // 考情
    var K=D.kq[k]||[];
    if(K.length){ h+='<div class="sec"><h4>考情明细<span>'+K.length+' 条</span></h4><div class="scroll">'+
      '<table><thead><tr><th>学院</th><th>科目</th><th>年</th><th>线</th><th>拟招</th><th>复试</th><th>录取</th><th>来源</th></tr></thead><tbody>';
      K.forEach(function(r){ h+='<tr><td>'+esc(r[0]||'—')+'</td><td>'+esc(r[1]||'—')+'</td>'+
        '<td class="num">'+num(r[3])+'</td><td class="num">'+num(r[4])+'</td><td class="num">'+num(r[5])+'</td>'+
        '<td class="num">'+num(r[6])+'</td><td class="num">'+num(r[7])+'</td>'+
        '<td>'+(r[12]?'<a href="'+esc(r[12])+'" target="_blank" rel="noopener">链接</a>':'—')+'</td></tr>' });
      h+='</tbody></table></div></div>'; }

    // 2027 改考
    var U=D.u27[k]||[];
    if(U.length){ h+='<div class="sec"><h4>2027 改考动态<span>'+U.length+' 条</span></h4><div class="scroll">'+
      '<table><thead><tr><th>范围</th><th>原科目</th><th>新科目</th><th>生效年</th><th>来源</th></tr></thead><tbody>';
      U.forEach(function(r){ h+='<tr><td>'+esc(r[0]||'—')+'</td><td>'+esc(r[1]||'—')+'</td>'+
        '<td>'+esc(r[2]||'—')+'</td><td class="num">'+num(r[3])+'</td><td>'+esc(r[4]||'—')+'</td></tr>' });
      h+='</tbody></table></div></div>'; }

    // 招生目录
    var C=D.cat[k]||[];
    if(C.length){ h+='<div class="sec"><h4>招生目录<span>'+C.length+' 条</span></h4><div class="scroll">'+
      '<table><thead><tr><th>年</th><th>专业</th><th>学院/范围</th><th>408 科目</th><th>学位</th><th>来源</th></tr></thead><tbody>';
      C.forEach(function(r){ h+='<tr><td class="num">'+num(r[0])+'</td><td>'+esc(r[1]||'—')+'</td>'+
        '<td>'+esc(r[3]||r[2]||'—')+'</td><td>'+esc(r[4]||'—')+'</td><td>'+esc(r[5]||'—')+'</td>'+
        '<td>'+(r[7]?'<a href="'+esc(r[7])+'" target="_blank" rel="noopener">链接</a>':'—')+'</td></tr>' });
      h+='</tbody></table></div></div>'; }

    // 王道链接
    var W=D.wd[k]||[];
    if(W.length){ h+='<div class="sec"><h4>王道考情链接<span>（最多显示 __WDCAP__ 条）</span></h4><div class="kv">';
      W.forEach(function(r){ h+='<div><b>'+esc(r[0]||'—')+'</b> <a href="'+esc(r[1])+'" target="_blank" rel="noopener">打开</a></div>' });
      h+='</div></div>'; }

    // 冲突
    var F=D.cf[k]||[];
    if(F.length){ h+='<div class="sec"><h4>口径冲突登记<span>'+F.length+' 条</span></h4><div class="scroll">'+
      '<table><thead><tr><th>字段</th><th>专业</th><th>原值</th><th>新值</th><th>各方说法</th><th>状态</th><th>依据</th></tr></thead><tbody>';
      F.forEach(function(r){ h+='<tr><td>'+esc(r[0]||'—')+'</td><td>'+esc(r[4]||'—')+'</td>'+
        '<td>'+esc(r[5]||'—')+'</td><td>'+esc(r[6]||'—')+'</td>'+
        '<td>'+esc(claimsText(r[1]))+'</td><td>'+esc(r[2]||'—')+'</td><td>'+esc(r[7]||'—')+'</td></tr>' });
      h+='</tbody></table></div></div>'; }

    // 待补
    var P=D.todo[k]||[];
    if(P.length){ h+='<div class="sec"><h4>待补字段工单<span>'+P.length+' 项</span></h4><div class="kv">'+
      P.map(function(r){return '<div>'+esc(r[0])+' <b>×'+r[1]+'</b></div>'}).join('')+'</div></div>'; }

    return h;
  }
  function kv(k,v){return '<div>'+esc(k)+'：<b>'+v+'</b></div>'}

  /* ---------- 详情：专业 ---------- */
  function majorDetail(c){
    var m=MM[c]; if(!m) return '<div class="empty">未找到</div>';
    var h='<h3>'+esc(m.n)+'</h3><div class="lead">专业代码 <code>'+esc(m.c)+'</code>'+
      (m.dt?' · '+esc(m.dt):'')+(m.cat&&m.cat!==m.dt?' · '+esc(m.cat):'')+
      (m.nz?' · 研招网 408 目录收录 <b>'+m.nz+'</b> 个单位':' · 研招网目录未收录（代码来自校内数据）')+
      ' · 本校库覆盖 <b>'+m.sg.length+'</b> 所</div>';
    if(m.co.length) h+='<div class="sec"><h4>开设学院 / 单位<span>'+m.co.length+' 个</span></h4><div class="kv">'+
      m.co.map(function(x){return '<div>'+esc(x)+'</div>'}).join('')+'</div></div>';
    h+='<div class="sec"><h4>开设院校<span>'+m.sg.length+' 所</span></h4><div class="scroll">'+
      '<table><thead><tr><th>院校</th><th>代码</th><th>省份</th><th>层次</th><th>学院/方向</th></tr></thead><tbody>';
    m.sg.slice().sort(function(a,b){return SM[a].n.localeCompare(SM[b].n,'zh')}).forEach(function(k){
      var s=SM[k]; var o=(s.o||[]).filter(function(x){return x.c===c});
      h+='<tr><td><a href="javascript:void(0)" onclick="__pickS(\''+esc(k)+'\')">'+esc(s.n)+'</a></td>'+
        '<td class="num">'+esc(s.code||'—')+'</td><td>'+esc(s.p||'—')+'</td>'+
        '<td>'+esc(s.t||'—')+'</td><td>'+esc(o.map(function(x){return x.col||x.dir}).filter(Boolean).join(' ｜ ')||'—')+'</td></tr>';
    });
    h+='</tbody></table></div></div>';
    return h;
  }

  /* 供详情内联 onclick 调用 */
  window.__pickS=function(k){ pick('s',k,null); var r=document.querySelector('.row[data-t="s"][data-k="'+k+'"]'); if(r){r.classList.add('on')} };
  window.__pickM=function(c){ pick('m',c,null) };

  /* ---------- 初始化 ---------- */
  var mt=IDX.meta;
  el('hd').textContent=mt.nSchools+' 校 · '+mt.nMajors+' 专业 · '+mt.nOfferings+' 组合 · 索引建于 '+mt.built;
  el('stat').innerHTML='<span>院校 <b>'+mt.nSchools+'</b></span>'+
    '<span>有实质数据 <b>'+mt.nFull+'</b></span>'+
    '<span>仅研招网目录 <b>'+mt.nCatalogOnly+'</b></span>'+
    '<span>仅链接 <b>'+mt.nLinkOnly+'</b></span>'+
    '<span>专业 <b>'+mt.nMajors+'</b></span>'+
    '<span>学校×专业×学院 <b>'+mt.nOfferings+'</b></span>'+
    '<span>别名 <b>'+mt.nAliases+'</b></span>';
  // 下拉
  var ps={},ts={};
  S.forEach(function(s){ if(s.p) ps[s.p]=1; if(s.t) ts[s.t]=1 });
  Object.keys(ps).sort().forEach(function(p){ el('fProv').insertAdjacentHTML('beforeend','<option>'+esc(p)+'</option>') });
  Object.keys(ts).sort(function(a,b){
    var ia=TIER_ORDER.indexOf(a),ib=TIER_ORDER.indexOf(b);
    if(ia<0)ia=99; if(ib<0)ib=99; return ia-ib||a.localeCompare(b,'zh')
  }).forEach(function(t){ el('fTier').insertAdjacentHTML('beforeend','<option>'+esc(t)+'</option>') });
  el('fLvl').insertAdjacentHTML('beforeend',
    '<option value="full">有实质数据</option><option value="catalog_only">仅研招网目录</option><option value="link_only">仅链接</option>');
  var tm=null;
  function deb(){ clearTimeout(tm); tm=setTimeout(render,120) }
  el('q').oninput=deb;
  el('clr').onclick=function(){ el('q').value=''; render(); el('q').focus() };
  ['fProv','fTier','fLvl'].forEach(function(id){ el(id).onchange=render });
  el('q').onkeydown=function(e){
    if(e.key==='Enter'){ var f=el('list').querySelector('.row'); if(f) f.click() }
    if(e.key==='Escape'){ el('q').value=''; render() }
  };
  render();
})();}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
