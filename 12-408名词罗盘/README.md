# 12-408 名词罗盘（atlas408）

reactbits 风格的 408 术语图鉴：四本《专业名词手册》+ 融合思维导图做成**轮盘式索引**，
三幕结构（翻书 → 转轮盘点名词 → 思维导图），点词条可看释义、跳原手册 PDF。

## 🌐 在线打开（免下载）

👉 [https://laz8noy.github.io/kaoyan408-share/12-408名词罗盘/](https://laz8noy.github.io/kaoyan408-share/12-408%E5%90%8D%E8%AF%8D%E7%BD%97%E7%9B%98/)

- `index.html` + `assets/`：构建产物，GitHub Pages 直接服务（相对路径，子目录可用）
- `sources/`：四本名词手册 + 思维导图的原始 PDF（页面里"查看原手册"指向这里，浏览器可在线读）
- `sounds/`：轮盘音效
- `project/`：**完整源码**（Vite + React 18）

## 本地改造 / 重新构建

```bash
cd project
npm install
npm run dev      # 开发（127.0.0.1:5175）
npm run build    # 重新出 dist/，把 dist/* 复制回本目录替换 index.html 与 assets/ 即可
```

注意：`vite.config.js` 已设 `base: './'`（相对 base），改子目录名/挪位置都不用重配；
`src/App.jsx` 里 PDF 链接走 `import.meta.env.BASE_URL`，不要写死 `/sources/`。

## 组件来源

OptionWheel / TextType 等组件取自 reactbits.dev（MIT，DavidHDev/react-bits），
`project/DESIGN.md` 记录了配色与动效设计口径。
