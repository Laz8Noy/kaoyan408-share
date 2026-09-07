# 09 生成脚本

> 本目录仅保留数据表的**核心生成器**（共 8 个），其余一次性调试/排查脚本已清理（可从 git 历史找回）。

若要改数据重新导出 HTML/XLSX：

| 目标 | 脚本 |
|---|---|
| 择校与规划文档（打卡表、主 md 等） | `build_plan_v2.py` |
| 全国双非 408 完整版（20260813） | `build_408.py` |
| 终极版 20260824（html + xlsx） | `build_final.py` + `build_final_html.py` + `make_final_xlsx.py` |
| 终极版 20260826（html + xlsx，三源整合） | `integrate_three_sources.py` + `make_final_xlsx_v2.py` |
| 双非热度版 xlsx 反导出 | `make_shuangfei_xlsx.py` |

## ⚠️ 重要警告

**`integrate_three_sources.py` 重跑会覆盖 09-06 的人工扩容**（+81 所 N诺候选 + 2024 考情参考 114 条），该扩容是直接在 html 上手工追加的，脚本不知道这回事。如需重跑，跑完后要重新合并扩容部分。

运行前请读脚本头部，不要把 API Key 写进仓库。脚本内的本机路径已被脱敏为 `<SOURCE_DIR>` 等占位符，需按实际路径调整才能跑。
