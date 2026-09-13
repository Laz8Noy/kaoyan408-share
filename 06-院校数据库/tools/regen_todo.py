# -*- coding: utf-8 -*-
import json, os, glob
from collections import Counter

DB = r'C:\Users\华硕\Desktop\考研085410_22408_资料汇总_20260818\deliverables\20260903-考研院校数据库AI版'
SCH = os.path.join(DB, 'data', 'schools')
files = sorted(glob.glob(os.path.join(SCH, '*.json')))

with open(os.path.join(DB, 'data', 'meta.json'), 'r', encoding='utf-8') as f:
    meta = json.load(f)
cat_map = {s['name']: s['inCategory'] for s in meta['schools']}
file_map = {s['name']: s['file'] for s in meta['schools']}

patch_list = []
for fp in files:
    with open(fp, 'r', encoding='utf-8') as f:
        o = json.load(f)
    name = o.get('name', '')
    units = o.get('units', [])
    missing = []
    if not units:
        missing.append('招生单位行')
    if not any(u.get('line2026') for u in units):
        missing.append('2026复试线')
    if not any(u.get('linesByYear') and any(v for v in u['linesByYear'].values()) for u in units):
        missing.append('历年线')
    if not any(u.get('plan2026') for u in units):
        missing.append('计划人数')
    if not any(u.get('fill') for u in units):
        missing.append('一志愿/调剂')
    if not any(u.get('admitCnt') for u in units):
        missing.append('录取人数')
    if not any(u.get('admitAvg') for u in units):
        missing.append('均分')
    if not any(u.get('nn408avg') for u in units):
        missing.append('N诺408均分')
    if not any(u.get('wdCount') for u in units):
        missing.append('王道条数')
    if not any(u.get('wdYears') for u in units):
        missing.append('王道链接年份')
    if not o.get('updates2027'):
        missing.append('2027改考')
    if not o.get('kaoqingDetail2026'):
        missing.append('考情明细')

    wd_count = len(o.get('wangdaoLinks', {}))
    patch_list.append({
        'name': name,
        'file': file_map.get(name, os.path.basename(fp)),
        'category': cat_map.get(name, '未知'),
        'n_missing': len(missing),
        'missing': missing,
        'wangdaoLinks': wd_count
    })

patch_list.sort(key=lambda x: (-x['n_missing'], x['name']))

with open(os.path.join(DB, 'data', 'todo_patch_list.json'), 'w', encoding='utf-8') as f:
    json.dump(patch_list, f, ensure_ascii=False, indent=1)

total_missing = sum(p['n_missing'] for p in patch_list)
zero_missing = [p['name'] for p in patch_list if p['n_missing'] == 0]
print('补后总缺失字段数:', total_missing, '(补前1486)')
print('全绿学校数:', len(zero_missing))
print('全绿学校:', zero_missing)
print()
dist = Counter(p['n_missing'] for p in patch_list)
for k in sorted(dist.keys()):
    print('  缺%d项: %d所' % (k, dist[k]))
print()
print('仍缺最多的15所:')
for p in patch_list[:15]:
    print('  %s(%s): 缺%d项 %s' % (p['name'], p['category'], p['n_missing'], p['missing']))
