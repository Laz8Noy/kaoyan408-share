# -*- coding: utf-8 -*-
"""更新 meta.json 中的 conflicts 计数、nUnits 与 inCategory（与正本 units[0].category 同步）。
在仓库任意位置运行均可。"""
import json, os, glob, datetime

DB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 06-院校数据库/
SCH = os.path.join(DB, 'data', 'schools')

with open(os.path.join(DB, 'data', 'meta.json'), 'r', encoding='utf-8') as f:
    meta = json.load(f)

meta['date'] = datetime.date.today().isoformat()
meta['nSchools'] = len(meta['schools'])

n_cat = 0
for s in meta['schools']:
    fp = os.path.join(SCH, s['file'])
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            o = json.load(f)
        units = o.get('units', [])
        s['nUnits'] = len(units)
        s['conflicts'] = len(o.get('conflicts', []))
        # inCategory 与正本同步：units 非空以 units[0].category 为准；
        # 仅 units 为空的校才允许停留「NN候选」（09-13 全量补全后 81 校曾滞留旧档）。
        if units:
            cat = units[0].get('category')
            if cat and cat != s.get('inCategory'):
                s['inCategory'] = cat
                n_cat += 1

with open(os.path.join(DB, 'data', 'meta.json'), 'w', encoding='utf-8', newline='') as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)

print('meta.json updated: date=%s, nSchools=%d, inCategory 变更 %d 校' % (meta['date'], meta['nSchools'], n_cat))
total_conf = sum(s['conflicts'] for s in meta['schools'])
total_units = sum(s['nUnits'] for s in meta['schools'])
from collections import Counter
print('总units:', total_units, '总conflicts:', total_conf)
print('inCategory 分布:', dict(Counter(s['inCategory'] for s in meta['schools'])))
