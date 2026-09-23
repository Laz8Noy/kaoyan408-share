# 09 生成脚本

> 本目录收录数据表的生成器与主页补丁脚本（**共 15 个 .py**，2026-09-23 实测计数）。一次性调试/排查脚本早已清理（可从 git 历史找回）。
> 多数脚本内的本机路径被脱敏为 `<SOURCE_DIR>` 等占位符，运行前需按实际路径调整；不要把 API Key 写进仓库。

| 目标 | 脚本 | 状态 |
|---|---|---|
| ~~择校与规划文档（主 md/html/xlsx）~~ | `build_plan_v2.py` | **已退役**：产出的三件套对应已删除的 `01-择校与规划`（2026-09-22 改造为只含导师信息的 `01-导师与规划`），保留仅供追溯历史数据；⚠ 会连带产出已退役的"每日学习打卡表" |
| 早期全国双非 408 完整版（20260813） | `build_408.py` | **已过时**：真实输入已换代（现仅剩 20260820 基底），重跑得时点错配件；对应 4 个 20260813 产物已于 09-13 从库中删除 |
| 早期院校大全+备考指南（20260813） | `build_final.py` | **已断**：依赖已删的 `md_conv.py` 与库外素材，仅存档参考 |
| 终极版 20260824 html | `build_final_html.py` | 改路径可跑（历史代） |
| 终极版 20260824 xlsx | `make_final_xlsx.py` | 改路径可跑（历史代，10 Sheet） |
| 双非热度版 20260820 xlsx 反导出 | `make_shuangfei_xlsx.py` | 从 html 内嵌数组反导，改路径可跑 |
| 终极版 20260826 html（三源整合） | `integrate_three_sources.py` | **⛔ 禁直接重跑**（见下方警告） |
| 终极版 20260826 xlsx（与 html 同步） | `make_final_xlsx_v2.py` | 解析 20260826 html 的 S/C/K/O/SRCS + `var CB`（408 分位列）导出 12+Sheet；「2027改考动态」Sheet 读 `04-终极版择校/2027改考动态_20260820.md`（原 01 主文档已改造）；改数据/复核后重跑本脚本可保持 xlsx 与网页一致 |
| 09-03 复核修正打进两主网页 | `apply_verify_0903_pages.py` | 幂等补丁（已执行于 04 html 与 08 推荐器） |
| CodeBrick 分位数注入两主网页 | `inject_codebrick_pages.py` | 幂等补丁（检测 `var CB=` 已注入则跳过） |
| 浏览器页派生索引 | `build_school_browser_data.py` | 幂等；改动 06/10 两库 JSON 或本目录 xlsx 明细后重跑 |
| **统一院校库（学校 → 专业 → 各类数据）** | `build_unified_db.py` | **现役**：读 06 择校库 + 10 分数库 + `yz408_catalog`（招生单位代码）+ 01 导师正本 + 04 改考动态 + `dai408_scores` + `score_matrix` + `todo_patch_list` + `wangdao_links_all` + `catalog_2024~2027` → 生成 `06/data/kaoyan408.db`（SQLite，**24 表 + 2 视图 + 16 索引**；**本地生成、不入库**，已加 .gitignore）、`crosswalk.json`、`schools_unified.json`；含脏值数值化（`*_value`/`*_note`）与 CHECK 约束；纯 stdlib、跨平台、幂等；**任一源变更后重跑** |
| **页面字段回填（04/08/score_matrix）** | `patch_pages_from_db.py` | **现役**：从仓库正本补 04/08 页面与 `score_matrix.json` 的缺失字段（只补空、不覆盖手工值；幂等；改前自动备份到 `_bak/`）。干跑不加 `--apply` |
| **搜索索引 + 索引页** | `build_search_index.py` | **现役**：读 `kaoyan408.db` → 生成 `06-院校数据库/data/搜索索引.json`（894 KB 扁平索引）与 `06-院校数据库/索引.html`（单文件搜索页，索引内嵌，双击可离线打开）。支持按 校名/别名/招生单位代码/专业代码/专业名/学院 检索。**统一库变更后重跑** |
| **发布门禁（一条命令全流程自检）** | `publish_check.py` | 改完任何数据后跑：C1 索引再生 / C2 懒加载路径 / C3 `xlsx↔网页`同步 / C4 死链与本机路径泄露（Windows+类 Unix 双形态）/ C5 py 编译 / C7 生成脚本输入存在性 / C8 字段类型与数值可解析 / C9 规模口径对账 / C10 页面院校⊆统一库 / C11 全仓死链 / C12 来源分级（`sources.tier` 无空值）与冲突裁定规则文件存在。**全 PASS 再 commit+push**（C6 为信息性 git 状态） |

## 发布工作流（数据更新 → 上线）

1. 新资料归位：考情字段进 06 JSON，分数分位进 10 库（勿新增第四数据源）
2. 再生派生物：动过 04 html → `make_final_xlsx_v2.py`；动过任何数据源 → `build_school_browser_data.py`
3. 门禁：`python 09-生成脚本/publish_check.py`（exit 0 才继续）
4. 提交推送（origin 为 SSH）：`git -c core.sshCommand="C:/Windows/System32/OpenSSH/ssh.exe" push origin main`
5. 线上验证：curl 改动 URL 比对 200/字节一致（Pages 约 1~2 分钟生效）

## 🚫 已断链脚本（输入已不存在，勿重跑）

2026-09-22 实测：以下脚本引用的输入文件/目录**已不存在**，直接运行必然失败或产出错误结果。保留仅供追溯。

| 脚本 | 断链原因 |
|---|---|
| `build_score_matrix.py` | **`ext/` 目录整体缺失**（`ext/408-offerings.json`、`ext/awarer/universities.json`）→ 产出的 `score_matrix.json`(984 KB) / `dai408_scores.json`(630 KB) / `yz408_catalog.json`(473 KB) **永久不可再生** |
| `build_final_html.py` | 引用 `<SOURCE_DIR>\01_择校与规划\…`（目录已改名 `01-导师与规划`、原主文档已删除） |
| `make_final_xlsx.py` | 同上；且含未替换的 `<SOURCE_DIR>` 占位符 |
| `build_final.py` | 依赖已删的 `md_conv.py` 与库外素材 |
| `build_408.py` | 依赖 2026-09-13 已删的 20260813 一代产物 |
| `integrate_three_sources.py` | 引用旧目录 `06_终极版输出\`；**且重跑会覆盖 09-06 人工扩容** |
| `make_shuangfei_xlsx.py` | 引用库外 `<MATERIAL_DIR>\02_院校数据_原有\…` |
| `06-院校数据库/tools/validate_db.py` | `SCH` 指向库外脱敏路径，运行必 0 文件 |
| `06-院校数据库/tools/etl_build_db.py` | 引用库外归档路径；**且重跑会回退 09-03 复核与 09-13 补全** |

> 门禁 `publish_check.py` 的 **C7** 会扫描脚本输入是否存在：**现役脚本缺输入即 FAIL**；上表已登记脚本仅打 `INFO`（不阻断，但说明其产物不可再生）。新增断链会被 C7 立即发现。

## ⚠️ 重要警告

1. **`integrate_three_sources.py` 重跑会覆盖 09-06 的人工扩容**（+81 所 N诺候选 + 2024 考情参考 114 条），该扩容是直接在 html 上手工追加的，脚本不知道这回事。如需重跑，跑完后要重新合并扩容部分。
2. **`06-院校数据库/tools/etl_build_db.py` 与 `update_verify_0903.py` 同样不可盲目重跑**：现库中的 schools/*.json 与 conflicts_registry.json 已含 09-03 人工复核结论，重跑旧生成逻辑会回退这些修正。
3. 当前对 04 主网页的合规改动方式是"锚点幂等补丁"（参考 `apply_verify_0903_pages.py` / `inject_codebrick_pages.py` 的写法），不要整页重生成。
