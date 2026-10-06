<!-- 投稿前请读根 README「🤝 数据征集（面向 AI agent 与考生）」节；一校一文件、一 PR 一校 -->

## 投稿内容

- 学校（与 `06-院校数据库/contributions/<学校名>.json` 文件名一致）：
- 学院 / 专业组合数（entries 数量）：
- 数据内容：<!-- 如 2026 复试线 / 录取统计 / 2027 改考 / 导师方向 … -->

## 来源自查（全部勾选才能合并）

- [ ] 每个 field 都带 `source.url`（http(s) 直链）+ `source.tier`（T1~T4）+ `source.date`（YYYY-MM-DD）
- [ ] 官方来源优先；王道 / N诺等机构口径只作交叉参考并已标注 tier
- [ ] 无需登录 / 付费即可查看；不含任何个人隐私（考生姓名 / 编号 / 联系方式）；录取名单类数据已脱敏

## 格式自查

- [ ] 文件位于 `06-院校数据库/contributions/<学校名>.json`，`schema` 为 `contribution-v1`
- [ ] 本地跑过 `python 09-生成脚本/validate_contributions.py` 且全部合法
- [ ] 未改动 `data/schools/*.json` 正本、派生文件（`school_browser.json` / `搜索索引.json` / `kaoyan408.db` / 页面 HTML）及其他学校数据
- [ ] 未运行 `integrate_three_sources.py` / `etl_build_db.py` / `update_verify_0903.py`

## 备注

<!-- 多来源冲突说明、口径注、原始页面存档链接等 -->
