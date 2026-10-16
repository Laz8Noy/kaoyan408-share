"""导出本轮事实分类和数据一致性结果；不修改正本或历史分类试点。"""
from pathlib import Path
import collections
import datetime as dt
import hashlib
import json
import sqlite3

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
DATA = ROOT / '06-院校数据库/data'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    audit = load(BASE / 'source_records.json')
    changes = load(BASE / 'changes.json')
    db = sqlite3.connect(DATA / 'kaoyan408.db')
    db.row_factory = sqlite3.Row
    backup = load(BASE / 'backup.json')
    checks = {}
    checks['sqlite_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
    checks['sqlite_foreign_key_violations'] = len(db.execute('PRAGMA foreign_key_check').fetchall())
    assert checks['sqlite_integrity'] == 'ok' and not checks['sqlite_foreign_key_violations']
    saved = {r['id']: r for r in db.execute('SELECT * FROM source_records')}
    matrix = {r['name']: r for r in load(DATA / 'score_matrix.json')['schools']}
    expected = {r['id']: r for r in audit['records']}
    # This audit is a dated batch snapshot. Later batches may add records to
    # the canonical database; they must not invalidate the earlier audit.
    assert expected.keys() <= saved.keys()
    for rid, row in expected.items():
        assert json.loads(saved[rid]['raw_json']) == {k: v for k, v in row.items() if k != 'school'}
        assert json.loads(saved[rid]['metrics_json']) == row['metrics']
        assert saved[rid]['year'] == row['year'] == 2026
    checks['source_record_roundtrip_count'] = len(expected)
    checks['source_records_total'] = len(saved)
    topic_labels = {'enrollment_plans': '计划人数', 'examinations': '初试科目', 'retest_requirements': '复试科目与教材',
                    'retest_results': '复试线/名单/成绩', 'transfer_policy': '调剂政策'}
    pending = []
    review = ['# 本轮补录分类对照', '', '以下只覆盖本轮读取的来源；不代表全校全部专业。', '',
              '| 学校 | 本轮来源记录 | 分类项目 | 需保留的口径边界 |', '|---|---:|---:|---|']
    school_summaries = []
    numeric_fields = ['line2026', 'plan2026', 'retestCnt', 'admitCnt', 'admitMax', 'admitMin', 'admitAvg']
    school_names = [row[0] for row in db.execute(
        'SELECT DISTINCT s.name FROM source_records r JOIN schools s ON s.school_key=r.school_key ORDER BY s.name')]
    for name in school_names:
        src_path = DATA / 'schools' / ('001-' + name + '.json')
        doc = load(src_path)
        assert matrix[name]['sourceRecords'] == doc['sourceRecords']
        for i, unit in enumerate(doc['units']):
            for field in numeric_fields:
                assert unit.get(field) is None or isinstance(unit[field], str), (name, i, field)
            current_ids = {r['id'] for r in doc['sourceRecords']}
            for refs in unit.get('fieldSources', {}).values():
                assert all(rid in current_ids for rid in refs)
            if unit.get('programCode'):
                actual = db.execute('SELECT major_code FROM offerings o JOIN schools s ON s.school_key=o.school_key '
                                    'WHERE s.name=? ORDER BY o.id', (name,)).fetchall()[i][0]
                assert actual == unit['programCode'], (name, i, actual)
            missing = [f for f in numeric_fields if not unit.get(f)]
            if missing or unit.get('dataQuality'):
                pending.append({'school': name, 'unitIndex': i, 'college': unit.get('college'),
                                'programCode': unit.get('programCode'), 'missingLegacyFields': missing,
                                'dataQuality': unit.get('dataQuality')})
        records = doc['sourceRecords']
        projects = {}
        for r in records:
            ui = r.get('unitIndex')
            # 只在已明确挂接同一个招生单位时借用其另一条官网证据确认的学习方式。
            unit = doc['units'][ui] if ui is not None else {}
            study = r.get('studyMode') or unit.get('studyMode')
            key = (r['college'], r['programCode'], r.get('direction'), study)
            if key not in projects:
                identity = json.dumps([name, *key], ensure_ascii=False)
                projects[key] = {'id': 'project-' + hashlib.sha256(identity.encode()).hexdigest()[:14],
                                 'college': r['college'], 'programCode': r['programCode'], 'programName': r['programName'],
                                 'direction': r.get('direction'), 'studyMode': study, 'legacyUnitIndices': [], 'annualData': []}
            project = projects[key]
            if ui is not None and ui not in project['legacyUnitIndices']:
                project['legacyUnitIndices'].append(ui)
            annual = next((y for y in project['annualData'] if y['year'] == r['year']), None)
            if annual is None:
                annual = {'year': r['year'], **{t: [] for t in topic_labels}}
                project['annualData'].append(annual)
            annual[r['topic']].append(r)
        identity_row = db.execute('SELECT school_key,code FROM schools WHERE name=?', (name,)).fetchone()
        export = {'schema': 'school-source-classification/v1', 'school': dict(identity_row), 'name': name,
                  'scope': '本轮来源事实分类；旧招录统计的可信度不因补目录而升级',
                  'canonicalFile': src_path.relative_to(ROOT).as_posix(), 'projects': list(projects.values()),
                  'legacyUnits': doc['units']}
        save(BASE / 'schools' / (identity_row['school_key'] + '-' + name + '.json'), export)
        # 每条来源只在一个主题位置出现一次，数量、单位和阶段标签不因导出丢失。
        flattened = [r for p in export['projects'] for y in p['annualData'] for t in topic_labels for r in y[t]]
        assert {r['id']: r for r in flattened} == {r['id']: r for r in records}
        school_summaries.append({'name': name, 'sourceRecords': len(records), 'projects': len(projects)})
        warnings = '; '.join(sorted({r['scope'] for r in records if r['scope']}))
        review.append(f'| {name} | {len(records)} | {len(projects)} | {warnings.replace(chr(10), " ")} |')
    checks['score_matrix_matches_canonical_schools'] = len(school_summaries)
    checks['topic_export_matches_canonical_records'] = sum(x['sourceRecords'] for x in school_summaries)
    for item in backup['files']:
        backup_root = Path(backup['backup_directory'])
        if not backup_root.is_absolute():
            backup_root = ROOT / backup_root
        path = backup_root / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    checks['backup_hashes_match'] = len(backup['files'])
    historical = ROOT / 'deliverables/20261015-院校数据库分类试点'
    snapshot_manifest = load(historical / 'source_manifest.json')
    for row in snapshot_manifest['files']:
        assert hashlib.sha256((historical / row['snapshot']).read_bytes()).hexdigest() == row['sha256']
    checks['historical_pilot_snapshots_preserved'] = len(snapshot_manifest['files'])
    current_records = [json.loads(row['raw_json']) for row in saved.values()]
    checks['source_tiers'] = dict(collections.Counter(r['source']['tier'] for r in current_records))
    checks['topics'] = dict(collections.Counter(r['topic'] for r in current_records))
    checks['school_count'] = db.execute('SELECT COUNT(*) FROM schools').fetchone()[0]
    checks['offering_count'] = db.execute('SELECT COUNT(*) FROM offerings').fetchone()[0]
    checks['no_new_admission_counts_in_source_records'] = not any('admit' in key for r in current_records for key in r['metrics'])
    checks['canonical_unit_numeric_values_remain_strings_or_null'] = True
    save(BASE / 'verification.json', {'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'checks': checks,
                                    'schools': school_summaries, 'trackedFieldChanges': len(changes)})
    save(BASE / 'pending_items.json', pending)
    (BASE / '分类对照.md').write_text('\n'.join(review) + '\n', encoding='utf-8')
    # 外部代理仅复制公开文本处理结果；账号凭据、个人名单和本地全库没有发送。
    agent = []
    for file in ['result.json', 'result-2.json']:
        row = load(ROOT / '.dsh/work/source-extraction-20261015/qoder' / file)
        assert row['exit_code'] == 0 and row['text'].strip()
        agent.append(row)
    expanded = ROOT / '.dsh/work/expanded-20261016'
    qoder_new = load(expanded / 'qoder-result.json')
    assert qoder_new['model_requested'] == 'Qwen3.8-Flash' and qoder_new['exit_code'] == 0
    agent.append(qoder_new)
    buddy_new = load(expanded / 'workbuddy-result.json')
    assert buddy_new['success'] and buddy_new['model_reported'] == 'deepseek-v4.1-flash'
    assert buddy_new['stop_reason'] == 'end_turn' and buddy_new['permission_mode'] == 'allow_once'
    buddy_new['prompt_file'] = '.dsh/work/expanded-20261016/workbuddy-prompt.txt'
    workbuddy = {'requestedModel': 'deepseek-v4.1-flash', 'reportedModel': buddy_new['model_reported'],
                 'successfulCalls': 1, 'stopReason': buddy_new['stop_reason'],
                 'permissionMode': buddy_new['permission_mode'],
                 'scope': '武汉纺织大学官网公开调剂公告；主代理对照官网原文复核后采用。',
                 'billing': '使用本机已登录WorkBuddy账号；具体token和扣额未返回，无法确认数值。',
                 'result': buddy_new}
    save(BASE / 'external_agents.json', {'qoder': {'requestedModel': 'Qwen3.8-Flash', 'successfulCalls': 3,
         'scope': '前两次官网公开资料和本次齐鲁工大科目调整公告；主代理逐条复核后采用。',
         'billing': '使用本机已登录Qoder账号；具体token和扣额未返回，无法确认数值。', 'results': agent},
         'workbuddy': workbuddy})
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
