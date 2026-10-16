"""Import checked official facts for QLU, WTU and NUIST into school JSONs.

Usage: python apply_batch.py. One shot: it backs up every existing target first,
checks source bytes and both external agent results, then updates three schools.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import shutil

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
WORK = ROOT / '.dsh/work/expanded-20261016'
SOURCES = WORK / 'sources'
DATA = ROOT / '06-院校数据库/data'
FIRST = ROOT / 'deliverables/20261015-院校来源数据补录'
SCHOOL_PATHS = {name: DATA / 'schools' / f'001-{name}.json' for name in
                ['齐鲁工业大学', '武汉纺织大学', '南京信息工程大学']}
CATALOG_URL = 'https://yjszs.qlu.edu.cn/_upload/article/files/ed/0d/975cefca49fdbc73f9b536c34080/6a0d584d-69eb-402e-a7e0-4fe1d605c679.pdf'
NUIST_URL = 'https://xxgk.nuist.edu.cn/_upload/article/files/95/46/c377f100465d94b8ccc174089ee6/9ba56202-7b1e-4361-83e7-ce4b107404a8.pdf'


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def need(test: bool, description: str) -> None:
    if not test:
        raise ValueError(description)


def parse_agent_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    return json.loads(match.group(1) if match else text)


def source(filename: str, url: str, title: str, published: str | None,
           location: str) -> tuple[dict, str]:
    raw = (SOURCES / filename).read_bytes()
    return ({'url': url, 'title': title, 'publishedDate': published,
             'collectedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'tier': 'T1', 'retrievalMethod': 'downloaded_pdf' if filename.endswith('.pdf') else 'downloaded_html',
             'downloadSha256': sha256(raw).hexdigest()}, location)


def rec(id_: str, college: str, program: str, name: str, topic: str, batch: str,
        metrics: dict, scope: str, file: str, url: str, title: str,
        published: str | None, location: str, unit_index: int | None = None,
        study_mode: str | None = None, direction: str | None = None) -> dict:
    src, place = source(file, url, title, published, location)
    return {'id': id_, 'year': 2026, 'college': college, 'programCode': program,
            'programName': name, 'direction': direction, 'studyMode': study_mode,
            'topic': topic, 'batch': batch, 'metrics': metrics, 'scope': scope,
            'unitIndex': unit_index, 'source': src, 'evidenceLocation': place,
            'verificationStatus': 'checked_against_primary'}


def backup_files() -> dict:
    target = ROOT / '.dsh/backups/20261016-expanded-official'
    need(not target.exists(), 'Backup already exists; batch is one shot')
    paths = list(SCHOOL_PATHS.values())
    paths += [DATA / x for x in ['score_matrix.json', 'kaoyan408.db', 'meta.json',
               'todo_patch_list.json', 'crosswalk.json', 'schools_unified.json',
               'school_browser.json']]
    paths += [FIRST / x for x in ['tools/export_review.py', 'verification.json',
               'pending_items.json', '分类对照.md', 'external_agents.json']]
    paths += list((FIRST / 'schools').glob('*.json'))
    manifest = []
    for path in paths:
        if not path.exists():
            continue
        dest = target / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        manifest.append({'path': path.relative_to(ROOT).as_posix(),
                         'sha256': sha256(path.read_bytes()).hexdigest()})
    relative_backup = target.relative_to(ROOT).as_posix()
    save_json(OUT / 'backup.json', {'directory': relative_backup, 'files': manifest})
    return {'directory': relative_backup, 'files': manifest}


def main() -> None:
    need(not (OUT / 'backup.json').exists(), 'This batch was already applied')
    qoder = load_json(WORK / 'qoder-result.json')
    buddy = load_json(WORK / 'workbuddy-result.json')
    need(qoder['model_requested'] == 'Qwen3.8-Flash' and qoder['exit_code'] == 0,
         'Qoder result is not usable')
    need(buddy['success'] and buddy['model_reported'] == 'deepseek-v4.1-flash'
         and buddy['stop_reason'] == 'end_turn', 'WorkBuddy result is not usable')
    qlu_agent = parse_agent_json(qoder['text'])
    wtu_agent = parse_agent_json(buddy['text'])
    need(any(x['program_code'] == '085410' and x['new_fourth_subject'].startswith('876')
             for x in qlu_agent['claims']), 'Qoder omitted 085410/876')
    need({p['code'] for p in wtu_agent['programs']} == {'081200', '085405', '085410'}
         and wtu_agent['adjustment_quota_known'] is None, 'WorkBuddy overclaimed quota')

    with pdfplumber.open(SOURCES / 'qlu-catalog-2026.pdf') as pdf:
        ai_rows = [r for table in pdf.pages[13].extract_tables() for r in table
                   if any(c and '085410' in c for c in r)]
        cs_rows = [r for table in pdf.pages[0].extract_tables() for r in table
                   if any(c and '085404' in c for c in r)]
    need(len(ai_rows) == 1 and len(cs_rows) == 1, 'QLU catalog rows changed')
    ai, cs = ai_rows[0], cs_rows[0]
    need('29' in ai[2] and all(code in ai[3] for code in ('101', '204', '302', '876')),
         'QLU 085410 catalog row changed')
    need(all(code in cs[3] for code in ('101', '204', '302', '408')),
         'QLU 085404 catalog row changed')
    with pdfplumber.open(SOURCES / 'nuist-2026-list.pdf') as pdf:
        rows = pdf.pages[1].extract_tables()[0]
    ai022, ai036 = rows[19], rows[45]
    need(rows[18][0] == '022' and rows[42][0] == '036'
         and ai022[2] == ai036[2] == '085410'
         and ai022[8:10] == ['5', '4'] and ai036[8:10] == ['140', '138'],
         'NUIST rows or column mapping changed')
    wtu_rules = ''.join((p.extract_text() or '') for p in PdfReader(str(SOURCES / 'wtu-retest-rules.pdf')).pages)
    need('不再进行二次划线' in wtu_rules and '120%' in wtu_rules and '085410' in wtu_rules,
         'WTU retest rules changed')
    wtu_transfer = (SOURCES / 'wtu-transfer.html').read_text(encoding='utf-8', errors='replace')
    wtu_exam = (SOURCES / 'wtu-exam-draft.html').read_text(encoding='utf-8', errors='replace')
    qlu_notice = (SOURCES / 'qlu-notice.html').read_text(encoding='utf-8', errors='replace')
    need(all(code in wtu_transfer for code in ('081200', '085405', '085410')),
         'WTU transfer table changed')
    need(all(code in wtu_exam for code in ('085410', '848', '408')),
         'WTU draft exam notice changed')
    need(all(code in qlu_notice for code in ('085404', '085410', '408', '876')),
         'QLU exam notice changed')

    documents = {name: load_json(path) for name, path in SCHOOL_PATHS.items()}
    need(all(not d.get('sourceRecords') for d in documents.values()),
         'One of the three schools already has source records')
    backup = backup_files()

    qlu = documents['齐鲁工业大学']
    old_qlu = qlu['units'][0]
    qlu['dataQuality'] = {'quarantinedLegacyUnits': [old_qlu],
                          'reason': '旧unit将计算机学部2025第三方招录与数学与人工智能学部2026招生混合，并误写085410为22408；完整旧值保留待逐项核实。'}
    qlu['units'] = [{
        'category': old_qlu['category'], 'province': old_qlu['province'],
        'region': old_qlu['region'], 'tier': old_qlu['tier'],
        'college': '数学与人工智能学部', 'programCode': '085410',
        'subjectClass': '非408', 'direction': '计算机视觉等四方向',
        'plan2026': '29', 'line2026': None,
        'linesByYear': {'2023': None, '2024': None, '2025': None, '2026': None},
        'aiTag': '✅真AI专业', 'srcLabel': '官方2026招生目录',
        'scope': '2026最终招生目录第14页：085410人工智能拟招29人，初试101/204/302/876。目录未在该行明示学习方式；旧22408、线264、计划28、历史分数另存待核。',
        'note': '该085410为英二数二876，非22408；同校计算机技术085404为英二数二408。',
        'fieldSources': {'programCode': ['qlu-2026-ai-catalog-exams'],
                         'plan2026': ['qlu-2026-ai-catalog-plan'],
                         'subjectClass': ['qlu-2026-ai-catalog-exams']},
    }]
    qlu['sourceRecords'] = [
        rec('qlu-2026-ai-catalog-exams', '数学与人工智能学部', '085410', '人工智能',
            'examinations', '2026最终招生目录',
            {'initial_subject_codes': ['101', '204', '302', '876'],
             'business_subject_name': '人工智能基础综合',
             'directions': ['计算机视觉', '医学人工智能', '大数据与可信计算', '智能机器人']},
            'PDF行未明示学习方式；该专业与计算机学部085404的408不得混同。',
            'qlu-catalog-2026.pdf', CATALOG_URL, '齐鲁工业大学2026年硕士研究生招生专业目录',
            '2025-09-30', 'PDF第14页，010数学与人工智能学部085410行', 0),
        rec('qlu-2026-ai-catalog-plan', '数学与人工智能学部', '085410', '人工智能',
            'enrollment_plans', '2026最终招生目录拟招', {'planned_total': 29},
            '目录拟招数，不是实际录取人数。', 'qlu-catalog-2026.pdf', CATALOG_URL,
            '齐鲁工业大学2026年硕士研究生招生专业目录', '2025-09-30',
            'PDF第14页，010数学与人工智能学部085410行', 0),
        rec('qlu-2026-cs-085404-catalog-exams', '计算机科学与技术学部', '085404', '计算机技术',
            'examinations', '2026最终招生目录',
            {'initial_subject_codes': ['101', '204', '302', '408']},
            '同校另一个专业；不得把408当成085410人工智能的科目。',
            'qlu-catalog-2026.pdf', CATALOG_URL, '齐鲁工业大学2026年硕士研究生招生专业目录',
            '2025-09-30', 'PDF第1页，001计算机科学与技术学部085404行'),
        rec('qlu-2026-ai-adjustment-notice', '数学与人工智能学部', '085410', '人工智能',
            'examinations', '2026初试科目拟调整公告',
            {'new_business_subject_code': '876', 'new_business_subject_name': '人工智能基础综合',
             'former_subjects_mentioned_together': ['874', '873']},
            '拟调整公告未逐一指明874/873与两个专业的对应关系；已由最终目录确认085410为876。',
            'qlu-notice.html', 'https://yjszs.qlu.edu.cn/2025/0709/c6602a259344/page.htm',
            '关于调整2026年硕士研究生招生考试初试科目的公告', '2025-07-09',
            '正文第3项及末尾最终目录提示', 0),
    ]

    wtu = documents['武汉纺织大学']
    unit = wtu['units'][0]
    old_plan = unit.get('plan2026')
    unit['programCode'] = '085410'
    unit['studyMode'] = '全日制'
    unit['plan2026'] = None
    unit['scope'] = ('官网确认2026计算机与人工智能学院085410全日制接受调剂，具体名额以研招网系统为准；'
                     '复试执行国家基本线且不二次划线。原N诺招录数字未由本批公告核对：' + unit['scope'])
    unit.setdefault('fieldSources', {}).update({
        'programCode': ['wtu-2026-ai-transfer-policy'],
        'studyMode': ['wtu-2026-ai-transfer-policy'],
        'linePolicy': ['wtu-2026-ai-retest-rules']})
    unit['dataQuality'] = {'reclassifiedLegacyFields': {'plan2026': old_plan},
                           'reason': '20一志愿+28调剂是旧第三方招录人数说法，不是官方招生计划；调剂公告未给具体名额。'}
    if wtu.get('kaoqingDetail2026'):
        wtu['kaoqingDetail2026'][0]['plan'] = None
        wtu['kaoqingDetail2026'][0]['scope'] = ('旧plan字段20一志愿+28调剂已移入dataQuality；官网调剂名额以研招网为准。'
                                                   + wtu['kaoqingDetail2026'][0]['scope'])
    wtu['sourceRecords'] = [
        rec('wtu-2026-ai-transfer-policy', '计算机与人工智能学院', '085410', '人工智能',
            'transfer_policy', '2026调剂申请',
            {'accepts_transfer': True, 'transfer_quota_published_here': False,
             'required_line_policy': 'national_A_for_origin_and_destination',
             'initial_subject_similarity_required': True},
            '公告表列全日制085410，具体调剂名额以研招网系统为准；不能据此确定录取或一志愿计划。',
            'wtu-transfer.html', 'https://csai.wtu.edu.cn/info/1063/17087.htm',
            '武汉纺织大学计算机与人工智能学院2026年硕士研究生调剂公告',
            '2026-04-03', '正文招生专业表085410行与调剂条件第1至3项', 0, '全日制'),
        rec('wtu-2026-ai-retest-rules', '计算机与人工智能学院', '085410', '人工智能',
            'retest_requirements', '2026复试工作细则',
            {'line_policy': 'national_basic_by_discipline', 'college_second_line': False,
             'minimum_retest_ratio': 1.2},
            '学院通用复试细则，未给085410独立数字线；特殊士兵计划另按学校方案。',
            'wtu-retest-rules.pdf',
            'https://csai.wtu.edu.cn/__local/D/18/9E/B68186EA15F097553E57E82058A_38E63D0A_39DF1.pdf',
            '计算机与人工智能学院2026年硕士研究生复试录取工作实施细则', None,
            'PDF第1页第三节，第2页列085410为复试专业', 0),
        rec('wtu-2026-ai-exam-draft', '计算机学院（公告用名）', '085410', '人工智能',
            'examinations', '2026目录及大纲初稿公告',
            {'previous_business_subject_code': '848', 'new_business_subject_code': '408'},
            '学校公告称科目4由848调整为408，但声明目录及大纲为初稿，最终以正式发布为准；不证明英语和数学科目。',
            'wtu-exam-draft.html', 'https://gs.wtu.edu.cn/info/1038/9392.htm',
            '关于发布武汉纺织大学2026年硕士研究生招生专业目录和大纲的公告',
            '2025-09-22', '正文考试科目调整提示', None),
    ]

    nuist = documents['南京信息工程大学']
    old_nuist_plan = nuist['units'][0]['plan2026']
    nuist['units'][0]['plan2026'] = None
    nuist['units'][0]['dataQuality'] = {
        'reclassifiedLegacyFields': {'plan2026': old_nuist_plan},
        'reason': '167+3补录为旧第三方拟录取人数，不能充当官网招生计划；旧招录口径仍保留在admitCnt。'}
    nuist.setdefault('dataQuality', {})['unitMapping'] = (
        '旧unit为第三方人工智能学院085410招录统计；官网2026招生列表列022学院与036创新港基地两条085410，'
        '本批未取得证据把旧167+3拟录取映射到任一条目录计划，故两条新记录不挂旧unit，也不合计。')
    nuist['sourceRecords'] = [
        rec('nuist-2026-022-ai-plan', '人工智能学院（未来技术学院）', '085410', '人工智能',
            'enrollment_plans', '2026招生专业列表',
            {'planned_total': 5, 'planned_exam_excluding_recommendation': 4},
            '022招生单位智慧气象与智能预报方向；目录拟招和统考计划不等于实际录取数。',
            'nuist-2026-list.pdf', NUIST_URL,
            '附件1：南京信息工程大学2026年硕士研究生拟招生专业列表', None,
            'PDF第2页022单位085410行', None, '全日制', '智慧气象与智能预报'),
        rec('nuist-2026-036-ai-plan', '南信大浦口经开区创新港研究生培养基地', '085410', '人工智能',
            'enrollment_plans', '2026招生专业列表',
            {'planned_total': 140, 'planned_exam_excluding_recommendation': 138},
            '036招生单位不区分研究方向；独立于022单位，不得与旧学院招录统计合并。',
            'nuist-2026-list.pdf', NUIST_URL,
            '附件1：南京信息工程大学2026年硕士研究生拟招生专业列表', None,
            'PDF第2页036单位085410行', None, '全日制', '不区分研究方向'),
    ]

    changes = [
        {'school': '齐鲁工业大学', 'path': 'units[0]', 'before': old_qlu,
         'after': qlu['units'][0], 'reason': '最终目录确认085410为876与拟招29；旧错配unit完整隔离保存'},
        {'school': '武汉纺织大学', 'path': 'units[0].plan2026', 'before': old_plan,
         'after': None, 'reason': '旧一志愿+调剂人数不是官方招生计划'},
        {'school': '武汉纺织大学', 'path': 'kaoqingDetail2026[0].plan',
         'before': old_plan, 'after': None, 'reason': '同一旧人数错放到计划字段'},
        {'school': '南京信息工程大学', 'path': 'dataQuality.unitMapping', 'before': None,
         'after': nuist['dataQuality']['unitMapping'], 'reason': '两招生单位同代码但不能映射旧统计'},
        {'school': '南京信息工程大学', 'path': 'units[0].plan2026', 'before': old_nuist_plan,
         'after': None, 'reason': '旧167+3补录属于拟录取数，不能放入招生计划字段'},
    ]
    for name, doc in documents.items():
        save_json(SCHOOL_PATHS[name], doc)
        save_json(OUT / 'after' / f'001-{name}.json', doc)
    records = [{'school': name, **r} for name, d in documents.items() for r in d['sourceRecords']]
    save_json(OUT / 'source_records.json', records)
    save_json(OUT / 'changes.json', changes)
    save_json(OUT / 'external_agents.json', {
        'qoder': {'model': qoder['model_requested'], 'success': True,
                  'resultFile': str((WORK / 'qoder-result.json').relative_to(ROOT)),
                  'task': '齐鲁工大公开公告科目归类'},
        'workbuddy': {'model': buddy['model_reported'], 'stopReason': buddy['stop_reason'],
                      'success': buddy['success'], 'permissionMode': buddy['permission_mode'],
                      'permissions': buddy['permissions'],
                      'resultFile': str((WORK / 'workbuddy-result.json').relative_to(ROOT)),
                      'task': '武汉纺大公开调剂公告结构化'}})
    print(json.dumps({'schools': len(documents), 'new_records': len(records),
                      'changes': len(changes), 'backup_files': len(backup['files']),
                      'qoder': 'success', 'workbuddy': 'success'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
