# 09 生成脚本

> 本目录收录数据表的生成器与主页补丁脚本（共 11 个），一次性调试/排查脚本早已清理（可从 git 历史找回）。
> 多数脚本内的本机路径被脱敏为 `<SOURCE_DIR>` 等占位符，运行前需按实际路径调整；不要把 API Key 写进仓库。

| 目标 | 脚本 | 状态 |
|---|---|---|
| 择校与规划文档（主 md/html/xlsx） | `build_plan_v2.py` | 数据内联可跑（OUT_DIR 需改）；⚠ 会连带产出已退役的"每日学习打卡表" |
| 早期全国双非 408 完整版（20260813） | `build_408.py` | **已过时**：真实输入已换代（现仅剩 20260820 基底），重跑得时点错配件；对应 4 个 20260813 产物已于 09-13 从库中删除 |
| 早期院校大全+备考指南（20260813） | `build_final.py` | **已断**：依赖已删的 `md_conv.py` 与库外素材，仅存档参考 |
| 终极版 20260824 html | `build_final_html.py` | 改路径可跑（历史代） |
| 终极版 20260824 xlsx | `make_final_xlsx.py` | 改路径可跑（历史代，10 Sheet） |
| 双非热度版 20260820 xlsx 反导出 | `make_shuangfei_xlsx.py` | 从 html 内嵌数组反导，改路径可跑 |
| 终极版 20260826 html（三源整合） | `integrate_three_sources.py` | **⛔ 禁直接重跑**（见下方警告） |
| 终极版 20260826 xlsx（与 html 同步） | `make_final_xlsx_v2.py` | 解析 20260826 html 的 S/C/K/O/SRCS + `var CB`（408 分位列）导出 12+Sheet；改数据/复核后重跑本脚本可保持 xlsx 与网页一致 |
| 09-03 复核修正打进两主网页 | `apply_verify_0903_pages.py` | 幂等补丁（已执行于 04 html 与 08 推荐器） |
| CodeBrick 分位数注入两主网页 | `inject_codebrick_pages.py` | 幂等补丁（检测 `var CB=` 已注入则跳过） |
| 浏览器页派生索引 | `build_school_browser_data.py` | 幂等；改动 06/10 两库 JSON 或本目录 xlsx 明细后重跑 |
| **发布门禁（一条命令全流程自检）** | `publish_check.py` | 改完任何数据后跑：自动再生索引 + 懒加载路径/`xlsx↔网页`同步/死链与本机路径泄露/py 编译 六项检查，全 PASS 再 commit+push |

## 发布工作流（数据更新 → 上线）

1. 新资料归位：考情字段进 06 JSON，分数分位进 10 库（勿新增第四数据源）
2. 再生派生物：动过 04 html → `make_final_xlsx_v2.py`；动过任何数据源 → `build_school_browser_data.py`
3. 门禁：`python 09-生成脚本/publish_check.py`（exit 0 才继续）
4. 提交推送（origin 为 SSH）：`git -c core.sshCommand="C:/Windows/System32/OpenSSH/ssh.exe" push origin main`
5. 线上验证：curl 改动 URL 比对 200/字节一致（Pages 约 1~2 分钟生效）

## ⚠️ 重要警告

1. **`integrate_three_sources.py` 重跑会覆盖 09-06 的人工扩容**（+81 所 N诺候选 + 2024 考情参考 114 条），该扩容是直接在 html 上手工追加的，脚本不知道这回事。如需重跑，跑完后要重新合并扩容部分。
2. **`06-院校数据库/tools/etl_build_db.py` 与 `update_verify_0903.py` 同样不可盲目重跑**：现库中的 schools/*.json 与 conflicts_registry.json 已含 09-03 人工复核结论，重跑旧生成逻辑会回退这些修正。
3. 当前对 04 主网页的合规改动方式是"锚点幂等补丁"（参考 `apply_verify_0903_pages.py` / `inject_codebrick_pages.py` 的写法），不要整页重生成。
