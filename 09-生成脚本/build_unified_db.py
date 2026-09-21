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
    score_lines      分数线（含历年、口径）
    admissions       招生录取（拟招/复试/录取/最高/最低/均分）
    score_quantiles  分数分位（408/数学/英语/政治/总分 的 min·p25·中位·p75·max·均值）
    tutors           导师
    kaoqing          考情明细
    updates_2027     2027 改考
    wangdao_links / sources / conflicts

统一视图 v_school_major：一行 = 学校×专业，各类数据条数齐全 → "全部收拢"

用法（仓库根目录）：python 09-生成脚本/build_unified_db.py
输出：06-院校数据库/data/kaoyan408.db、crosswalk.json、schools_unified.json
"""
import os
import io
import re
import json
import glob
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D06 = os.path.join(ROOT, '06-院校数据库', 'data')
D10 = os.path.join(ROOT, '10-录取分数统计', 'data')
DB = os.path.join(D06, 'kaoyan408.db')
CROSSWALK = os.path.join(D06, 'crosswalk.json')
UNIFIED = os.path.join(D06, 'schools_unified.json')
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
    """SQLite 只接受标量：list/dict 转 JSON 字符串"""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


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


# ── 2. 建库 ───────────────────────────────────────────────
if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
con.execute('PRAGMA foreign_keys=ON')
cur = con.cursor()

cur.executescript('''
CREATE TABLE schools (
  school_key TEXT PRIMARY KEY,
  code TEXT UNIQUE, code_verified INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL, province TEXT, region TEXT, tier TEXT,
  is985 INTEGER, is211 INTEGER, is_dfc INTEGER, cs_rank INTEGER,
  in_lib06 INTEGER DEFAULT 0, in_lib10 INTEGER DEFAULT 0,
  in_yz408 INTEGER DEFAULT 0, in_cb INTEGER DEFAULT 0,
  cb_id INTEGER, lib06_file TEXT, note TEXT
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

CREATE TABLE offerings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT REFERENCES majors(major_code),
  major_source TEXT,
  college TEXT, category TEXT, tier TEXT, province TEXT, region TEXT,
  subject_class TEXT, direction TEXT, ai_tag TEXT, src TEXT, src_label TEXT,
  kaoqing_url TEXT, remark TEXT, note TEXT,
  raw TEXT
);

CREATE TABLE score_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, offering_id INTEGER REFERENCES offerings(id),
  year INTEGER, line_type TEXT, value REAL, basis TEXT, raw_value TEXT
);

CREATE TABLE admissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, offering_id INTEGER REFERENCES offerings(id),
  year INTEGER,
  plan TEXT, fill TEXT, retest_cnt TEXT, admit_cnt TEXT,
  admit_max TEXT, admit_min TEXT, admit_avg TEXT,
  ratio_retest TEXT, ratio_apply TEXT,
  nn_408avg TEXT, nn_rate TEXT, heat_net TEXT, heat_comp TEXT
);

CREATE TABLE score_quantiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_key TEXT NOT NULL REFERENCES schools(school_key),
  major_code TEXT, year INTEGER, program_name TEXT,
  exam_408_type TEXT, source_level TEXT, source_url TEXT,
  subject TEXT, label TEXT, count INTEGER,
  min REAL, p25 REAL, median REAL, p75 REAL, max REAL, mean REAL,
  ci_low REAL, ci_high REAL
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
    cur.execute('''INSERT INTO schools(school_key,code,code_verified,name,province,region,tier,
                   is985,is211,is_dfc,cs_rank,in_lib06,in_lib10,in_yz408,in_cb,cb_id,lib06_file,note)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (key, cd, ver, name, prov, region, tier,
                 m10.get('is985'), m10.get('is211'), m10.get('isDoubleFirstClass'), m10.get('csRank'),
                 1 if src == 'lib06' else 0, 1 if src == 'lib10' else 0, 1 if src == 'yz408' else 0, 0,
                 m10.get('id'), (d06 or {}).get('_file'), (d06 or {}).get('note')))
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
n_off = n_line = n_adm = n_q = 0
for name, d in s06.items():
    key = key06[name]
    for u in d.get('units') or []:
        text = ' '.join(str(u.get(k) or '') for k in ('direction', 'note', 'college', 'nnProg', 'nnCollege'))
        mc, msrc = infer_major(text)
        mc = ensure_major(mc)
        cur.execute('''INSERT INTO offerings(school_key,major_code,major_source,college,category,tier,province,region,
                       subject_class,direction,ai_tag,src,src_label,kaoqing_url,remark,note,raw)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, msrc, sv(u.get('college')), sv(u.get('category')), sv(u.get('tier')), sv(u.get('province')), sv(u.get('region')),
                     sv(u.get('subjectClass')), sv(u.get('direction')), sv(u.get('aiTag')), sv(u.get('src')), sv(u.get('srcLabel')),
                     sv(u.get('kaoqingUrl')), sv(u.get('remark')), sv(u.get('note')), json.dumps(u, ensure_ascii=False)))
        oid = cur.lastrowid
        n_off += 1
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
        cur.execute('''INSERT INTO admissions(school_key,major_code,offering_id,year,plan,fill,retest_cnt,admit_cnt,
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
    for u in d.get('updates2027') or []:
        mc = ensure_major(infer_major(str(u.get('专业/范围') or ''))[0])
        cur.execute('''INSERT INTO updates_2027(school_key,major_code,school_name,tier,scope,subject_old,
                       subject_new,effective_year,source,note) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (key, mc, u.get('院校') or name, u.get('层次'), u.get('专业/范围'),
                     u.get('原科目'), u.get('新科目'), u.get('生效年份'), u.get('来源'), u.get('备注')))
    for t in d.get('tutors') or []:
        s = t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)
        cur.execute('INSERT INTO tutors(school_key,major_code,school_name,direction,note,src) VALUES(?,?,?,?,?,?)',
                    (key, None, name, s, '来自 06 tutors 摘要字段', 'lib06'))
    for y, url in (d.get('wangdaoLinks') or {}).items():
        if url:
            cur.execute('INSERT INTO wangdao_links(school_key,year_label,url) VALUES(?,?,?)', (key, y, url))
    for u in d.get('sources') or []:
        cur.execute('INSERT INTO sources(school_key,label,url) VALUES(?,?,?)', (key, u.get('label'), u.get('url')))
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

# 10 侧：分数分位（挂到 school_key + major_code）
for name, d in s10.items():
    key = key10[name]
    for p in d.get('programs') or []:
        pname = p.get('programName') or ''
        mc = ensure_major(infer_major(pname)[0])
        for y in (p.get('stats') or {}).get('years') or []:
            for s in y.get('subjects') or []:
                cur.execute('''INSERT INTO score_quantiles(school_key,major_code,year,program_name,exam_408_type,
                               source_level,source_url,subject,label,count,min,p25,median,p75,max,mean,ci_low,ci_high)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (key, mc, y.get('year'), pname, y.get('exam408Type'), y.get('sourceLevel'),
                             y.get('sourceUrl'), s.get('key'), s.get('label'), s.get('count'),
                             s.get('min'), s.get('p25'), s.get('median'), s.get('p75'), s.get('max'),
                             s.get('mean'), s.get('ciLow'), s.get('ciHigh')))
                n_q += 1

# 数据源登记
for r in [
    ('lib06', '本仓库择校库（177 校）', '', '', 'CC BY 4.0', 0, '可编辑正本'),
    ('lib10', 'CodeBrick 录取分数统计（96 校）', 'https://www.codebrick.tech/practice/school-admit', '2026-09-06', '版权归原站', 1, '无抓取脚本，一次性快照'),
    ('yz408', '研招网 2026 硕士专业目录（第四科=408）', 'https://yz.chsi.com.cn/zsml/', '2026-09-20', '官方公开', 1, '招生单位代码来源'),
    ('dai408', 'Dai408 录取数据库（公益参考版）', 'https://awarer.top/', '2026-09-21', '公益参考', 1, '生成脚本已断（ext/ 缺失）'),
]:
    cur.execute('INSERT OR REPLACE INTO dataset_sources(id,label,url,fetched_at,license,immutable,note) VALUES(?,?,?,?,?,?,?)', r)

# ── 6. 统一视图（学校×专业）────────────────────────────────
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
       (SELECT COUNT(*) FROM tutors        x WHERE x.school_key=s.school_key) AS n_tutors,
       (SELECT COUNT(*) FROM kaoqing       x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_kaoqing,
       (SELECT COUNT(*) FROM updates_2027  x WHERE x.school_key=s.school_key AND IFNULL(x.major_code,'')=IFNULL(o.major_code,'')) AS n_updates2027,
       (SELECT COUNT(*) FROM conflicts     x WHERE x.school_key=s.school_key) AS n_conflicts
FROM schools s
LEFT JOIN offerings o ON o.school_key = s.school_key
LEFT JOIN majors    m ON m.major_code = o.major_code;

DROP VIEW IF EXISTS v_school_all;
CREATE VIEW v_school_all AS
SELECT s.school_key, s.code, s.code_verified, s.name, s.province, s.region, s.tier,
       s.is985, s.is211, s.is_dfc, s.cs_rank, s.in_lib06, s.in_lib10, s.in_yz408, s.in_cb, s.cb_id,
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

# ── 7. 导出 ───────────────────────────────────────────────
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

# ── 8. 自检 ───────────────────────────────────────────────
def one(q, *a):
    return cur.execute(q, a).fetchone()[0]


print('=== 统一库自检（学校 → 专业 → 各类数据）===')
for t in ['schools', 'school_aliases', 'majors', 'offerings', 'score_lines', 'admissions',
          'score_quantiles', 'tutors', 'kaoqing', 'updates_2027', 'wangdao_links',
          'sources', 'conflicts', 'dataset_sources']:
    print('  %-16s %6d 行' % (t, one('SELECT COUNT(*) FROM %s' % t)))
print('  %-16s %6d 行  ← 学校×专业' % ('v_school_major', len(rows)))
print('  %-16s %6d 行  ← 全部学校' % ('v_school_all', one('SELECT COUNT(*) FROM v_school_all')))
print()
print('  专业字典 %d 个：%s' % (one('SELECT COUNT(*) FROM majors'),
      ', '.join('%s %s' % (r[0], r[1]) for r in cur.execute('SELECT major_code,major_name FROM majors ORDER BY major_code'))))
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
