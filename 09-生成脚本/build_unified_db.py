# -*- coding: utf-8 -*-
"""
build_unified_db.py — 把院校数据用关系数据库打通，全部收拢，按
「学校 → 专业 → 各类数据」三层建模。

层次
----
学校 schools        主键 = 教育部招生单位代码（5 位）；未匹配者 school_key='X-<名>' 且 code_verified=0
专业 majors         主键 = 专业代码（6 位，如 085410）；字典来自研招网 408 目录的 mc/mn/dt
学校×专业 offerings 一行 = 某校某专业某学院的招生单位（学院是属性，不是层）
各类数据（全部挂到 school_key + major_code）
    score_lines      分数线（含历年、口径、国家线标记）
    admissions       招生录取（拟招/复试/录取/最高/最低/均分；含数值化列 + 定性枚举外键）
    score_quantiles  分数分位（408/数学/英语/政治/总分 的 min·p25·中位·p75·max·均值 + 年份级统计）
    score_bands      分数段网格（10 库 stats.bandGrids，逐年份逐科目带）
    stats_yoy        逐年同环比（10 库 stats.yoy）
    tutors           导师（正本 01-导师与规划/085410_22408_导师信息_20260820.md）
    kaoqing          考情明细
    updates_2027     2027 改考
    wangdao_links / sources / conflicts
    catalog          研招目录逐年快照（10 库 catalog_2024~2027）
    dai408_records   Dai408 录取明细（1928 条 / 114 校）
    todo_patch       待补字段清单（177 校）
    field_provenance 字段级来源/精度标记
    national_lines   国家线（年份×门类×A/B 区）
    exam_subjects    招生单元初试科目
    provinces        省份 → 大区
    fill_types       调剂/一志愿 定性文本枚举

统一视图 v_school_major：一行 = 学校×专业，各类数据条数齐全 → "全部收拢"

用法（仓库根目录）：python 09-生成脚本/build_unified_db.py
输出：06-院校数据库/data/kaoyan408.db（**本地生成、不入库**，已加 .gitignore）、crosswalk.json、schools_unified.json
"""
import os
import io
import re
import json
import glob
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D01 = os.path.join(ROOT, '01-导师与规划')
D06 = os.path.join(ROOT, '06-院校数据库', 'data')
D10 = os.path.join(ROOT, '10-录取分数统计', 'data')
DB = os.path.join(D06, 'kaoyan408.db')
CROSSWALK = os.path.join(D06, 'crosswalk.json')
UNIFIED = os.path.join(D06, 'schools_unified.json')
TUTORS_MD = os.path.join(D01, '085410_22408_导师信息_20260820.md')
BUILT = '2026-09-22'


def jload(p):
    with io.open(p, encoding='utf-8') as f:
        return json.load(f)


def snake(k):
    """camelCase/含数字键 → snake_case（line2026→line_2026、nn408avg→nn_408_avg、wdUrl26→wd_url_26）"""
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', k)
    s = re.sub(r'(?<=[A-Za-z])(?=\d)', '_', s)
    s = re.sub(r'(?<=\d)(?=[A-Za-z])', '_', s)
    return s.lower()


def sv(v):
    """SQLite 只接受标量：list/dict 转 JSON 字符串；空串/空容器 → None"""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False) if v else None
    if isinstance(v, str):
        v = v.strip()
        return v if v and v != '—' else None
    return v


# ── 脏值数值化工具（P2）────────────────────────────────────
NUM_RE = re.compile(r'^-?\d+(?:\.\d+)?$')
MULTI_TOKENS = ('计算机', '生物', '人工智能', '软件', '大数据')
MULTI_EXPLICIT = {'调剂9+5', '一志愿复试17人', '085410计划未单列;085404=45/085411=10'}


_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')
_CODE_RE = re.compile(r'^\d{6}$')
# 明确"没有这个数"的标记：出现即判定无主值（原文仍进 *_note）
NO_VALUE_MARKERS = ("未单列", "未公布", "未公示", "未获取", "待补", "待定", "无数据", "不详")
# 可剥离的标签词（用于识别「A一志愿+B调剂」这类扁平两段式）
_LABELS = ("一志愿", "调剂", "专项", "非全", "全日制", "统考", "统招", "计划", "推免", "本部", "联培")
_FLAT2_RE = re.compile(r'^\s*(\d+)\s*\+\s*(\d+)\s*$')


def first_num(s):
    """取字符串里第一个「计数」数字。

    必须跳过两类"假计数"（2026-09-23 修，实测 9 条受影响）：
      · 年份     —— `2026待补(调剂友好)` 里的 2026 是年份，不是拟招数
      · 专业代码 —— `085410计划未单列;085404=45/085411=10` 里的 085410/085404 是专业代码
    命中就继续往后找下一个数字；全不合格返回 None。
    """
    for m in re.finditer(r'\d+', str(s)):
        t = m.group(0)
        if _YEAR_RE.match(t) and 2019 <= int(t) <= 2030:
            continue
        if _CODE_RE.match(t) and (t.startswith(("08", "14")) or t.startswith("083")):
            continue
        return int(t)
    return None


def flat_sum(s):
    """识别「A一志愿+B调剂」「8(一志愿)+12调剂」这类扁平两段式 → A+B（总人数）。

    只处理"剥掉标签后恰好是 `数字+数字`"的情形；带嵌套括号的
    （如 `约90(86+4专项)`，90 本身就是总数）不处理，避免重复相加。
    """
    t = str(s)
    for lb in _LABELS:
        t = t.replace("(" + lb + ")", "").replace("（" + lb + "）", "").replace(lb, "")
    m = _FLAT2_RE.match(t)
    return (int(m.group(1)) + int(m.group(2))) if m else None


def is_multi(s):
    """多值：一条文本里按子方向/子专业分列的多个计数（主值仍取首数字，note 前缀「多值:」）"""
    if s in MULTI_EXPLICIT:
        return True
    if '(' in s or '（' in s:
        return False
    return sum(1 for t in MULTI_TOKENS if t in s) >= 2


def num_cols(v):
    """脏值 → (value:int|None, note:str|None)；纯数值只给 value；无数字 → (None, 原文)"""
    if v is None:
        return None, None
    s = str(v).strip()
    if not s:
        return None, None
    if NUM_RE.match(s):
        return int(round(float(s))), None
    if any(k in s for k in NO_VALUE_MARKERS):      # 「085410未单列」「2026待补」→ 无主值
        return None, s
    fs = flat_sum(s)                               # 「0一志愿+38调剂」→ 38（总人数）
    if fs is not None:
        return fs, '合计:' + s
    n = first_num(s)
    if n is None:
        return None, s
    return n, ('多值:' + s if is_multi(s) else s)


# ── 专业关键词映射（顺序敏感：具体在前，泛化在后）────────────────
MAJOR_KEYWORDS = [
    ('085410', ['人工智能', '智能系统', 'ai方向']),
    ('085404', ['计算机技术', '计算机专硕']),
    ('085412', ['网络与信息安全', '信息安全', '网安']),
    ('085405', ['软件工程']),
    ('085411', ['大数据']),
    ('085408', ['光电信息工程']),
    ('085400', ['电子信息']),
    ('081200', ['计算机科学与技术']),
    ('083500', ['软件工程学硕']),
    ('083900', ['网络空间安全']),
    ('140500', ['智能科学与技术']),
]
CODE_RE = re.compile(r'0[18]\d{4}|140500')


def infer_major(text):
    """从任意文本推断专业代码；返回 (code, 'extracted'|'inferred'|None)"""
    if not text:
        return None, None
    m = CODE_RE.search(text)
    if m:
        return m.group(0), 'extracted'
    low = text.lower()
    for code, kws in MAJOR_KEYWORDS:
        for kw in kws:
            if kw in low:
                return code, 'inferred'
    return None, None


# ── 1. 读源 ───────────────────────────────────────────────
meta06 = jload(os.path.join(D06, 'meta.json'))
yz_items = jload(os.path.join(D06, 'yz408_catalog.json'))['items']
idx10 = jload(os.path.join(D10, 'schools_index.json'))
cat10 = []
for y in (2024, 2025, 2026, 2027):
    p = os.path.join(D10, 'catalog_%d.json' % y)
    if os.path.exists(p):
        cat10.append((y, jload(p)))

s06 = {}
for f in sorted(glob.glob(os.path.join(D06, 'schools', '*.json'))):
    d = jload(f)
    d['_file'] = os.path.basename(f)
    s06[d['name']] = d

s10 = {}
meta10 = {s['name']: s for s in idx10}
for s in idx10:
    p = os.path.join(D10, 'schools', '%s.json' % s['id'])
    if os.path.exists(p):
        s10[s['name']] = jload(p)

score_matrix = jload(os.path.join(D06, 'score_matrix.json'))
todo_patch_list = jload(os.path.join(D06, 'todo_patch_list.json'))
wangdao_all = jload(os.path.join(D06, 'wangdao_links_all.json'))
dai408 = jload(os.path.join(D06, 'dai408_scores.json'))

code_of, prov_of = {}, {}
for x in yz_items:
    code_of.setdefault(x['s'], x['code'])
    prov_of.setdefault(x['s'], x.get('p'))


def norm(s):
    """仅去括号字符/空格/连接符，保留括号内内容（校区信息不可丢）"""
    return re.sub(r'[（()）\s·、\-]', '', s)


norm_index = {}
for nm, cd in code_of.items():
    norm_index.setdefault(norm(nm), (nm, cd))
MANUAL = {}


def resolve(name):
    if name in code_of:
        return code_of[name], 1
    if name in MANUAL:
        return MANUAL[name], 1
    n = norm(name)
    if n in norm_index:
        return norm_index[n][1], 1
    return None, 0


# ── 2. 建库（幂等：DROP + 重建，不依赖上次状态）───────────────
if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
con.execute('PRAGMA foreign_keys=ON')
cur = con.cursor()

cur.executescript('''
DROP VIEW  IF EXISTS v_school_major;
DROP VIEW  IF EXISTS v_school_all;
DROP TABLE IF EXISTS field_provenance;
DROP TABLE IF EXISTS fill_types;
DROP TABLE IF EXISTS todo_patch;
DROP TABLE IF EXISTS catalog;
DROP TABLE IF EXISTS score_bands;
DROP TABLE IF EXISTS stats_yoy;
DROP TABLE IF EXISTS exam_subjects;
DROP TABLE IF EXISTS national_lines;
DROP TABLE IF EXISTS provinces;
DROP TABLE IF EXISTS dai408_records;
DROP TABLE IF EXISTS conflicts;
DROP TABLE IF EXISTS sources;
DROP TABLE IF EXISTS wangdao_links;
DROP TABLE IF EXISTS updates_2027;
DROP TABLE IF EXISTS kaoqing;
DROP TABLE IF EXISTS tutors;
DROP TABLE IF EXISTS score_quantiles;
DROP TABLE IF EXISTS admissions;
DROP TABLE IF EXISTS score_lines;
DROP TABLE IF EXISTS offerings;
DROP TABLE IF EXISTS school_aliases;
DROP TABLE IF EXISTS majors;
DROP TABLE IF EXISTS schools;
DROP TABLE IF EXISTS dataset_sources;

CREATE TABLE schools (
  school_key TEXT PRIMARY KEY,
  code TEXT UNIQUE, code_verified INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL, province TEXT, province_raw TEXT, region TEXT, tier TEXT,
  is985 INTEGER, is211 INTEGER, is_dfc INTEGER, cs_rank INTEGER,
  in_lib06 INTEGER DEFAULT 0, in_lib10 INTEGER DEFAULT 0,
  in_yz408 INTEGER DEFAULT 0, in_cb INTEGER DEFAULT 0,
  cb_id INTEGER, lib06_file TEXT, note TEXT,
  category_guess TEXT, nn_candidates TEXT, cross_refs TEXT,
  in_tj_list TEXT, in_key_list TEXT, deep_ref TEXT
);

CREATE TABLE school_aliases (
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  alias TEXT NOT NULL, src TEXT NOT NULL,
  PRIMARY KEY (school_key, alias, src)
);

CREATE TABLE majors (
  major_code TEXT PRIMARY KEY,
  major_name TEXT, degree_type TEXT, category TEXT,
  in_yz408 INTEGER DEFAULT 0, n_yz408 INTEGER DEFAULT 0
);

CREATE TABLE provinces (
  province TEXT PRIMARY KEY, region TEXT
);

CREATE TABLE offerings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT REFERENCES majors(major_code),
  major_source TEXT,
  college TEXT, category TEXT, tier TEXT, province TEXT, region TEXT,
  subject_class TEXT, direction TEXT, ai_tag TEXT, src TEXT, src_label TEXT,
  kaoqing_url TEXT, remark TEXT, note TEXT,
  raw TEXT,
  scope TEXT, line_delta TEXT, line_ultimate_2026 TEXT,
  nn_college TEXT, nn_prog TEXT, nn_subjects TEXT, nn_url TEXT,
  wd_count TEXT, wd_url_26 TEXT, wd_years TEXT,
  cy_code TEXT, cy_avg TEXT, cy_retest TEXT, cy_admit TEXT,
  scope2 TEXT, subject_claim_2026 TEXT, subject_status TEXT, fill_2026 TEXT
);

CREATE TABLE score_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, offering_id INTEGER REFERENCES offerings(id),
  year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  line_type TEXT, value REAL CHECK(value IS NULL OR value GLOB '[0-9]*'),
  basis TEXT, raw_value TEXT, value_kind TEXT
);

CREATE TABLE admissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, offering_id INTEGER REFERENCES offerings(id),
  year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  plan TEXT, fill TEXT, retest_cnt TEXT, admit_cnt TEXT,
  admit_max TEXT, admit_min TEXT, admit_avg TEXT,
  ratio_retest TEXT, ratio_apply TEXT,
  nn_408avg TEXT, nn_rate TEXT, heat_net TEXT, heat_comp TEXT,
  plan_value INTEGER CHECK(plan_value IS NULL OR plan_value GLOB '[0-9]*'), plan_note TEXT,
  fill_value INTEGER CHECK(fill_value IS NULL OR fill_value GLOB '[0-9]*'), fill_note TEXT,
  retest_cnt_value INTEGER CHECK(retest_cnt_value IS NULL OR retest_cnt_value GLOB '[0-9]*'), retest_cnt_note TEXT,
  admit_cnt_value INTEGER CHECK(admit_cnt_value IS NULL OR admit_cnt_value GLOB '[0-9]*'), admit_cnt_note TEXT,
  admit_max_value INTEGER CHECK(admit_max_value IS NULL OR admit_max_value GLOB '[0-9]*'), admit_max_note TEXT,
  admit_min_value INTEGER CHECK(admit_min_value IS NULL OR admit_min_value GLOB '[0-9]*'), admit_min_note TEXT,
  admit_avg_value INTEGER CHECK(admit_avg_value IS NULL OR admit_avg_value GLOB '[0-9]*'), admit_avg_note TEXT,
  fill_type_code TEXT REFERENCES fill_types(code),
  -- 唯一键必须含 offering_id（它已编码 college）：三层模型里"学院"是 offering 的属性，
  -- 按 (school_key,major_code,year) 折叠会把"同校同专业不同学院"压成一行 → 数据丢失
  UNIQUE(offering_id, year)
);

CREATE TABLE fill_types (
  code TEXT PRIMARY KEY, label TEXT
);

CREATE TABLE score_quantiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, offering_id INTEGER REFERENCES offerings(id),
  year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  program_name TEXT, exam_408_type TEXT, source_level TEXT, source_url TEXT,
  subject TEXT, label TEXT,
  count INTEGER CHECK(count IS NULL OR count GLOB '[0-9]*'),
  min REAL, p25 REAL, median REAL, p75 REAL, max REAL, mean REAL,
  ci_low REAL, ci_high REAL,
  record_count INTEGER, enrolled_count INTEGER, retest_count INTEGER,
  single_fail_count INTEGER, pool_count INTEGER, known_admit_count INTEGER,
  dist_population TEXT, retest_elimination_rate REAL,
  national_total_line INTEGER, national_408_line INTEGER,
  retest_weight TEXT, rank_shift TEXT, warnings TEXT,
  retest_line_total REAL, admit_min_total REAL
);

CREATE TABLE score_bands (
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  band_key TEXT NOT NULL, band_label TEXT, full REAL, step REAL,
  cols_json TEXT, rows_json TEXT,
  PRIMARY KEY (school_key, major_code, year, band_key)
);

CREATE TABLE stats_yoy (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, program_name TEXT,
  prev_year INTEGER CHECK(prev_year IS NULL OR prev_year BETWEEN 2019 AND 2027),
  curr_year INTEGER CHECK(curr_year IS NULL OR curr_year BETWEEN 2019 AND 2027),
  prev_relative REAL, curr_relative REAL, delta REAL,
  significant INTEGER, raw_delta REAL, unavailable_reason TEXT
);

CREATE TABLE tutors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), major_code TEXT,
  school_name TEXT, dept TEXT, name TEXT, title TEXT,
  direction TEXT, url TEXT, note TEXT, src TEXT
);

CREATE TABLE kaoqing (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), major_code TEXT,
  college TEXT, tier TEXT, subjects TEXT, program TEXT, batch TEXT,
  year INTEGER, line_value REAL, plan TEXT, retest_cnt TEXT, admit_cnt TEXT,
  admit_max TEXT, admit_min TEXT, admit_avg TEXT,
  scope TEXT, url TEXT, verify TEXT
);

CREATE TABLE exam_subjects (
  offering_id INTEGER NOT NULL REFERENCES offerings(id),
  subject_key TEXT NOT NULL, subject_label TEXT, src TEXT,
  PRIMARY KEY (offering_id, subject_key)
);

CREATE TABLE updates_2027 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), major_code TEXT,
  school_name TEXT, tier TEXT, scope TEXT,
  subject_old TEXT, subject_new TEXT, effective_year TEXT, source TEXT, note TEXT
);

CREATE TABLE wangdao_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), year_label TEXT, url TEXT
);

CREATE TABLE sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), label TEXT, url TEXT, tier TEXT
);

CREATE TABLE conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key), major_code TEXT, scope TEXT,
  field TEXT, old_value TEXT, new_value TEXT, reason TEXT,
  claims TEXT, status TEXT, action TEXT, refs TEXT
);

CREATE TABLE catalog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  major_code TEXT, college TEXT, scope TEXT, exam_408_type TEXT, degree_type TEXT,
  note TEXT, changed_from TEXT, source_level TEXT, source_url TEXT
);
-- 说明：catalog 不设自然唯一键。实测 4 年共 631 条 program，**全部互不相同**（含 scope 后仍 631 条），
-- 按 (school_key,year,major_code) 建唯一键会丢掉 139 条"同校同专业同年多学院"的 program。
-- 幂等性由建库时的 DROP+CREATE 保证，不依赖唯一键。查询用下方索引。
CREATE INDEX idx_cat_school_year ON catalog(school_key, year, major_code);

CREATE TABLE dai408_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT REFERENCES schools(school_key),
  s TEXT, p TEXT, lv TEXT, c TEXT, d TEXT, dc TEXT, dt TEXT,
  y INTEGER CHECK(y IS NULL OR y BETWEEN 2019 AND 2027),
  sid INTEGER, ex TEXT, fee TEXT, rt TEXT,
  plan INTEGER, act INTEGER, retest INTEGER, adm INTEGER,
  smin REAL, smax REAL, savg REAL, smed REAL,
  m408 REAL, mmath REAL, line TEXT
);

CREATE TABLE todo_patch (
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  field_name TEXT NOT NULL, n_missing INTEGER,
  PRIMARY KEY (school_key, field_name)
);

CREATE TABLE field_provenance (
  table_name TEXT NOT NULL, row_id INTEGER NOT NULL, field_name TEXT NOT NULL,
  source_tier TEXT, confidence REAL, approx_flag INTEGER DEFAULT 0,
  PRIMARY KEY (table_name, row_id, field_name)
);

CREATE TABLE national_lines (
  year INTEGER CHECK(year IS NULL OR year BETWEEN 2019 AND 2027),
  subject_category TEXT NOT NULL, zone TEXT NOT NULL,
  total_line INTEGER CHECK(total_line IS NULL OR total_line GLOB '[0-9]*'),
  subject_408_line INTEGER CHECK(subject_408_line IS NULL OR subject_408_line GLOB '[0-9]*'),
  src TEXT,
  caveat TEXT DEFAULT '人工汇总自 score_lines 文本与 06 备注，非官方国家线表；正式口径以研招网/教育部公布为准',
  PRIMARY KEY (year, subject_category, zone)
);

CREATE TABLE dataset_sources (
  id TEXT PRIMARY KEY, label TEXT, url TEXT, fetched_at TEXT,
  license TEXT, immutable INTEGER DEFAULT 0, note TEXT
);
''')

# ── 3. 专业字典 ───────────────────────────────────────────
majors = {}
for x in yz_items:
    mc, mn, dt = x.get('mc'), x.get('mn'), x.get('dt')
    if not mc:
        continue
    m = majors.setdefault(mc, {'name': mn, 'degree': dt, 'n': 0})
    m['n'] += 1
    if mn and not m['name']:
        m['name'] = mn
    if dt:
        m['degree'] = dt
for code, v in sorted(majors.items()):
    cat = '专业学位' if code.startswith('0854') else ('交叉学科' if code.startswith('14') else '学术学位')
    cur.execute('INSERT OR REPLACE INTO majors(major_code,major_name,degree_type,category,in_yz408,n_yz408) VALUES(?,?,?,?,?,?)',
                (code, v['name'], v['degree'], cat, 1, v['n']))

# 06/10 中出现、但不在研招网 408 目录里的专业代码 → 补录（in_yz408=0）
EXTRA_MAJOR_NAMES = {
    '085401': '新一代电子信息技术', '085402': '通信工程', '085403': '集成电路工程',
    '085406': '控制工程', '085407': '仪器仪表工程', '085408': '光电信息工程',
    '080900': '电子科学与技术', '081000': '信息与通信工程', '081100': '控制科学与工程',
    '081104': '模式识别与智能系统', '081201': '计算机系统结构',
    '081202': '计算机软件与理论', '081203': '计算机应用技术',
    '085409': '生物医学工程', '085901': '土木工程',
}


def ensure_major(code):
    """确保 major_code 在字典中（供外键使用）；未知代码补录并标 in_yz408=0"""
    if not code:
        return None
    if code in majors:
        return code
    cat = '专业学位' if code.startswith('0854') else ('交叉学科' if code.startswith('14') else '学术学位')
    cur.execute('INSERT OR IGNORE INTO majors(major_code,major_name,degree_type,category,in_yz408,n_yz408) '
                'VALUES(?,?,?,?,0,0)', (code, EXTRA_MAJOR_NAMES.get(code), None, cat))
    majors[code] = {'name': EXTRA_MAJOR_NAMES.get(code), 'degree': None, 'n': 0}
    return code

# ── 4. 学校（全部收拢）────────────────────────────────────
seen = set()


# 省名归一（实测库内只有 '内蒙'/'内蒙古' 一处不统一；保留原始写法到 schools.province_raw 以便溯源）
PROV_FIX = {'内蒙': '内蒙古'}


def norm_prov(p):
    if not p:
        return p
    p = str(p).strip()
    return PROV_FIX.get(p, p)


# 来源权威度分级（规则见 docs/数据源与冲突裁定.md §1）：
#   T1 官方一手（学校/学院/研招网）> T2 官方转载 > T3 第三方已整理 > T4 仓库内/其他
SRC_T1 = ('.edu.cn', '.gov.cn', 'yz.chsi.com.cn')
SRC_T2 = ('chinakaoyan.com', 'eduego.com', 'kaoyanziyuan.org')
SRC_T3 = ('ludengkaoyan.com', 'ludengkefu.com', 'noobdream.com', 'iqihang.com',
          'kaoyan365.cn', 'koolearn.com', 'kaoyan.cn', 'kaoyana.com',
          'codebrick.tech', 'awarer.top', 'xdf.cn', 'shunyoutech.com', 'yanshuoshi.com')


def src_tier(url):
    """按 docs/数据源与冲突裁定.md §1 给来源分级（冲突裁定的取证顺序）"""
    if not url:
        return 'T4-仓库内'
    u = str(url).lower()
    if any(k in u for k in SRC_T1):
        return 'T1-官方'
    if any(k in u for k in SRC_T2):
        return 'T2-官方转载'
    if any(k in u for k in SRC_T3):
        return 'T3-第三方整理'
    return 'T4-其他'


def upsert_school(name, src, m10=None):
    cd, ver = resolve(name)
    key = cd or 'X-' + name
    if key in seen:
        cur.execute('UPDATE schools SET in_lib06=MAX(in_lib06,?), in_lib10=MAX(in_lib10,?), '
                    'in_yz408=MAX(in_yz408,?) WHERE school_key=?',
                    (1 if src == 'lib06' else 0, 1 if src == 'lib10' else 0,
                     1 if src == 'yz408' else 0, key))
        cur.execute('INSERT OR IGNORE INTO school_aliases(school_key,alias,src) VALUES(?,?,?)', (key, name, src))
        return key
    seen.add(key)
    d06 = s06.get(name)
    m10 = m10 or {}
    prov = m10.get('location') or prov_of.get(name)
    if not prov and d06 and d06.get('units'):
        prov = d06['units'][0].get('province')
    region = None
    if d06:
        for u in d06.get('units') or []:
            if u.get('region'):
                region = u['region']
                break
    tier = (d06 or {}).get('units', [{}])[0].get('tier') if d06 and d06.get('units') else None
    if not tier:
        tier = '985' if m10.get('is985') else '211' if m10.get('is211') else '双一流' if m10.get('isDoubleFirstClass') else ('双非' if m10 else None)
    cur.execute('''INSERT INTO schools(school_key,code,code_verified,name,province,province_raw,region,tier,
                   is985,is211,is_dfc,cs_rank,in_lib06,in_lib10,in_yz408,in_cb,cb_id,lib06_file,note,
                   category_guess,nn_candidates,cross_refs,in_tj_list,in_key_list,deep_ref)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (key, cd, ver, name, norm_prov(prov), prov, region, tier,
                 m10.get('is985'), m10.get('is211'), m10.get('isDoubleFirstClass'), m10.get('csRank'),
                 1 if src == 'lib06' else 0, 1 if src == 'lib10' else 0, 1 if src == 'yz408' else 0, 0,
                 m10.get('id'), (d06 or {}).get('_file'), (d06 or {}).get('note'),
                 sv((d06 or {}).get('categoryGuess')), sv((d06 or {}).get('nnCandidates')),
                 sv((d06 or {}).get('crossRefs')), sv((d06 or {}).get('inTJList')),
                 sv((d06 or {}).get('inKeyList')), sv((d06 or {}).get('deepRef'))))
    cur.execute('INSERT OR IGNORE INTO school_aliases(school_key,alias,src) VALUES(?,?,?)', (key, name, src))
    return key


for n in sorted(s06):
    upsert_school(n, 'lib06')
for n in sorted(s10):
    upsert_school(n, 'lib10', meta10.get(n))
for n in sorted(code_of):
    upsert_school(n, 'yz408')
cur.execute('UPDATE schools SET in_cb=1 WHERE cb_id IS NOT NULL')

key06 = {n: (resolve(n)[0] or 'X-' + n) for n in s06}
key10 = {n: (resolve(n)[0] or 'X-' + n) for n in s10}

# ── 5. 学校×专业（offerings）+ 各类数据 ────────────────────
off_map = {}          # (school_key, major_code) → offering id（首条）
exam_rows = set()     # (offering_id, subject_key, label, src)
n_off = n_line = n_adm = n_q = n_band = n_yoy = 0
for name, d in s06.items():
    key = key06[name]
    for u in d.get('units') or []:
        text = ' '.join(str(u.get(k) or '') for k in ('direction', 'note', 'college', 'nnProg', 'nnCollege'))
        mc, msrc = infer_major(text)
        mc = ensure_major(mc)
        cur.execute('''INSERT INTO offerings(school_key,major_code,major_source,college,category,tier,province,region,
                       subject_class,direction,ai_tag,src,src_label,kaoqing_url,remark,note,raw,
                       scope,line_delta,line_ultimate_2026,nn_college,nn_prog,nn_subjects,nn_url,
                       wd_count,wd_url_26,wd_years,cy_code,cy_avg,cy_retest,cy_admit,
                       scope2,subject_claim_2026,subject_status,fill_2026)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, msrc, sv(u.get('college')), sv(u.get('category')), sv(u.get('tier')), norm_prov(sv(u.get('province'))), sv(u.get('region')),
                     sv(u.get('subjectClass')), sv(u.get('direction')), sv(u.get('aiTag')), sv(u.get('src')), sv(u.get('srcLabel')),
                     sv(u.get('kaoqingUrl')), sv(u.get('remark')), sv(u.get('note')), json.dumps(u, ensure_ascii=False),
                     sv(u.get('scope')), sv(u.get('lineDelta')), sv(u.get('lineUltimate2026')),
                     sv(u.get('nnCollege')), sv(u.get('nnProg')), sv(u.get('nnSubjects')), sv(u.get('nnUrl')),
                     sv(u.get('wdCount')), sv(u.get('wdUrl26')), sv(u.get('wdYears')),
                     sv(u.get('cyCode')), sv(u.get('cyAvg')), sv(u.get('cyRetest')), sv(u.get('cyAdmit')),
                     sv(u.get('scope2')), sv(u.get('subjectClaim2026')), sv(u.get('subjectStatus')), sv(u.get('fill2026'))))
        oid = cur.lastrowid
        n_off += 1
        if mc and (key, mc) not in off_map:
            off_map[(key, mc)] = oid
        if u.get('nnSubjects'):
            exam_rows.add((oid, 'nn_subjects', str(u['nnSubjects']), 'lib06'))
        # 分数线：2026 + 历年
        if u.get('line2026') is not None:
            raw = str(u['line2026'])
            m = re.search(r'\d+', raw)
            cur.execute('''INSERT INTO score_lines(school_key,major_code,offering_id,year,line_type,value,basis,raw_value)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (key, mc, oid, 2026, '复试线', float(m.group(0)) if m else None,
                         '国家线' if '国家线' in raw else ('B区' if 'B区' in raw else '院线/专业线'), raw))
            n_line += 1
        for y, v in (u.get('linesByYear') or {}).items():
            if v is None:
                continue
            raw = str(v)
            m = re.search(r'\d+', raw)
            cur.execute('''INSERT INTO score_lines(school_key,major_code,offering_id,year,line_type,value,basis,raw_value)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (key, mc, oid, int(y) if str(y).isdigit() else None, '复试线',
                         float(m.group(0)) if m else None, '历年线', raw))
            n_line += 1
        cur.execute('''INSERT OR REPLACE INTO admissions(school_key,major_code,offering_id,year,plan,fill,retest_cnt,admit_cnt,
                       admit_max,admit_min,admit_avg,ratio_retest,ratio_apply,nn_408avg,nn_rate,heat_net,heat_comp)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, oid, 2026, u.get('plan2026'), u.get('fill'), u.get('retestCnt'), u.get('admitCnt'),
                     u.get('admitMax'), u.get('admitMin'), u.get('admitAvg'), u.get('ratioRetest'),
                     u.get('ratioApply'), u.get('nn408avg'), u.get('nnRate'), u.get('heatNet'), u.get('heatComp')))
        n_adm += 1
    for u in d.get('kaoqingDetail2026') or []:
        text = ' '.join(str(u.get(k) or '') for k in ('program', 'scope', 'college'))
        mc = ensure_major(infer_major(text)[0])
        lv = re.search(r'\d+', str(u.get('line2026') or ''))
        cur.execute('''INSERT INTO kaoqing(school_key,major_code,college,tier,subjects,program,batch,year,
                       line_value,plan,retest_cnt,admit_cnt,admit_max,admit_min,admit_avg,scope,url,verify)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, u.get('college'), u.get('tier'), u.get('subjects'), u.get('program'), u.get('batch'),
                     2026, float(lv.group(0)) if lv else None, u.get('plan'), u.get('retestCnt'), u.get('admitCnt'),
                     u.get('admitMax'), u.get('admitMin'), u.get('admitAvg'), u.get('scope'), u.get('url'), u.get('verify')))
        if u.get('subjects') and mc:
            oid = off_map.get((key, mc))
            if oid:
                exam_rows.add((oid, 'kaoqing_subjects', str(u['subjects']), 'lib06'))
    for u in d.get('updates2027') or []:
        mc = ensure_major(infer_major(str(u.get('专业/范围') or ''))[0])
        cur.execute('''INSERT INTO updates_2027(school_key,major_code,school_name,tier,scope,subject_old,
                       subject_new,effective_year,source,note) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, u.get('院校') or name, u.get('层次'), u.get('专业/范围'),
                     u.get('原科目'), u.get('新科目'), u.get('生效年份'), u.get('来源'), u.get('备注')))
        oid = off_map.get((key, mc)) if mc else None
        if oid:
            if u.get('原科目'):
                exam_rows.add((oid, 'update_subject_old', str(u['原科目']), 'lib06'))
            if u.get('新科目'):
                exam_rows.add((oid, 'update_subject_new', str(u['新科目']), 'lib06'))
    for y, url in (d.get('wangdaoLinks') or {}).items():
        if url:
            cur.execute('INSERT INTO wangdao_links(school_key,year_label,url) VALUES(?,?,?)', (key, y, url))
    for u in d.get('sources') or []:
        cur.execute('INSERT INTO sources(school_key,label,url,tier) VALUES(?,?,?,?)',
                    (key, u.get('label'), u.get('url'), src_tier(u.get('url'))))
    for u in d.get('conflicts') or []:
        mc = ensure_major(infer_major(str(u.get('field') or '') + str(u.get('reason') or ''))[0])
        cur.execute('''INSERT INTO conflicts(school_key,major_code,scope,field,old_value,new_value,reason,refs)
                       VALUES(?,?,?,?,?,?,?,?)''',
                    (key, mc, 'in-school', u.get('field'), u.get('old'), u.get('new'), u.get('reason'),
                     json.dumps(u.get('sources'), ensure_ascii=False)))

for u in jload(os.path.join(D06, 'conflicts_registry.json')).get('items', []):
    nm = u.get('school') or ''
    key = resolve(nm)[0] or 'X-' + nm
    mc = ensure_major(infer_major(str(u.get('field') or '') + str(u.get('action') or ''))[0])
    cur.execute('''INSERT INTO conflicts(school_key,major_code,scope,field,claims,status,action)
                   VALUES(?,?,?,?,?,?,?)''',
                (key, mc, 'cross-school', u.get('field'), json.dumps(u.get('claims'), ensure_ascii=False),
                 u.get('status'), u.get('action')))

# ── 5.5 导师（正本 = 01 库 Markdown 表格）──────────────────
MD_LINK = re.compile(r'\[[^\]]*\]\((https?://[^)\s]+)\)')


def load_tutors_md(path):
    """解析 01 库导师正本 Markdown 表格 → 行字典（表头 # | 院校 | 学院/单位 | 导师 | 职称/职务 | 研究方向 | 来源 | 备注）"""
    out = []
    if not os.path.exists(path):
        return out
    lines = io.open(path, encoding='utf-8').read().splitlines()
    started = False
    for ln in lines:
        if not ln.strip().startswith('|'):
            if started:
                break
            continue
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        if not started:
            if cells[:2] == ['#', '院校']:
                started = True
            continue
        if all(re.fullmatch(r':?-{2,}:?', c or '-') for c in cells):
            continue
        if len(cells) < 8:
            continue
        m = MD_LINK.search(cells[6])
        out.append({'school': cells[1], 'dept': cells[2], 'name': cells[3],
                    'title': cells[4], 'direction': cells[5],
                    'url': m.group(1) if m else None, 'note': cells[7]})
    return out


n_tut = 0
for t in load_tutors_md(TUTORS_MD):
    nm = t['school']
    key = resolve(nm)[0] or 'X-' + nm
    if key not in seen:
        upsert_school(nm, 'lib01')
    cur.execute('''INSERT INTO tutors(school_key,major_code,school_name,dept,name,title,direction,url,note,src)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (key, '085410', nm, t['dept'], t['name'], t['title'], t['direction'], t['url'],
                 None if t['note'] in (None, '—') else t['note'], 'lib07'))
    n_tut += 1

# 10 侧：分数分位（挂到 school_key + major_code）+ 年份级统计 + 分数带 + 同环比
for name, d in s10.items():
    key = key10[name]
    for p in d.get('programs') or []:
        pname = p.get('programName') or ''
        mc = ensure_major(infer_major(pname)[0])
        st = p.get('stats') or {}
        for y in st.get('years') or []:
            for s in y.get('subjects') or []:
                cur.execute('''INSERT INTO score_quantiles(school_key,major_code,year,program_name,exam_408_type,
                               source_level,source_url,subject,label,count,min,p25,median,p75,max,mean,ci_low,ci_high,
                               record_count,enrolled_count,retest_count,single_fail_count,pool_count,known_admit_count,
                               dist_population,retest_elimination_rate,national_total_line,national_408_line,
                               retest_weight,rank_shift,warnings,retest_line_total,admit_min_total)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (key, mc, y.get('year'), pname, y.get('exam408Type'), y.get('sourceLevel'),
                             y.get('sourceUrl'), s.get('key'), s.get('label'), s.get('count'),
                             s.get('min'), s.get('p25'), s.get('median'), s.get('p75'), s.get('max'),
                             s.get('mean'), s.get('ciLow'), s.get('ciHigh'),
                             y.get('recordCount'), y.get('enrolledCount'), y.get('retestCount'),
                             y.get('singleFailCount'), y.get('poolCount'), y.get('knownAdmitCount'),
                             y.get('distPopulation'), y.get('retestEliminationRate'),
                             y.get('nationalTotalLine'), y.get('national408Line'),
                             sv(y.get('retestWeight')), sv(y.get('rankShift')), sv(y.get('warnings')),
                             y.get('retestLineTotal'), y.get('admitMinTotal')))
                n_q += 1
            oid = off_map.get((key, mc)) if mc else None
            if oid:
                for s in y.get('subjects') or []:
                    exam_rows.add((oid, s.get('key'), s.get('label'), 'lib10'))
        for yy in st.get('yoy') or []:
            cur.execute('''INSERT INTO stats_yoy(school_key,major_code,program_name,prev_year,curr_year,
                           prev_relative,curr_relative,delta,significant,raw_delta,unavailable_reason)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (key, mc, pname, yy.get('prevYear'), yy.get('currYear'),
                         yy.get('prevRelative'), yy.get('currRelative'), yy.get('delta'),
                         1 if yy.get('significant') else 0, yy.get('rawDelta'), yy.get('unavailableReason')))
            n_yoy += 1
        for b in st.get('bandGrids') or []:
            for col in b.get('cols') or []:
                cur.execute('''INSERT OR REPLACE INTO score_bands(school_key,major_code,year,band_key,
                               band_label,full,step,cols_json,rows_json) VALUES(?,?,?,?,?,?,?,?,?)''',
                            (key, mc, col.get('year'), b.get('key'), b.get('label'), b.get('full'), b.get('step'),
                             json.dumps(col, ensure_ascii=False), json.dumps(b.get('rows'), ensure_ascii=False)))
                n_band += 1

# 数据源登记
for r in [
    ('lib06', '本仓库择校库（177 校）', 'https://github.com/Laz8Noy/kaoyan408-share', '2026-09-13', 'CC BY 4.0', 0,
     '可编辑正本；最近全量补全 2026-09-13（v2）'),
    ('lib10', 'CodeBrick 录取分数统计（96 校）', 'https://www.codebrick.tech/practice/school-admit', '2026-09-06', '版权归原站', 1, '无抓取脚本，一次性快照'),
    ('yz408', '研招网 2026 硕士专业目录（第四科=408）', 'https://yz.chsi.com.cn/zsml/', '2026-09-20', '官方公开', 1, '招生单位代码来源'),
    ('dai408', 'Dai408 录取数据库（公益参考版）', 'https://awarer.top/', '2026-09-21', '公益参考', 1, '生成脚本已断（ext/ 缺失）'),
    ('ludeng', '路灯考研 · 逐校分数线/录取分数', 'https://www.ludengkaoyan.com/major83/fsx/', '2026-09-23', '第三方整理，版权归原站', 0,
     'T3 源：085410 全院校分数线汇总页 + 逐校 school{id}/qrz/fsx/；含录取最低/最高分。2026 行多为国家线口径'),
    ('chinakaoyan', '中国考研网 · 官方复试线公告转载', 'https://www.chinakaoyan.com/', '2026-09-23', '转载，版权归原站', 0,
     'T2 源：转载各校研究生院公告全文并标注"来源：XX研究生院"；官方站不可达时用于取证'),
    ('kaoyan_cn', '掌上考研 · 逐校分数线查询', 'https://www.kaoyan.cn/', '2026-09-23', '第三方整理，版权归原站', 0,
     'T3 源：kaoyan.cn/school/{id}/score'),
    ('conflict_policy', '冲突裁定规则（本仓库）', 'docs/数据源与冲突裁定.md', '2026-09-23', 'CC BY 4.0', 0,
     'T1~T4 取证顺序 + 已裁定 4 例 + 待裁定 8 例；冲突必须先查此文件'),
]:
    cur.execute('INSERT OR REPLACE INTO dataset_sources(id,label,url,fetched_at,license,immutable,note) VALUES(?,?,?,?,?,?,?)', r)

# ── 5.6 新表：provinces / national_lines / exam_subjects / catalog / dai408 / todo_patch ──
# provinces
prov = {}
for (p, r) in cur.execute('SELECT province, region FROM schools'):
    if p:
        prov.setdefault(p, r)
for (p, r) in cur.execute('SELECT province, region FROM offerings'):
    if p and (p not in prov or prov.get(p) is None):
        prov[p] = r
for p, r in sorted(prov.items()):
    cur.execute('INSERT OR REPLACE INTO provinces(province,region) VALUES(?,?)', (p, r))

# national_lines：score_lines.raw_value 实测 + 06 库国家线备注（A/B 区）
nl = {}
for (rv,) in cur.execute("SELECT DISTINCT raw_value FROM score_lines WHERE raw_value LIKE '%国家线%'"):
    n = first_num(rv)
    if n:
        nl[(2026, '工学', 'B区' if 'B区' in rv else 'A区')] = (n, None, '06-院校数据库/data/schools/*.json(score_lines.raw_value)')
for (y, sc, z, t, s4, src) in [
    (2026, '工学', 'A区', 264, 53, '02-院校数据/全国408_085410双非热度版_20260820.html'),
    (2026, '工学', 'B区', 254, 48, '02-院校数据/全国408_085410双非热度版_20260820.html'),
    (2025, '工学', 'A区', 260, None, 'T1 多校官方 2026 复试线表交叉确证（2026-09-23 取证，5 校一致）'),
    (2025, '工学', 'B区', 250, None, '06-院校数据库/data/schools/001-宁夏大学.json'),
    (2024, '工学', 'A区', 273, None, '06-院校数据库/data/schools/001-华北电力大学.json'),
    (2024, '工学', 'B区', 263, None, '06-院校数据库/data/schools/001-宁夏大学.json'),
    (2023, '工学', 'A区', 273, None, '06-院校数据库/data/schools/001-浙江海洋大学.json'),
    (2023, '工学', 'B区', 263, None, '06-院校数据库/data/schools/001-宁夏大学.json'),
]:
    nl[(y, sc, z)] = (t, s4, src)
for (y, sc, z), (t, s4, src) in sorted(nl.items()):
    cur.execute('INSERT OR REPLACE INTO national_lines(year,subject_category,zone,total_line,subject_408_line,src) '
                'VALUES(?,?,?,?,?,?)', (y, sc, z, t, s4, src))

# exam_subjects
for (oid, sk, lab, src) in sorted(exam_rows, key=lambda x: (x[0], str(x[1]))):
    if oid and sk:
        cur.execute('INSERT OR REPLACE INTO exam_subjects(offering_id,subject_key,subject_label,src) VALUES(?,?,?,?)',
                    (oid, str(sk), sv(lab), src))

# catalog（研招目录逐年快照）
n_cat = 0
for y, d in cat10:
    for s in d.get('schools') or []:
        nm = s.get('schoolName') or ''
        key = resolve(nm)[0] or 'X-' + nm
        if key not in seen:
            upsert_school(nm, 'lib10')
        for p in s.get('programs') or []:
            mcs = p.get('majorCodes')
            scope = sv(p.get('scope'))
            # scope 形如「人工智能学院 · 085410 人工智能」，取「·」前段作 college
            college = scope.split('·')[0].strip() if scope and '·' in scope else None
            cur.execute('INSERT INTO catalog(school_key,year,major_code,college,scope,exam_408_type,degree_type,'
                        'note,changed_from,source_level,source_url) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (key, y, sv(mcs), college, scope, sv(p.get('exam408Type')), sv(p.get('degreeType')),
                         sv(p.get('note')), sv(p.get('changedFrom')), sv(p.get('sourceLevel')), sv(p.get('sourceUrl'))))
            n_cat += 1

# dai408_records
n_dai = 0
for it in dai408.get('items') or []:
    nm = it.get('s') or ''
    key = resolve(nm)[0] or 'X-' + nm
    if key not in seen:
        upsert_school(nm, 'dai408')
    cur.execute('''INSERT INTO dai408_records(school_key,s,p,lv,c,d,dc,dt,y,sid,ex,fee,rt,plan,act,retest,adm,
                   smin,smax,savg,smed,m408,mmath,line) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (key, sv(it.get('s')), sv(it.get('p')), sv(it.get('lv')), sv(it.get('c')), sv(it.get('d')),
                 sv(it.get('dc')), sv(it.get('dt')), it.get('y'), it.get('sid'), sv(it.get('ex')), sv(it.get('fee')),
                 sv(it.get('rt')), it.get('plan'), it.get('act'), it.get('retest'), it.get('adm'),
                 it.get('smin'), it.get('smax'), it.get('savg'), it.get('smed'), it.get('m408'), it.get('mmath'),
                 sv(it.get('line'))))
    n_dai += 1

# todo_patch
n_todo = 0
for it in todo_patch_list:
    nm = it.get('name') or ''
    key = resolve(nm)[0] or 'X-' + nm
    if key not in seen:
        upsert_school(nm, 'lib06')
    for fld in it.get('missing') or []:
        cur.execute('INSERT OR REPLACE INTO todo_patch(school_key,field_name,n_missing) VALUES(?,?,?)',
                    (key, str(fld), it.get('n_missing')))
        n_todo += 1

# wangdao_links_all.json（byProvince 嵌套 → 补 wangdao_links）
n_wd2 = 0
for province, schools in (wangdao_all.get('byProvince') or {}).items():
    if province == '省份':
        continue
    for sname, rec in (schools or {}).items():
        key = resolve(sname)[0] or 'X-' + sname
        if key not in seen:
            upsert_school(sname, 'lib07')
        for ylab, url in (rec.get('links') or {}).items():
            if url:
                cur.execute('INSERT INTO wangdao_links(school_key,year_label,url) VALUES(?,?,?)', (key, ylab, url))
                n_wd2 += 1

# ── 5.7 脏值清洗（P2）：admissions 7 字段数值化 + 定性枚举 + score_lines 国家线 ──
CLEAN_FIELDS = ['plan', 'fill', 'retest_cnt', 'admit_cnt', 'admit_max', 'admit_min', 'admit_avg']
quali = set()
for f in CLEAN_FIELDS:
    for (v,) in cur.execute('SELECT DISTINCT %s FROM admissions WHERE %s IS NOT NULL' % (f, f)):
        s = str(v).strip()
        if s and not NUM_RE.match(s) and first_num(s) is None:
            quali.add(s)
fill_code = {}
for i, lab in enumerate(sorted(quali), 1):
    code = 'F%02d' % i
    fill_code[lab] = code
    cur.execute('INSERT OR REPLACE INTO fill_types(code,label) VALUES(?,?)', (code, lab))

n_clean = 0
for f in CLEAN_FIELDS:
    for rid, v in cur.execute('SELECT id, %s FROM admissions WHERE %s IS NOT NULL' % (f, f)).fetchall():
        val, note = num_cols(v)
        cur.execute('UPDATE admissions SET %s_value=?, %s_note=? WHERE id=?' % (f, f), (val, note, rid))
        if note is not None:
            n_clean += 1
for row in cur.execute('SELECT id, fill, plan, retest_cnt, admit_cnt, admit_max, admit_min, admit_avg FROM admissions').fetchall():
    rid, vals = row[0], row[1:]
    for v in vals:
        if v is None:
            continue
        c = fill_code.get(str(v).strip())
        if c:
            cur.execute('UPDATE admissions SET fill_type_code=? WHERE id=?', (c, rid))
            break

# score_lines：9 行「国家线/国家线(NC)」无数字 → value_kind='national_line'，值从 national_lines 取
nl_map = {(y, z): t for (y, sc, z), (t, s4, src) in nl.items()}
n_natline = 0
for rid, y, rv in cur.execute('SELECT id, year, raw_value FROM score_lines').fetchall():
    if rv is None:
        continue
    if first_num(rv) is None:
        zone = 'B区' if 'B区' in str(rv) else 'A区'
        cur.execute("UPDATE score_lines SET value_kind='national_line' WHERE id=?", (rid,))
        t = nl_map.get((y, zone))
        if t is not None:
            cur.execute('UPDATE score_lines SET value=? WHERE id=?', (float(t), rid))
        n_natline += 1

# score_quantiles.offering_id 回连：① 按 (school_key, major_code) 精确；② 按 college 与 program_name 的包含关系兜底
_offs = cur.execute('SELECT id, school_key, major_code, college FROM offerings').fetchall()
for (oid, sk, mc, col) in _offs:
    cur.execute("UPDATE score_quantiles SET offering_id=? WHERE school_key=? AND IFNULL(major_code,'')=IFNULL(?,'')",
                (oid, sk, mc))
for (oid, sk, mc, col) in _offs:
    if col:
        cur.execute("""UPDATE score_quantiles SET offering_id=?
                       WHERE offering_id IS NULL AND school_key=? AND program_name LIKE ?""",
                    (oid, sk, '%' + str(col) + '%'))
n_q_link = cur.execute('SELECT COUNT(*) FROM score_quantiles WHERE offering_id IS NOT NULL').fetchone()[0]

# ── 5.8 field_provenance（_approx 精度 / sourceLevel / 页面 verified）──
approx_map = {}
for s in score_matrix.get('schools') or []:
    key = resolve(s.get('name') or '')[0] or 'X-' + (s.get('name') or '')
    for u in s.get('units') or []:
        if u.get('_approx'):
            approx_map[(key, sv(u.get('college')), sv(u.get('direction')))] = u['_approx']
n_prov_fp = 0
for oid, sk, col, dirn in cur.execute('SELECT id, school_key, college, direction FROM offerings').fetchall():
    ap = approx_map.get((sk, col, dirn))
    if ap:
        for fld in ap:
            cur.execute('INSERT OR REPLACE INTO field_provenance(table_name,row_id,field_name,source_tier,confidence,approx_flag) '
                        'VALUES(?,?,?,?,?,?)', ('offerings', oid, fld, 'lib06', None, 1))
            n_prov_fp += 1
for rid, lvl in cur.execute('SELECT id, source_level FROM score_quantiles').fetchall():
    if lvl:
        cur.execute('INSERT OR REPLACE INTO field_provenance(table_name,row_id,field_name,source_tier,confidence,approx_flag) '
                    'VALUES(?,?,?,?,?,?)', ('score_quantiles', rid, 'source_level', lvl, None, 0))
        n_prov_fp += 1
for rid, vf in cur.execute('SELECT id, verify FROM kaoqing').fetchall():
    if vf:
        cur.execute('INSERT OR REPLACE INTO field_provenance(table_name,row_id,field_name,source_tier,confidence,approx_flag) '
                    'VALUES(?,?,?,?,?,?)', ('kaoqing', rid, 'verify', vf, None, 0))
        n_prov_fp += 1

# ── 6. 索引与约束 ─────────────────────────────────────────
cur.executescript('''
CREATE INDEX idx_q_school      ON score_quantiles(school_key);
CREATE INDEX idx_q_school_major ON score_quantiles(school_key, major_code);
CREATE INDEX idx_q_offering    ON score_quantiles(offering_id);
CREATE INDEX idx_off_school    ON offerings(school_key);
CREATE INDEX idx_off_major     ON offerings(major_code);
CREATE INDEX idx_off_school_major ON offerings(school_key, major_code);
CREATE INDEX idx_line_school   ON score_lines(school_key);
CREATE INDEX idx_line_offering ON score_lines(offering_id);
CREATE INDEX idx_adm_school    ON admissions(school_key);
CREATE INDEX idx_adm_offering  ON admissions(offering_id);
CREATE INDEX idx_kq_school     ON kaoqing(school_key);
CREATE INDEX idx_upd_school    ON updates_2027(school_key);
CREATE INDEX idx_wd_school     ON wangdao_links(school_key);
CREATE INDEX idx_src_school    ON sources(school_key);
CREATE INDEX idx_cf_school     ON conflicts(school_key);
CREATE INDEX idx_alias_school  ON school_aliases(school_key);
''')

# ── 7. 统一视图（学校×专业）────────────────────────────────
cur.executescript('''
DROP VIEW IF EXISTS v_school_major;
CREATE VIEW v_school_major AS
SELECT s.school_key, s.code, s.name AS school_name, s.province, s.region, s.tier,
       s.is985, s.is211, s.in_lib06, s.in_lib10, s.in_yz408, s.cb_id,
       o.major_code, m.major_name, m.degree_type, m.category,
       o.college, o.subject_class, o.direction,
       (SELECT COUNT(*) FROM score_lines   x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_lines,
       (SELECT COUNT(*) FROM admissions    x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_admissions,
       (SELECT COUNT(*) FROM score_quantiles x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_quantiles,
       (SELECT COUNT(*) FROM tutors        x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_tutors,
       (SELECT COUNT(*) FROM kaoqing       x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_kaoqing,
       (SELECT COUNT(*) FROM updates_2027  x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_updates2027,
       (SELECT COUNT(*) FROM conflicts     x WHERE x.school_key=s.school_key) AS n_conflicts
FROM schools s
LEFT JOIN offerings o ON o.school_key = s.school_key
LEFT JOIN majors    m ON m.major_code = o.major_code;

DROP VIEW IF EXISTS v_school_all;
CREATE VIEW v_school_all AS
SELECT s.school_key, s.code, s.code_verified, s.name, s.province, s.province_raw, s.region, s.tier,
       s.is985, s.is211, s.is_dfc, s.cs_rank, s.in_lib06, s.in_lib10, s.in_yz408, s.in_cb, s.cb_id,
       CASE WHEN s.in_lib06=1 OR s.in_lib10=1 THEN 'full'          -- 有择校或录取分数数据
            WHEN s.in_yz408=1                 THEN 'catalog_only'  -- 仅研招网 408 目录
            ELSE                                   'link_only'     -- 仅王道链接，无 408 数据
       END AS data_level,
       (SELECT COUNT(*) FROM offerings       x WHERE x.school_key=s.school_key) AS n_offerings,
       (SELECT COUNT(DISTINCT major_code) FROM offerings x WHERE x.school_key=s.school_key AND major_code IS NOT NULL) AS n_majors,
       (SELECT COUNT(*) FROM score_lines     x WHERE x.school_key=s.school_key) AS n_lines,
       (SELECT COUNT(*) FROM admissions      x WHERE x.school_key=s.school_key) AS n_admissions,
       (SELECT COUNT(*) FROM score_quantiles x WHERE x.school_key=s.school_key) AS n_quantiles,
       (SELECT COUNT(*) FROM tutors          x WHERE x.school_key=s.school_key) AS n_tutors,
       (SELECT COUNT(*) FROM kaoqing         x WHERE x.school_key=s.school_key) AS n_kaoqing,
       (SELECT COUNT(*) FROM updates_2027    x WHERE x.school_key=s.school_key) AS n_updates2027,
       (SELECT COUNT(*) FROM conflicts       x WHERE x.school_key=s.school_key) AS n_conflicts
FROM schools s;
''')
con.commit()

# ── 8. 导出 ───────────────────────────────────────────────
cur.execute('SELECT school_key,code,code_verified,name,in_lib06,in_lib10,in_yz408,cb_id FROM schools ORDER BY school_key')
cw = {}
for r in cur.fetchall():
    cur.execute('SELECT alias,src FROM school_aliases WHERE school_key=?', (r[0],))
    cw[r[0]] = {'code': r[1], 'code_verified': r[2], 'name': r[3],
                'aliases': [{'alias': a, 'src': s} for a, s in cur.fetchall()],
                'in_lib06': r[4], 'in_lib10': r[5], 'in_yz408': r[6], 'cb_id': r[7]}
with io.open(CROSSWALK, 'w', encoding='utf-8', newline='\n') as f:
    json.dump({'schema': 'crosswalk/v1', 'built': BUILT,
               'key': '教育部招生单位代码（5 位）；未匹配者 school_key=X-<标准名> 且 code_verified=0',
               'n': len(cw), 'schools': cw}, f, ensure_ascii=False, indent=1)

cur.execute('SELECT * FROM v_school_major')
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
with io.open(UNIFIED, 'w', encoding='utf-8', newline='\n') as f:
    json.dump({'schema': 'school-major/v1', 'built': BUILT,
               'note': '学校×专业 三层模型的统一视图（学校 → 专业 → 各类数据）',
               'n': len(rows), 'rows': rows}, f, ensure_ascii=False, indent=1)

# ── 9. 自检 ───────────────────────────────────────────────
def one(q, *a):
    return cur.execute(q, a).fetchone()[0]


print('=== 统一库自检（学校 → 专业 → 各类数据）===')
for t in ['schools', 'school_aliases', 'majors', 'provinces', 'offerings', 'score_lines', 'admissions',
          'fill_types', 'score_quantiles', 'score_bands', 'stats_yoy', 'tutors', 'kaoqing',
          'exam_subjects', 'updates_2027', 'wangdao_links', 'sources', 'conflicts', 'catalog',
          'dai408_records', 'todo_patch', 'field_provenance', 'national_lines', 'dataset_sources']:
    print('  %-16s %6d 行' % (t, one('SELECT COUNT(*) FROM %s' % t)))
print('  %-16s %6d 行  ← 学校×专业' % ('v_school_major', len(rows)))
print('  %-16s %6d 行  ← 全部学校' % ('v_school_all', one('SELECT COUNT(*) FROM v_school_all')))
print()
print('  专业字典 %d 个：%s' % (one('SELECT COUNT(*) FROM majors'),
      ', '.join('%s %s' % (r[0], r[1]) for r in cur.execute('SELECT major_code,major_name FROM majors ORDER BY major_code'))))
print()
print('  索引 %d 个；国家线 %d 行；分数带 %d 行；同环比 %d 行' % (
    one("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"),
    one('SELECT COUNT(*) FROM national_lines'), one('SELECT COUNT(*) FROM score_bands'), one('SELECT COUNT(*) FROM stats_yoy')))
print('  导师 %d 行（name 非空 %d / title 非空 %d / url 非空 %d）' % (
    one('SELECT COUNT(*) FROM tutors'), one('SELECT COUNT(*) FROM tutors WHERE name IS NOT NULL'),
    one('SELECT COUNT(*) FROM tutors WHERE title IS NOT NULL'), one('SELECT COUNT(*) FROM tutors WHERE url IS NOT NULL')))
print('  脏值清洗：数值化 note 条 %d；定性枚举 %d 类；score_lines 国家线标记 %d 行' % (
    n_clean, one('SELECT COUNT(*) FROM fill_types'), n_natline))
for f in ('plan', 'retest_cnt', 'admit_cnt'):
    tot = one('SELECT COUNT(*) FROM admissions WHERE %s IS NOT NULL' % f)
    ok = one('SELECT COUNT(*) FROM admissions WHERE %s IS NOT NULL AND %s_value IS NOT NULL' % (f, f))
    print('     %-11s 数值化率 %6.1f%%（%d/%d）' % (f, 100.0 * ok / max(tot, 1), ok, tot))
print()
n_off_all = one('SELECT COUNT(*) FROM offerings')
n_off_mc = one('SELECT COUNT(*) FROM offerings WHERE major_code IS NOT NULL')
print('  offerings %d 行，其中 major_code 已识别 %d（%.1f%%）；v_school_major %d 行（含仅研招网目录、无 offering 的学校）' % (
    n_off_all, n_off_mc, 100.0 * n_off_mc / max(n_off_all, 1), len(rows)))
print('  major_code 仍为 NULL 的 offering：')
for r in cur.execute('''SELECT s.name, o.college, o.direction FROM offerings o JOIN schools s ON s.school_key=o.school_key
                        WHERE o.major_code IS NULL ORDER BY s.name'''):
    print('     %-14s %-24s %s' % (r[0], str(r[1])[:24], str(r[2])[:40]))
for src, n in cur.execute("SELECT major_source, COUNT(*) FROM offerings GROUP BY major_source"):
    print('    offerings.major_source=%-9s %d' % (src, n))
print()
print('  06∩10（两侧都有）: %d 校' % one('SELECT COUNT(*) FROM schools WHERE in_lib06=1 AND in_lib10=1'))
print('  仅06 / 仅10 / 仅研招网: %d / %d / %d' % (
    one('SELECT COUNT(*) FROM schools WHERE in_lib06=1 AND in_lib10=0'),
    one('SELECT COUNT(*) FROM schools WHERE in_lib10=1 AND in_lib06=0'),
    one('SELECT COUNT(*) FROM schools WHERE in_yz408=1 AND in_lib06=0 AND in_lib10=0')))
print('  code 已验证: %d / %d' % (one('SELECT COUNT(*) FROM schools WHERE code_verified=1'),
                                  one('SELECT COUNT(*) FROM schools')))
print()
print('=== 样例：某校某专业 的全部数据（三层贯通）===')
q = '''SELECT s.name, o.major_code, m.major_name, o.college, o.subject_class,
              (SELECT COUNT(*) FROM score_lines     x WHERE x.offering_id=o.id) AS 线,
              (SELECT COUNT(*) FROM admissions      x WHERE x.offering_id=o.id) AS 招录,
              (SELECT COUNT(*) FROM score_quantiles x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS 分位,
              (SELECT COUNT(*) FROM kaoqing         x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS 考情
       FROM schools s JOIN offerings o ON o.school_key=s.school_key
       LEFT JOIN majors m ON m.major_code=o.major_code
       WHERE s.school_key='10459' ORDER BY o.id'''
for r in cur.execute(q):
    print('  %s | %s %s | %s | %s | 线%s 招录%s 分位%s 考情%s' % tuple(str(x) for x in r))
print()
print('=== 样例：按专业聚合（哪些专业数据最全）===')
q = '''SELECT o.major_code, m.major_name, COUNT(DISTINCT o.school_key) AS 校数,
              SUM(CASE WHEN o.major_source='extracted' THEN 1 ELSE 0 END) AS 显式,
              SUM(CASE WHEN o.major_source='inferred'  THEN 1 ELSE 0 END) AS 推断
       FROM offerings o LEFT JOIN majors m ON m.major_code=o.major_code
       GROUP BY o.major_code ORDER BY 校数 DESC LIMIT 10'''
for r in cur.execute(q):
    print('  %-8s %-14s %3d 校（显式 %d / 推断 %d）' % (r[0] or 'NULL', r[1] or '-', r[2], r[3], r[4]))
con.close()
print('\n输出：')
for p in [DB, CROSSWALK, UNIFIED]:
    print('  %s  (%.1f KB)' % (os.path.relpath(p, ROOT), os.path.getsize(p) / 1024.0))
