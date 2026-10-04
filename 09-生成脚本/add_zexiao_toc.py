#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
add_zexiao_toc.py —— 给「04-终极版择校」页补可折叠目录、章节锚点与口径脚注

为什么是这个脚本而不是改生成器：
  终极版择校页由 integrate_three_sources.py 三源整合而来，README 明确警告**不可盲目重跑**
  （页面里含 09-03 之后的人工扩容与复核结果）。因此沿用本仓既有约定：
  用「锚点幂等补丁」就地改页面，而不是再生成一次。参照 apply_verify_0903_pages.py 的写法。

幂等性：
  所有插入内容都包在 QODER:TOC / QODER:TOCSTYLE / QODER:FOOT 标记对里，
  重跑先摘掉旧块再按当前标题重插；标题 id 一旦写上就复用（不重复编号）。

用法：
  python 09-生成脚本/add_zexiao_toc.py                # 处理 04 目录里日期最新的终极版
  python 09-生成脚本/add_zexiao_toc.py --check        # 只检查不写盘（门禁可用）
"""
import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D04 = os.path.join(ROOT, "04-终极版择校")
PREFIX = "全国408_085410双非热度版_终极版_"

B_TOC = "QODER:TOC"
B_STYLE = "QODER:TOCSTYLE"
B_FOOT = "QODER:FOOT"

STYLE = """<style id="qoder-toc-style">
/* 由 09-生成脚本/add_zexiao_toc.py 注入：目录与口径脚注样式（勿手改，改脚本） */
.q-toc{margin:14px 0 18px;border:1px solid #dfe3ea;border-radius:10px;background:#fff;color:#1c2028}
.q-toc>summary{cursor:pointer;padding:10px 14px;font-weight:600;font-size:13.5px;list-style:none}
.q-toc>summary::-webkit-details-marker{display:none}
.q-toc>summary::before{content:'\\25B8 ';color:#2f6bd8}
.q-toc[open]>summary::before{content:'\\25BE '}
.q-toc>summary small{font-weight:400;color:#8d97a6;margin-left:8px}
.q-toc ol{margin:0;padding:0 14px 12px 34px;columns:2;column-gap:26px}
.q-toc li{margin:3px 0;break-inside:avoid}
.q-toc a{color:#2f6bd8;text-decoration:none}
.q-toc a:hover{text-decoration:underline}
.q-toc .l3{padding-left:12px;font-size:12.5px;color:#5b6472}
.q-toc .l3 a{color:#5b6472}
.q-foot{margin:26px 0 8px;padding:12px 14px;border-top:1px solid #dfe3ea;font-size:12.5px;color:#5b6472}
.q-foot a{color:#2f6bd8}
@media(max-width:640px){.q-toc ol{columns:1}}
</style>"""


def strip_block(html, marker):
    """摘掉 <!-- MARKER:BEGIN --> ... <!-- MARKER:END --> 整块（含标记）

    刻意不吃标记前后的换行：插入侧也不额外加换行，两边对称，重跑字节数才不会再变（幂等）。
    """
    pat = re.compile(r"<!-- %s:BEGIN -->.*?<!-- %s:END -->" % (marker, marker), re.S)
    return pat.subn("", html)


def heading_label(text):
    """标题正文 → 目录短语：截到第一个分隔符前，避免把整段说明搬进目录"""
    t = re.sub(r"<[^>]+>", "", text)
    t = re.sub(r"\s+", " ", t).strip()
    for sep in (" · ", "｜", "（", "("):
        i = t.find(sep)
        if 6 < i <= 30:
            t = t[:i].strip()
            break
    return t[:34] if len(t) > 34 else t


def ensure_ids(html):
    """给每个 h2/h3 保证有 id：已有的复用，没有的按出现顺序补 sec-N

    <script> 里的 <h3> 是 JS 模板字符串拼出来的（本页实测 2 处），既不能进目录也不该被改写，
    所以先算出脚本区间，落在其中的匹配原样返回。
    """
    spans = [(m.start(), m.end()) for m in re.finditer(r"<script[^>]*>.*?</script>", html, re.S)]

    def in_script(i):
        return any(a <= i < b for a, b in spans)

    out = []
    n = [0]

    def repl(m):
        if in_script(m.start()):
            return m.group(0)
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        if "id=" in attrs:
            hid = re.search(r'id="([^"]+)"', attrs).group(1)
        else:
            n[0] += 1
            hid = "sec-%d" % n[0]
            attrs = attrs + ' id="%s"' % hid
        out.append((tag, hid, heading_label(inner)))
        return "<%s%s>%s</%s>" % (tag, attrs, inner, tag)

    html = re.sub(r"<(h[23])([^>]*)>(.*?)</\1>", repl, html, flags=re.S)
    return html, out


def build_toc(items):
    if not items:
        return ""
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lis = "".join('<li class="%s"><a href="#%s">%s</a></li>'
                  % ("l3" if t == "h3" else "l2", hid, esc(lab))
                  for t, hid, lab in items)
    n2 = sum(1 for t, _, _ in items if t == "h2")
    return ('<details class="q-toc"><summary>目录<small>%d 节 / %d 小节 · 手机端先收着</small></summary>'
            '<ol>%s</ol></details>' % (n2, len(items) - n2, lis))


def wrap(marker, body):
    return "<!-- %s:BEGIN -->\n%s\n<!-- %s:END -->" % (marker, body, marker)


def newest_page():
    if not os.path.isdir(D04):
        return None
    c = sorted(f for f in os.listdir(D04) if f.startswith(PREFIX) and f.endswith(".html"))
    return os.path.join(D04, c[-1]) if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查不写盘")
    ap.add_argument("page", nargs="?", help="目标 html（默认取 04 目录日期最新的终极版）")
    a = ap.parse_args()

    page = a.page or (newest_page() if os.path.isdir(D04) else None)
    if not page or not os.path.isfile(page):
        print("✗ 找不到目标页面：%s" % page)
        return 1
    html = io.open(page, encoding="utf-8").read()
    orig = html

    # 1. 先摘掉旧的三块，保证重跑不会叠加
    for mk in (B_TOC, B_STYLE, B_FOOT):
        html, _ = strip_block(html, mk)

    # 2. 标题补 id + 生成目录
    html, items = ensure_ids(html)
    toc = build_toc(items)
    if not toc:
        print("✗ 页面上没找到 h2/h3，拒绝插入空目录")
        return 1

    # 3. 目录插在 </header> 之后；没有 header 就插 <body...> 之后
    anchor = "</header>"
    if anchor in html:
        i = html.index(anchor) + len(anchor)
    else:
        m = re.search(r"<body[^>]*>", html)
        if not m:
            print("✗ 既没有 </header> 也没有 <body>，无法定位插入点")
            return 1
        i = m.end()
    html = html[:i] + wrap(B_TOC, toc) + html[i:]

    # 4. 样式插进 <head>
    if "</head>" in html:
        html = html.replace("</head>", wrap(B_STYLE, STYLE) + "</head>", 1)
    else:
        print("✗ 没有 </head>，样式无处可放")
        return 1

    # 5. 口径脚注：本页规模必须带限定语，且给新入口（索引页）留回程
    foot = ('<div class="q-foot">本页 <b>148 行</b> 是「04-0826 内嵌 var S 的主体院校行」，'
            '与索引页的 <b>511 校</b>（统一库全部学校，含仅目录 / 仅链接）、总库的 <b>177 校</b>'
            '（06 择校库）指代不同文件，不是互相矛盾；全部规模口径以 '
            '<a href="https://github.com/Laz8Noy/kaoyan408-share/blob/main/docs/%E5%8F%A3%E5%BE%84.md"'
            ' target="_blank" rel="noopener">docs/口径.md</a> 为准。'
            ' 想按院校 / 专业代码检索：回 <a href="../06-%E9%99%A2%E6%A0%A1%E6%95%B0%E6%8D%AE%E5%BA%93/'
            '%E7%B4%A2%E5%BC%95.html">408 院校索引</a>。</div>')
    if "</body>" in html:
        html = html.replace("</body>", wrap(B_FOOT, foot) + "</body>", 1)
    else:
        html = html + wrap(B_FOOT, foot)

    rel = os.path.relpath(page, ROOT).replace(os.sep, "/")
    if a.check:
        changed = html != orig
        print("%s %s：目录 %d 项 / 需要写盘=%s" % ("[check]" if changed else "[ok]", rel, len(items), changed))
        return 0

    io.open(page, "w", encoding="utf-8", newline="\n").write(html)
    print("✓ %s：目录 %d 项（h2 %d / h3 %d），新增 id %d 个，字节 %d → %d"
          % (rel, len(items), sum(1 for t, _, _ in items if t == "h2"),
             sum(1 for t, _, _ in items if t == "h3"),
             html.count(' id="sec-'), len(orig), len(html)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
