# SCHEMA 说明（kaoyan-db-ai v1）

## school JSON（data/schools/*.json）

顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| schema | str | 固定 `kaoyan-school/v1` |
| name | str | 院校全名 |
| units | [unit] | 招生单位行（校 × 学院 × 085410 相关）；`[]` 表示该档仅候补/链接 |
| crossRefs | [row] | 无法归入具体学院的跨学院参考行（含 N诺/川渝/王道汇总列） |
| kaoqingDetail2026 | [row] | 2026 考情明细（官方行/深档批次行） |
| nnCandidates | [row] | N诺新增候选明细（对未入主档的候选校是主数据） |
| wangdaoLinks | {年份:url} | 王道考情微信文章链接（2019-2026） |
| updates2027 | [row] | 2027 改考动态 |
| tutors | [str] | 导师研究方向摘要 |
| inTJList / inKeyList | obj|null | 是否在终极版"调剂院校/重点院校"清单 |
| conflicts | [conflict] | 本校冲突声明（最高优先级） |
| sources | [{label,url}] | 关联数据源链接 |
| deepRef | str|null | 深档文档相对路径（成信工等） |
| note | str|null | 学校级要点（人工总结） |
| generated | obj | 生成信息与谨慎声明 |

### unit 字段
category(S-主体/C-对照), college, province, region, tier, subjectClass(科目分类), direction,
line2026, lineDelta, linesByYear{2023..2026}, plan2026, fill(一志愿/调剂), ratioApply, ratioRetest,
retestCnt, admitCnt, admitMax/Min/Avg, scope(口径), aiTag, heatNet, heatComp, nn408avg, nnRate,
wdCount/wdYears/wdUrl26, note, srcLabel, nnProg/nnCollege/nnSubjects(若有), kaoqingUrl,
nnUrl(N诺院校页), scope2(录取明细拆解:一志愿/调剂各分段与最高最低), fill2026(2026 调剂实况),
subjectClaim2026[（成信工深档）], subjectStatus[（成信工深档）]

### kaoqingDetail2026 行字段
college, program(志愿专业), batch(批次), subjects, tier, line2026, plan, retestCnt, admitCnt,
ratioRetest, ratioApply, admitMax/Min/Avg, scope(口径), verify(核实状态), url(来源)

### todo_patch_list.json（2026-09-13 新增）
177 条：每校剩余待补字段清单（name/file/category/n_missing/missing/wangdaoLinks），由 tools/regen_todo.py 再生。

### conflict 字段
field(冲突字段), unit(相关单位), claims[{src,value}], status(已核实/待核/警告-非22408/参考/差异),
action(建议动作)。字段名 id 可选。

## 通用约定
- 空值 = null；"未公布"类占位尽量 null；原文 `—` 保留在字符串。
- 数值能转 number 则转 number，不能转保留字符串。
- 数字口径均以"2026 届复试/录取"为主；2023-2026 年线见 linesByYear。
- 任何 decision 用数之前：查该校 conflicts 与根目录 conflicts_registry.json。

## conflicts_registry.json
items[] 每项：school/field/claims/status/action。status 含"警告-非22408"，表示该校某专业为英一数一（11408）或其他口径，与 22408 目标不符，直接引此排除。
