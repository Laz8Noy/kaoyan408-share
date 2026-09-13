# -*- coding: utf-8 -*-
"""更新 meta.json 中的 conflicts 计数和 nUnits。"""
import json, os, glob

DB = r'C:\Users\华硕\Desktop\考研085410_22408_资料汇总_20260818\deliverables\20260903-考研院校数据库AI版'
SCH = os.path.join(DB, 'data', 'schools')

with open(os.path.join(DB, 'data', 'meta.json'), 'r', encoding='utf-8') as f:
    meta = json.load(f)

meta['date'] = '2026-09-13'
meta['nSchools'] = 177

for s in meta['schools']:
    fp = os.path.join(SCH, s['file'])
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            o = json.load(f)
        s['nUnits'] = len(o.get('units', []))
        s['conflicts'] = len(o.get('conflicts', []))

with open(os.path.join(DB, 'data', 'meta.json'), 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)

print('meta.json updated: date=2026-09-13, nSchools=177')
total_conf = sum(s['conflicts'] for s in meta['schools'])
total_units = sum(s['nUnits'] for s in meta['schools'])
print('总units:', total_units, '总conflicts:', total_conf)
