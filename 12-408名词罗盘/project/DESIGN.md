# DESIGN.md — 白日霓虹（reactbits light 模式，2026-XX 由暗转浅）

## 世界
白底 `#f6f7fb` 叠三层柔光极光径向渐变（蓝 #4f6fff / 紫 #8f4fff / 粉 #ff4f8d，alpha 10–16%）；卡片为磨砂玻璃：`rgba(255,255,255,.72)` + 1px `rgba(18,26,43,.09)` 边 + blur(10px) + 大半径柔影，圆角 18–24px。文字主墨 `#121a2b`。

## 交互尺寸规则（用户指定）
- 章/节轮盘基础字号加大（1.55 / 1.28rem），轨道列宽 420px；
- 轮盘平时 `scale(.86)`，鼠标指向（hover/focus-within）放大到 `scale(1.04)`，0.5s 弹性过渡；
- 词条标题 hover 放大 `scale(1.14)`（transform-origin left bottom，弹性曲线）。

## 调色板
| 角色 | 值 | 用途 |
|---|---|---|
| bg | #05060a | 页面底 |
| ink | #eef2fa | 标题/选中文字 |
| mist | #9aa7bf | 正文次级（对比 >7:1） |
| faint | #5f6b81 | 弱标签/折叠摘要 |
| line | #ffffff14 | 描边/分隔 |
| accent-a/b/c | #4f7dff / #9a5cff / #ff5c9a | CTA 渐变、focus、光标 |
| DS #5b8cff · CO #35d0ba · OS #ff5c7a · CN #ffb454 | 科目身份色 | 轮盘辉光、chip、展开标题 |

## 字阶（Poppins 500/600/800 + Noto Sans SC + JetBrains Mono）
- Hero 标题 clamp(40,7.2vw,92)/800/字距-0.01em；跑马灯描边字 -webkit-text-stroke 1px
- 页标题 16/600（顶栏）；卡标题 23–31/700；词条标题 16.5/600
- 正文 14.5（展开）/13（摘要，line-clamp:1）；mono 标签 10.5–12，字距 .12–.28em 大写
- 数字一律 tabular（mono）

## 组件语言
- 按钮：渐变填充胶囊 + 底光呼吸动画（CTA）、或科目色描边 ghost（book-go）
- 卡片：SpotlightCard 鼠标聚光（科目色 20–30% alpha）
- 轮盘：reactbits 原版弧线排布，选中行辉光 text-shadow rgba(140,160,255,.4)
- chip：mono 小字 + 科目色 35% 边框胶囊

## 动法（一套语法）
场景切换：blur(10px)+y26 淡入 0.65s cubic-bezier(.22,.9,.3,1)（scene-in）；文字入场全部交给原版 BlurText；全局 ClickSpark 火花；hover 位移 ≤6px、0.3s；轮盘动效由原版 rAF 平滑负责。禁止再引入散装 gsap 场景动画。

## 浏览器表面
selection 紫底、scrollbar 细白条、focus-visible 蓝描边 offset 3px。
