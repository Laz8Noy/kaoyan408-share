"""Audit the expanded school source import and derived count semantics.

Usage: python audit_batch.py
Only writes verification.json in this delivery folder.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import sqlite3


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATA = ROOT / '06-院校数据库/data'
BASELINE = ROOT / '.dsh/backups/20261016-expanded-official/06-院校数据库/data/score_matrix.json'


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    manifest = load(OUT / 'backup.json')
    backup_dir = Path(manifest['directory'])
    if not backup_dir.is_absolute():
        backup_dir = ROOT / backup_dir
    matched = sum(sha256((backup_dir / item['path']).read_bytes()).hexdigest() == item['sha256']
                  for item in manifest['files'])
    assert matched == len(manifest['files'])

    new_records = load(OUT / 'source_records.json')
    db = sqlite3.connect(DATA / 'kaoyan408.db')
    db.row_factory = sqlite3.Row
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    fk_violations = len(db.execute('PRAGMA foreign_key_check').fetchall())
    assert integrity == 'ok' and fk_violations == 0
    saved = {row['id']: json.loads(row['raw_json'])
             for row in db.execute('SELECT id, raw_json FROM source_records')}
    roundtrips = sum(saved.get(row['id']) == {k: v for k, v in row.items() if k != 'school'}
                     for row in new_records)
    assert roundtrips == len(new_records) == 9

    names = ('齐鲁工业大学', '武汉纺织大学', '南京信息工程大学')
    school = {name: load(DATA / 'schools' / f'001-{name}.json') for name in names}
    matrix = {row['name']: row for row in load(DATA / 'score_matrix.json')['schools']}
    assert all(matrix[name]['sourceRecords'] == school[name]['sourceRecords'] for name in names)
    qlu = school['齐鲁工业大学']['units'][0]
    wtu = school['武汉纺织大学']['units'][0]
    nuist = school['南京信息工程大学']['units'][0]
    assert (qlu['programCode'], qlu['subjectClass'], qlu['plan2026'], qlu['line2026']) == \
           ('085410', '非408', '29', None)
    assert wtu['plan2026'] is None and wtu['dataQuality']['reclassifiedLegacyFields']['plan2026'] == '20一志愿+28调剂'
    assert nuist['plan2026'] is None and nuist['dataQuality']['reclassifiedLegacyFields']['plan2026'] == '167+3补录'
    assert matrix['武汉纺织大学']['units'][0]['admitCnt'] == 48
    assert matrix['武汉纺织大学']['units'][0].get('retestCnt') is None
    assert matrix['南京信息工程大学']['units'][0]['admitCnt'] == 170
    assert len({(r['college'], r['programCode']) for r in school['南京信息工程大学']['sourceRecords']}) == 2

    before = {row['name']: row for row in load(BASELINE)['schools']}
    changed = Counter()
    for name, current in matrix.items():
        if name not in before:
            continue
        for old_unit, new_unit in zip(before[name].get('units', []), current.get('units', [])):
            for field in ('plan2026', 'retestCnt', 'admitCnt'):
                if old_unit.get(field) != new_unit.get(field):
                    changed[field] += 1

    report = {
        'newSchoolsWithRecords': 3,
        'newSourceRecords': len(new_records),
        'newRecordsSqliteRoundtrip': roundtrips,
        'allSourceRecords': len(saved),
        'classifiedSchools': len(load(ROOT / 'deliverables/20261015-院校来源数据补录/verification.json')['schools']),
        'sourceRecordTierT1': sum(row['source']['tier'] == 'T1' for row in new_records),
        'sqliteIntegrity': integrity,
        'sqliteForeignKeyViolations': fk_violations,
        'backupFiles': len(manifest['files']),
        'backupHashesMatched': matched,
        'numericFieldsChangedFromPreBatch': dict(changed),
        'compositePlanRowsKeptRawOnlyInSqlite': db.execute(
            "SELECT COUNT(*) FROM admissions WHERE plan IS NOT NULL AND plan_value IS NULL "
            "AND plan_note LIKE '计划口径待核:%'").fetchone()[0],
        'qoderModel': 'Qwen3.8-Flash',
        'workbuddyModel': 'deepseek-v4.1-flash',
    }
    (OUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
