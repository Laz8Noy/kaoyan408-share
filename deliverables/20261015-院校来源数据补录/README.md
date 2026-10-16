# 院校数据库来源补录

本批次于 2026-10-15 开始、2026-10-16 写入。仅修改院校数据库、两个数据库生成脚本和本轮交付文件。

## 本轮结果

- 8 校新增 **34 条来源事实**：33 条学校官网/官方附件，1 条官方通知转载（T2）。
- **57 项字段操作**记录于 `changes.json`；该数包含身份、口径说明和错放字段迁移，不等于填了57个数字空格。来源数组、来源链接和字段证据引用属于附加元数据。
- 正本在 `06-院校数据库/data/schools/*.json`。新增 `sourceRecords` 按学院、专业、学习方式、招生年、主题和批次保存；`programCode` 是明确身份，`fieldSources` 指向证据记录。
- SQLite 新增 `source_records` 表；总库 `score_matrix.json` 同步保留完整来源记录。SQLite、元数据、待补清单及数据库浏览索引已重建。

| 学校 | 主要补录或纠正 |
|---|---|
| 深圳大学 | 三个原有AI项目明确085410及全日制；补AI学院推免后统考计划27、湾区8。目录总计划72/30分开保存。光明实验室拟复试上线31人（含同分），并保留其081200、085404两个项目的表内数据。 |
| 湖北大学 | AI方向官方身份为085400电子信息·10人工智能，全日制，业务课871。目录拟招50另存，保留原第三方招录统计的待核状态。计院全日制085400拟招171、非全日制085404拟招20各存一条，不硬套旧unit。 |
| 青海大学 | 官网PDF明确AI085410、计技085404；匿名汇总一志愿成绩44/59人及初试范围、均分。成绩表不用于推断录取数。 |
| 桂林电子科技大学 | 003计算机与信息安全学院085410第一批名单33人，初试254–364、均296.393939，明确全日制。没有拿该表确认另一学院或调剂批次。 |
| 中北大学 | 补085410业务课811→408的直接证据、复试科目和四本教材；数据库教材为第7版，保留专业差异。 |
| 广东工业大学 | 301归类为自动化学院非全日制085410的调剂报名门槛，移出历年复试线；原普通线264未凭调剂公告重新认定。 |
| 成都信息工程大学 | 补计算机学院085410改考408及调剂条件。274/276/275属于两名复试者的初试分数统计，从录取分数字段移出；旧“录1人”仍待拟录取公示复核。 |
| 重庆邮电大学 | AI085410复试线336、单科35/53以T2转载保存；历年2026的330纠正为336。原计科/软工招录统计移入dataQuality隔离区，不继续当作AI数据。 |

## 从哪里看

- `分类对照.md`：本轮学校、记录数和口径边界。
- `schools/`：本轮事实按**招生项目 → 招生年份 → 五类主题**归位；目录、初试、复试要求、复试统计、调剂条件分开。明确区分仍待核的旧unit。
- `source_records.json`：本批次接受的来源事实快照；每条都有URL、证据等级、采集时间、文件哈希（取得原文件时）与定位说明。
- `changes.json`：逐字段修改前后及理由。`after/` 是本轮补录后八校快照，便于审阅。
- `verification.json`：正本→总库→SQLite→分类导出的逐条一致性结果、SQLite完整性及外键检查。
- `pending_items.json`：按招生单位列出剩余空字段及身份/口径问题；不把学校级“全绿”当作每个专业都完整。
- `backup.json`：修改前备份目录、原文件列表与SHA256。旧的八校分类试点保留为补录前历史快照，当前数据看本目录和正本。
- `external_agents.json`：Qoder两次公开文本外包的结果和WorkBuddy通路状态。

## 后续维护

1. 修改各校正本；同一数值必须带阶段、年份和人群口径。新增来源事实放到 `sourceRecords`，不要只丢一个链接。
2. 只有学院、专业、学习方式和方向足以对应时才填 `unitIndex`；不能唯一对应就留null。`programCode` 只填来源明示代码。
3. `units` 的传统数字字段保持字符串或null；来源事实的指标可用原生数字、数组和布尔值。不同批次或人群的数值不得直接合计。
4. 按顺序运行 `update_meta.py`、`regen_todo.py`、`build_score_matrix.py`、`build_unified_db.py`、`build_school_browser_data.py`。数据库生成脚本位于仓库 `09-生成脚本/`，前两项在 `06-院校数据库/tools/`。
5. `tools/apply_batch.py` 仅为这次有哈希保护的一次性补录，不要当成全库爬虫反复运行；`tools/export_review.py` 可重建本轮审阅导出。运行缓存位于 `.dsh/work/source-extraction-20261015/`，名单只在本地匿名聚合，交付不含考生姓名和编号。

查询示例：

```sql
SELECT s.name, r.college, r.major_code, r.study_mode, r.year,
       r.topic, r.batch, r.metrics_json, r.source_tier, r.source_url
FROM source_records r JOIN schools s ON s.school_key = r.school_key
ORDER BY s.name, r.college, r.major_code, r.year, r.topic;
```

## 仍需处理

光明实验室拟录取公示已结束、附件不可取，本轮没有填实际录取数。重邮官网本次返回412，只保留转载证据。湖北计院旧招录统计的学习方式、桂电另一学院及部分学校录取统计尚未获得本轮直接官方材料确认，详见待核清单。本轮未修改网站页面，也未进行提交或推送。

公开来源：[深大目录](https://yz.szu.edu.cn/info/1006/13396.htm)、[推免后统考计划](https://yz.szu.edu.cn/info/1008/13796.htm)、[光明复试细则](https://www.gml.ac.cn/zsgg/939.html)、[湖北目录](https://yz.hubu.edu.cn/info/1011/3299.htm)、[青大附件入口](https://cs.qhu.edu.cn/yxdt/351fef07b0dd4c4e8c9d0c9e342a9201.htm)、[桂电名单入口](https://www.guet.edu.cn/dept3/2026/0322/c2065a149917/page.htm)、[中北科目通知](https://cst.nuc.edu.cn/info/1039/8937.htm)、[广工调剂公告](https://automation.gdut.edu.cn/info/1081/10526.htm)、[成信成绩](https://jsjxy.cuit.edu.cn/info/1062/3251.htm)、[重邮复试线转载](https://m.chinakaoyan.com/info/article/id/668021.shtml)。
