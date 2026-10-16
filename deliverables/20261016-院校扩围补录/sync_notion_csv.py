"""Refresh the local 195-row Notion import snapshot from canonical school units.

Only the schools changed in the source-cleanup batches are refreshed in full.
For every school, ambiguous legacy plan text is kept in remarks rather than
published as a numeric enrollment plan. Run from any directory.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import csv
import json


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / '06-院校数据库/data'
CSV_PATH = ROOT / '06-院校数据库/notion导入-195招生单位矩阵.csv'
QLU_CATALOG = ('https://yjszs.qlu.edu.cn/_upload/article/files/'
               'ed/0d/975cefca49fdbc73f9b536c34080/'
               '6a0d584d-69eb-402e-a7e0-4fe1d605c679.pdf')
CHANGED_SCHOOLS = {
    '中北大学', '南京信息工程大学', '广东工业大学', '成都信息工程大学',
    '桂林电子科技大学', '武汉纺织大学', '深圳大学', '湖北大学',
    '重庆邮电大学', '青海大学', '齐鲁工业大学',
}


def value(v) -> str:
    return '' if v is None else str(v)


def ambiguous_plan(v) -> bool:
    s = value(v)
    return bool(s) and ('+' in s or any(word in s for word in ('一志愿', '调剂', '补录')))


def main() -> None:
    raw = CSV_PATH.read_bytes()
    encoding = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
    with CSV_PATH.open('r', encoding=encoding, newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    assert fields and len(rows) == 195

    meta = json.loads((DATA / 'meta.json').read_text(encoding='utf-8'))
    units_by_school = {}
    for item in meta['schools']:
        doc = json.loads((DATA / 'schools' / item['file']).read_text(encoding='utf-8'))
        units_by_school[item['name']] = doc['units']
    assert Counter(row['院校'] for row in rows) == Counter(
        {name: len(units) for name, units in units_by_school.items()})

    ordinal = defaultdict(int)
    refreshed = 0
    raw_only_plans = 0
    for row in rows:
        school = row['院校']
        index = ordinal[school]
        ordinal[school] += 1
        unit = units_by_school[school][index]
        if school != '齐鲁工业大学':
            assert row['学院'] == value(unit.get('college')), (school, index)

        if school in CHANGED_SCHOOLS:
            years = unit.get('linesByYear') or {}
            for column, source in (
                ('学院', 'college'), ('方向', 'direction'), ('省份', 'province'),
                ('地区', 'region'), ('层次', 'tier'), ('科目分类', 'subjectClass'),
                ('类别', 'category'), ('线2026', 'line2026'), ('涨跌', 'lineDelta'),
                ('生源', 'fill'), ('录取均分', 'admitAvg'), ('录取最高', 'admitMax'),
                ('录取最低', 'admitMin'),
            ):
                row[column] = value(unit.get(source))
            for year in (2025, 2024, 2023):
                row[f'线{year}'] = value(years.get(str(year)))
            row['拟招2026'] = value(unit.get('plan2026'))
            note = value(unit.get('note')) or row['备注']
            reason = (unit.get('dataQuality') or {}).get('reason')
            if reason and reason not in note:
                note += '；' + reason
            row['备注'] = note
            if school == '齐鲁工业大学':
                row['来源'] = QLU_CATALOG
            refreshed += 1

        # A stage split is not the school's total enrollment plan. Preserve
        # the exact original value in remarks so the CSV stays auditable.
        plan = value(unit.get('plan2026'))
        if ambiguous_plan(plan):
            row['拟招2026'] = ''
            marker = f'计划口径待核（原文：{plan}）'
            if marker not in row['备注']:
                row['备注'] = (row['备注'] + '；' if row['备注'] else '') + marker
            raw_only_plans += 1

    with CSV_PATH.open('w', encoding=encoding, newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'rows': len(rows), 'refreshedRows': refreshed,
                      'ambiguousPlansKeptInRemarks': raw_only_plans}, ensure_ascii=True))


if __name__ == '__main__':
    main()
