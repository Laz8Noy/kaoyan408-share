"""补录本轮已人工复核的来源事实。只允许应用到备份哈希一致的八校正本。

下载缓存留在 .dsh/work；公开名单仅在本地聚合，不在交付物中复制个人信息。
sourceRecords 是正本的一部分；本目录的导出、变更记录均为本轮审计快照。
"""
from pathlib import Path
import copy
import datetime as dt
import hashlib
import json
import re
import statistics

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
CACHE = ROOT / '.dsh/work/source-extraction-20261015/sources'
SCHOOLS = ROOT / '06-院校数据库/data/schools'
NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
CHANGES = []
DOCS = {}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=indent) + '\n', encoding='utf-8')


def source(url, title, published=None, cache=None, tier='T1', method='downloaded_html'):
    path = CACHE / cache if cache else None
    return {'url': url, 'title': title, 'publishedDate': published, 'collectedAt': NOW,
            'tier': tier, 'retrievalMethod': method,
            'downloadSha256': hashlib.sha256(path.read_bytes()).hexdigest() if path and path.exists() else None}


def fact(school, rid, college, code, program, topic, metrics, src, *, direction=None,
         study=None, batch=None, scope='', unit=None, location=None):
    row = {'id': rid, 'year': 2026, 'college': college, 'programCode': code,
           'programName': program, 'direction': direction, 'studyMode': study,
           'topic': topic, 'batch': batch, 'metrics': metrics, 'scope': scope,
           'unitIndex': unit, 'source': copy.deepcopy(src), 'evidenceLocation': location,
           'verificationStatus': 'checked_against_reprint' if src['tier'] == 'T2' else 'checked_against_primary'}
    DOCS[school].setdefault('sourceRecords', []).append(row)
    return rid


def patch(school, pointer, value, reason, refs):
    tokens = pointer.strip('/').split('/')
    parent = DOCS[school]
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent.setdefault(token, {})
    key = int(tokens[-1]) if isinstance(parent, list) else tokens[-1]
    existed = key in parent if isinstance(parent, dict) else key < len(parent)
    before = copy.deepcopy(parent[key]) if existed else None
    if existed and before == value:
        return
    CHANGES.append({'school': school, 'pointer': pointer, 'existedBefore': existed,
                    'before': before, 'after': value, 'reason': reason, 'sourceRecordIds': refs})
    parent[key] = copy.deepcopy(value)


def unit_patch(school, index, field, value, reason, refs):
    patch(school, f'/units/{index}/{field}', value, reason, refs)
    DOCS[school]['units'][index].setdefault('fieldSources', {})[field] = refs


def summarize(rows, score_key):
    values = [r[score_key] for r in rows]
    return {'count': len(values), 'min': min(values), 'max': max(values),
            'mean': round(statistics.mean(values), 6)}


def main():
    backup = load(BASE / 'backup.json')
    originals = {x['path']: x['sha256'] for x in backup['files']}
    names = ['深圳大学', '湖北大学', '成都信息工程大学', '广东工业大学',
             '桂林电子科技大学', '青海大学', '中北大学', '重庆邮电大学']
    for name in names:
        p = SCHOOLS / ('001-' + name + '.json')
        relative = p.relative_to(ROOT).as_posix()
        if hashlib.sha256(p.read_bytes()).hexdigest() != originals[relative]:
            raise ValueError('正本已变化，停止重复应用：' + relative)
        DOCS[name] = load(p)
        if DOCS[name].get('sourceRecords'):
            raise ValueError('本脚本只应用一次，已有来源事实：' + name)

    # 1. 深大：目录总计划与推免后的统考计划分开，名额不充当录取数。
    catalog = source('https://yz.szu.edu.cn/info/1006/13396.htm', '深圳大学2026年硕士研究生招生专业目录', cache='sz-catalog.html')
    post = source('https://yz.szu.edu.cn/info/1008/13796.htm', '2026年接收推免生后硕士招生可用于统考计划情况', cache='sz-plan.html')
    lines = source('https://yz.szu.edu.cn/info/1041/14396.htm', '深圳大学2026年硕士研究生招生复试分数线', cache='sz-line.html')
    gml = source('https://www.gml.ac.cn/zsgg/939.html', '深圳大学-光明实验室2026年硕士研究生复试录取实施细则', '2026-03-24', method='web_page_text')
    qoder = load(ROOT / '.dsh/work/source-extraction-20261015/qoder/result.json')
    external = json.loads(re.sub(r'^```json\s*|\s*```$', '', qoder['text'].strip()))
    expected = [('081200', 318, 7, 11), ('085404', 317, 19, 29), ('085410', 312, 20, 31)]
    if qoder['exit_code'] or [(r['program_code'], r['retest_line'], r['remaining_exam_slots'], r['shortlisted_count']) for r in external] != expected:
        raise ValueError('Qoder结果与已核对官网表格不一致')
    sz = [('人工智能学院', 72, 27, 335, '人工智能'), ('光明实验室', 20, 20, 312, '人工智能'),
          ('大湾区国际创新学院', 30, 8, 286, '人工智能（管理）')]
    for i, (college, total, remaining, line, program) in enumerate(sz):
        rid = f'szu-2026-{i}-catalog'
        fact('深圳大学', rid, college, '085410', program, 'enrollment_plans',
             {'directory_plan_count': total}, catalog, study='全日制', batch='招生目录拟招', unit=i, location='全日制专业学位目录：68/70/72行')
        post_id = f'szu-2026-{i}-post-recommendation'
        fact('深圳大学', post_id, college, '085410', program, 'enrollment_plans',
             {'post_recommendation_exam_plan_count': remaining}, post, study='全日制', batch='接收推免后统考计划', unit=i,
             scope='这一阶段的可用于统考计划；不代表最终实际录取人数。')
        line_id = f'szu-2026-{i}-line'
        fact('深圳大学', line_id, college, '085410', program, 'retest_results', {'retest_line': line}, lines,
             study='全日制', batch='复试基本线', unit=i)
        for field, value in [('programCode', '085410'), ('nnProg', '085410' + program), ('studyMode', '全日制')]:
            unit_patch('深圳大学', i, field, value, '官网目录明确的专业身份', [rid])
        if i != 1:
            unit_patch('深圳大学', i, 'plan2026', str(remaining), '补推免后的统考计划；目录总计划另存', [post_id])
        unit_patch('深圳大学', i, 'scope', f'2026全日制085410；目录拟招{total}，接收推免后统考计划{remaining}；阶段不同，实际录取人数待补。', '明确计划口径', [rid, post_id])
    for row in external:
        code = row['program_code']
        identity = dict(study='全日制', unit=1 if code == '085410' else None, location='复试细则表：专业所在行')
        fact('深圳大学', f'szu-gml-2026-{code}-quota', '光明实验室', code, row['program_name'], 'enrollment_plans',
             {'remaining_exam_slots': row['remaining_exam_slots']}, gml, batch='复试前剩余统考指标', **identity)
        fact('深圳大学', f'szu-gml-2026-{code}-shortlist', '光明实验室', code, row['program_name'], 'retest_results',
             {'retest_line': row['retest_line'], 'shortlisted_count': row['shortlisted_count'],
              'includes_tied_scores': code == '085410'}, gml, batch='拟复试上线考生',
             scope='上线名单人数，不等于实际到场或录取人数；人工智能31人含同分。', **identity)
    unit_patch('深圳大学', 1, 'retestCnt', '31（拟复试上线，含同分）', '从备注中的漏项提取，保留名单口径', ['szu-gml-2026-085410-shortlist'])

    # 2. 湖北大学：相同方向名不等于相同专业码；全日制/非全日制各自保存。
    hubu = source('https://yz.hubu.edu.cn/info/1011/3299.htm', '湖北大学2026年硕士研究生招生专业目录', '2025-09-29', cache='hubei-catalog.html')
    rows = [('ai', '人工智能学院', '085400', '电子信息', '10人工智能', '全日制', 50,
             ['101', '204', '302', '871'], '数据结构与算法', '面向对象程序设计和数据库系统原理，程序设计（上机考试）', 0),
            ('cs-full', '计算机学院', '085400', '电子信息', '04计算机技术', '全日制', 171,
             ['101', '204', '302', '408'], '计算机学科专业基础', '面向对象程序设计和数据库系统原理', None),
            ('cs-part', '计算机学院', '085404', '计算机技术', '00不区分研究方向', '非全日制', 20,
             ['101', '204', '302', '408'], '计算机学科专业基础', '面向对象程序设计和数据库系统原理', None)]
    for tag, college, code, program, direction, study, plan, subjects, subject_name, retest, oi in rows:
        kw = dict(direction=direction, study=study, unit=oi, location='208计算机学院/213人工智能学院；跨行专业单元格按rowspan归属')
        fact('湖北大学', f'hubu-2026-{tag}-catalog-plan', college, code, program, 'enrollment_plans', {'directory_plan_count': plan}, hubu, batch='招生目录拟招', **kw)
        fact('湖北大学', f'hubu-2026-{tag}-exams', college, code, program, 'examinations',
             {'initial_subject_codes': subjects, 'business_subject_name': subject_name}, hubu, batch='2026招生目录', **kw)
        fact('湖北大学', f'hubu-2026-{tag}-retest', college, code, program, 'retest_requirements', {'retest_subjects': retest}, hubu, batch='2026招生目录', **kw)
    old_ai = copy.deepcopy(DOCS['湖北大学']['units'][0])
    unit_patch('湖北大学', 0, 'dataQuality', {'legacySummary': {'scope': old_ai['scope'], 'note': old_ai['note']},
               'legacyProgramLabel': old_ai['nnProg'], 'legacySubjects': old_ai['nnSubjects'],
               'admissionsStatus': '旧第三方统计尚未按官方目录专业码复核；不因本次目录核实而升级其可信度'},
               '保留原811/085410主张，明确与官方目录差异', ['hubu-2026-ai-exams'])
    for field, value in [('programCode', '085400'), ('nnProg', '电子信息(085400)-10人工智能'), ('direction', '10人工智能'),
                         ('studyMode', '全日制'), ('nnSubjects', '英二数二+871数据结构与算法'),
                         ('retestSubjects', rows[0][9]),
                         ('note', '2026官方目录：085400电子信息·10人工智能，全日制，英二数二871（非408），目录拟招50；旧第三方招录统计保留，尚未确认与官方专业码的对应。'),
                         ('scope', '初试科目与身份以官方目录为准；线275、复试60、拟录50+1等仍是原第三方统计，未因本次补录得到官方确认。')]:
        unit_patch('湖北大学', 0, field, value, '按官方目录纠正考试与身份；不改275/264既有分数线裁定', ['hubu-2026-ai-exams', 'hubu-2026-ai-catalog-plan'])
    unit_patch('湖北大学', 1, 'dataQuality', {'identityStatus': '学习方式待核，不自动套用目录计划',
               'catalogAlternatives': [{'programCode': '085400', 'studyMode': '全日制', 'directoryPlan': 171},
                                       {'programCode': '085404', 'studyMode': '非全日制', 'directoryPlan': 20}],
               'warning': '旧nnProg=085404与招录181等统计的学习方式未核清；保留旧值，官方两条记录均不自动挂接该unit。'},
               '隔离全日制/非全日制身份歧义', ['hubu-2026-cs-full-catalog-plan', 'hubu-2026-cs-part-catalog-plan'])

    # 3. 青大：PDF为成绩公示；只能确认复试人数和成绩，不能由排名推断拟录取。
    for tag, code, program, oi in [('ai', '085410', '人工智能', 0), ('cs', '085404', '计算机技术', 1)]:
        file = f'qh-{tag}.pdf'
        rows_qh = load(CACHE / (file + '.anonymous.json'))
        if len(rows_qh) != (44 if tag == 'ai' else 59) or {r['code'] for r in rows_qh} != {code}:
            raise ValueError('青大匿名提取结果不符')
        values = [r['scores'][4] for r in rows_qh]
        metrics = {'observed_retest_count': len(rows_qh), 'initial_total_min': min(values), 'initial_total_max': max(values),
                   'initial_total_mean': round(statistics.mean(values), 6),
                   'retest_score_mean': round(statistics.mean(r['retest_score'] for r in rows_qh), 6)}
        filename = '5044754f48e142f1a58bae040c554215.pdf' if tag == 'ai' else '205230eacead43868656a06910153139.pdf'
        src = source('https://cs.qhu.edu.cn/docs//2026-03/' + filename, '青海大学2026年硕士研究生一志愿成绩公示-' + program,
                     '2026-03-31', cache=file, method='downloaded_pdf_local_anonymous_aggregation')
        rid = fact('青海大学', f'qhu-2026-{tag}-first-choice-results', '计算机技术与应用学院', code, program, 'retest_results', metrics, src,
                   batch='一志愿成绩公示', unit=oi, scope='PDF全量考生行匿名汇总；最低初试分不是单独公布的复试线，不含拟录取结论。', location='人工智能2页/计算机技术3页，按序号去重，全列加总核对')
        for field, value in [('programCode', code), ('nnProg', code + program)]:
            unit_patch('青海大学', oi, field, value, '以官网PDF报考专业代码列纠正旧085400标签', [rid])
        patch('青海大学', f'/kaoqingDetail2026/{oi}/program', code + program, '专业码由官方同学院同方向PDF确认；录取统计仍属旧第三方来源', [rid])

    # 4. 桂电：名单不等同到场成绩或录取名单；只提取匿名统计。
    guet_rows = [r for r in load(CACHE / 'guet-anonymous.json') if r['code'] == '085410']
    if len(guet_rows) != 33 or any(sum(r['scores'][:4]) != r['scores'][4] for r in guet_rows):
        raise ValueError('桂电名单行数/分数列不符')
    totals = [r['scores'][4] for r in guet_rows]
    guet_src = source('https://www.guet.edu.cn/_upload/article/files/6c/db/4a69c1914a8bb70f310ad514a4bc/e85f8f91-510f-4ec7-99fc-9f0c12bbd191.pdf',
                      '桂林电子科技大学计算机与信息安全学院2026年硕士研究生招生复试名单（第一批）', '2026-03-22', cache='guet-first.pdf', method='downloaded_pdf_local_anonymous_aggregation')
    gid = fact('桂林电子科技大学', 'guet-2026-cs-ai-first-shortlist', '计算机与信息安全学院', '085410', '人工智能', 'retest_results',
               {'shortlisted_count': 33, 'initial_total_min': min(totals), 'initial_total_max': max(totals),
                'initial_total_mean': round(statistics.mean(totals), 6)}, guet_src, study='全日制', batch='第一批复试名单', unit=0,
               scope='只统计003计算机与信息安全学院085410；不含另一个学院或调剂批次；名单不证明实际到场或拟录取。', location='5页PDF中专业码085410的33行')
    unit_patch('桂林电子科技大学', 0, 'programCode', '085410', '官网名单明确专业码', [gid])
    unit_patch('桂林电子科技大学', 0, 'studyMode', '全日制', '官网名单明确学习方式', [gid])

    # 5. 中北：初试调整与复试要求按主题保存，教材版本不跨专业替换。
    nuc = source('https://cst.nuc.edu.cn/info/1039/8937.htm', '2026年硕士研究生招生考试科目调整通知', '2025-03-11', cache='nuc-notice.html')
    nid = fact('中北大学', 'nuc-2026-ai-exam-change', '计算机科学与技术学院（大数据学院）', '085410', '人工智能', 'examinations',
               {'previous_business_subject': '811数据结构', 'business_subject_code': '408',
                'business_subject_name': '计算机学科专业基础', 'reference_scope': '参照教育部考试大纲'}, nuc,
               batch='2026初试业务课调整', unit=0, scope='公告只证明第四单元改408，不用它确认英语和数学。')
    books = ['Java 2实用教程（第5版）', 'C++面向对象程序设计（第2版）', '数据库系统概论（第7版）', '算法分析与设计及案例教程']
    retest = '编程能力测试（上机）；计算机综合知识（含数据库和算法分析）'
    nrid = fact('中北大学', 'nuc-2026-ai-retest-requirements', '计算机科学与技术学院（大数据学院）', '085410', '人工智能', 'retest_requirements',
                {'retest_subjects': retest, 'retest_references': books}, nuc, batch='2026复试科目与教材', unit=0,
                scope='仅085410行；085404行的数据库第6版和081200行的第5版不替换本行第7版。')
    for field, value, ref in [('programCode', '085410', nid), ('retestSubjects', retest, nrid), ('retestReferences', books, nrid)]:
        unit_patch('中北大学', 0, field, value, '提取旧链接中未结构化的复试科目和参考书', [ref])

    # 6. 广工：301是非全日制调剂报名门槛，从历年复试线中移出。
    gdut = source('https://automation.gdut.edu.cn/info/1081/10526.htm', '广东工业大学自动化学院硕士研究生招生调剂通知（一）', '2026-04-01', method='web_indexed_official_page')
    gdid = fact('广东工业大学', 'gdut-2026-auto-ai-part-time-transfer', '自动化学院', '085410', '人工智能', 'transfer_policy',
                {'minimum_initial_total': 301, 'eligible_categories': ['理学（07）', '工学（08）'],
                 'eligible_subjects': ['思想政治理论', '英语一或英语二', '数学一或数学二', '科目四相同相近'],
                 'application_start': '2026-04-08T00:00:00+08:00', 'application_end': '2026-04-08T12:00:00+08:00'}, gdut,
                study='非全日制', batch='调剂报名', scope='301不是普通一志愿复试线；旧自动化unit学习方式未明确，故不自动挂接。')
    patch('广东工业大学', '/units/1/linesByYear/2026', None, '把误放在复试线中的非全调剂门槛301归还调剂政策', [gdid])
    unit_patch('广东工业大学', 1, 'dataQuality', {'removedHistoricalLine': '301', 'reason': '非全日制调剂报名门槛，已迁入sourceRecords',
                'legacyLine264Status': '本轮未用调剂通知重新证明普通复试线264'}, '保留迁移理由和旧值', [gdid])

    # 7. 成信：成绩公示没有拟录取结论，不把两名复试者分数冒充录取分数。
    cuit_change = source('https://jsjxy.cuit.edu.cn/info/1062/3098.htm', '计算机学院关于调整2026年硕士研究生招生专业课考试初试科目的公告', cache='cuit-change.html')
    cid = fact('成都信息工程大学', 'cuit-2026-cs-ai-exam-change', '计算机学院', '085410', '人工智能', 'examinations',
               {'previous_business_subject': '820计算机专业基础', 'business_subject_code': '408', 'business_subject_name': '计算机学科专业基础'},
               cuit_change, batch='2026初试第四单元调整', unit=1, scope='本公告不证明英语/数学，也不用于人工智能学院。')
    cr = load(CACHE / 'cuit-anonymous.json')
    if len(cr) != 2 or sorted(r['initialTotal'] for r in cr) != [274, 276]:
        raise ValueError('成信匿名成绩不符')
    cuit_first = source('https://jsjxy.cuit.edu.cn/info/1062/3251.htm', '2026年计算机学院复试（第一批）成绩公布', cache='cuit-first.html')
    cfid = fact('成都信息工程大学', 'cuit-2026-cs-ai-first-results', '计算机学院', '085410', '人工智能', 'retest_results',
                {'observed_retest_count': 2, 'initial_total_min': 274, 'initial_total_max': 276, 'initial_total_mean': 275,
                 'zero_interview_score_count': 1}, cuit_first, study='全日制', batch='一志愿第一批成绩', unit=1,
                scope='只有成绩表；不由面试0分或排名推断拟录取人数。274/276/275是复试考生初试统计。')
    cuit_transfer = source('https://jsjxy.cuit.edu.cn/info/1062/3252.htm', '2026年计算机学院调剂公告（4月1日）', '2026-04-01', cache='cuit-transfer.html')
    fact('成都信息工程大学', 'cuit-2026-cs-ai-transfer-policy', '计算机学院', '085410', '人工智能', 'transfer_policy',
         {'accepted_english_codes': ['201', '204'], 'required_math_code': '301', 'required_business_code': '408'}, cuit_transfer,
         study='全日制', batch='调剂报名', unit=1, scope='调剂资格条件，不能当作本校一志愿完整考试科目组合。')
    unit_patch('成都信息工程大学', 1, 'programCode', '085410', '官网改考公告明确专业码', [cid])
    unit_patch('成都信息工程大学', 1, 'studyMode', '全日制', '成绩公示明确学习方式', [cfid])
    old_scores = {k: DOCS['成都信息工程大学']['units'][1].get(k) for k in ['admitMax', 'admitMin', 'admitAvg']}
    unit_patch('成都信息工程大学', 1, 'dataQuality', {'reclassifiedLegacyFields': old_scores,
               'reason': '原274/276/275为复试者初试成绩统计；已转sourceRecords.retest_results，不作为录取统计'}, '保留错放原值', [cfid])
    for field in ['admitMax', 'admitMin', 'admitAvg']:
        unit_patch('成都信息工程大学', 1, field, None, '复试统计从录取字段移出', [cfid])
        patch('成都信息工程大学', '/kaoqingDetail2026/0/' + field, None, '同步移出同一来源的重复错放统计', [cfid])
    for field in ['admitMax', 'admitMin']:
        patch('成都信息工程大学', '/kaoqingDetail2026/2/' + field, None, '官方成绩公示不能证明录取者分数', [cfid])
    patch('成都信息工程大学', '/kaoqingDetail2026/2/scope', '旧汇总声称录1人；本次官网只核得2名复试者初试274/276、其中一名面试0分。未用该表确认拟录取结论；admitCnt=1待拟录取公示复核。', '标明旧录取结论未获本次公示支持', [cfid])

    # 8. 重邮：官方页面本次412；转载证据保留T2，不冒充直接访问成功。
    cq = source('https://m.chinakaoyan.com/info/article/id/668021.shtml', '重庆邮电大学2026年硕士研究生招生复试基本分数线', '2026-03-24',
                cache='cq-lines-reprint.html', tier='T2', method='downloaded_official_notice_reprint')
    cqid = fact('重庆邮电大学', 'cqupt-2026-ai-line-reprint', '人工智能学院', '085410', '人工智能', 'retest_results',
                {'retest_line': 336, 'single_subject_100_line': 35, 'single_subject_over_100_line': 53}, cq,
                batch='普通复试基本线', unit=0, scope='中国考研网转载；官网本次返回412，维持T2证据等级。')
    unit_patch('重庆邮电大学', 0, 'programCode', '085410', '转载表明确学院与专业码，标记T2', [cqid])
    patch('重庆邮电大学', '/units/0/linesByYear/2026', '336', '旧330属于计算机技术，人工智能学院085410表列336', [cqid])
    unit = DOCS['重庆邮电大学']['units'][0]
    mixed = {k: unit.get(k) for k in ['retestCnt', 'admitCnt', 'admitAvg', 'scope']}
    unit_patch('重庆邮电大学', 0, 'dataQuality', {'quarantinedCrossProgramFields': mixed,
               'reason': '原文明确这些是计算机/软件统计，不能继续作为人工智能学院085410的招录指标。原值隔离保留，待各专业分别核实。'},
               '隔离跨学院跨专业统计，避免人工智能单位误读', [cqid])
    for field in ['retestCnt', 'admitCnt', 'admitAvg']:
        unit_patch('重庆邮电大学', 0, field, None, '原字段标明计算机/软工，移出人工智能统计', [cqid])
    unit_patch('重庆邮电大学', 0, 'scope', '人工智能学院085410；2026复试基本线336、单科35/53，来源T2转载。计划132及复录比仍待核；原计算机/软件招录统计已隔离于dataQuality。', '清理跨项目混用摘要', [cqid])

    all_records = []
    ids = set()
    for name, doc in DOCS.items():
        for rec in doc['sourceRecords']:
            if rec['id'] in ids:
                raise ValueError('来源记录ID重复')
            ids.add(rec['id'])
            ui = rec.get('unitIndex')
            if ui is not None and doc['units'][ui].get('programCode') != rec['programCode']:
                raise ValueError('专业码与挂接unit不符：' + rec['id'])
            if not any(x.get('url') == rec['source']['url'] for x in doc.get('sources', [])):
                doc.setdefault('sources', []).append({'label': rec['source']['title'], 'url': rec['source']['url']})
            all_records.append({'school': name, **rec})
    # 所有内存数据通过上述断言后再写正本；原值与补录结果一并交付，便于追溯。
    save(BASE / 'source_records.json', {'collectedAt': NOW, 'records': all_records})
    save(BASE / 'changes.json', CHANGES)
    for name, doc in DOCS.items():
        save(SCHOOLS / ('001-' + name + '.json'), doc, indent=1)
        save(BASE / 'after' / ('001-' + name + '.json'), doc)
    print(json.dumps({'schools': len(DOCS), 'source_records': len(all_records), 'field_changes': len(CHANGES)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
