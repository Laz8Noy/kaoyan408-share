# PRODUCT.md — 408 名词罗盘

## 产品是什么
面向 2027 考研 408 统考学习者的**四科专业名词轮盘索引**。数据来自用户自有的四本《专业名词手册》Markdown（数据结构 97 / 组成原理 58 / 操作系统 65 / 计算机网络 207，共 427 词条、24 章），及一份四科融合思维导图 PDF。

## 访客与场景
考研学生深夜复习，需要快速拨到某一章节、扫读术语并查看释义；兼作原典 PDF 的入口。

## 三幕结构
1. **Hero**：ScrollVelocity 描边跑马灯 + BlurText 标题 + TextType 打字副行 + Magnet 主按钮。
2. **书架**：SpotlightCard 四册选书（每科一条霓虹身份色）。
3. **罗盘**：章/节双 OptionWheel（reactbits 原版）联动，右侧词条手风琴列表（点击展开全文），顶栏可跳各科原典 PDF 与思维导图。

## 约束
- OptionWheel / TextType / BlurText / Magnet / ClickSpark / ScrollVelocity / SpotlightCard 使用 reactbits 原版源码（MIT），组件本体不改，仅外层适配。
- 无后端、纯静态；资源自托管（@fontsource）。
- 验收：用户人肉过清单，两轮封顶。
