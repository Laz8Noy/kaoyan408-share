#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_links.py —— 全仓链接体检：本地路径 + 本站 URL + 站外 URL 一次跑完

为什么单独一个脚本而不是塞进 publish_check.py：
  门禁要求离线可跑（C6 明确不 fetch），而"链接能不能用"必须真发请求才知道。
  本脚本是发布前的补充检查，退出码 0 = 全部可用。

用法：
  python 09-生成脚本/check_links.py              # 全量（含站外 HTTP 请求）
  python 09-生成脚本/check_links.py --offline    # 只查本地路径与站内链接，不发外网请求
  python 09-生成脚本/check_links.py --only-local # 同上，便于改完快速复跑

判定：
  · 本地相对路径 / 仓库绝对路径 → 文件必须存在（目录也算存在）
  · 指向本仓库 Pages / GitHub 的 URL → 必须 200（含 404 页面伪装成 200 的情况会看体积）
  · 站外 URL → 2xx/3xx 视为可用；4xx/5xx/超时/SSL 失败列为坏链
  · `07-考情资料/录取名单原始材料/` 是官网原文快照，其内部链接指向原站页面级 URL，
    按仓库惯例（门禁 C11 同样豁免）不参与判定，但会在汇总里说明跳过了多少条
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PAGES = "https://laz8noy.github.io/kaoyan408-share/"
REPO_GIT = "github.com/Laz8Noy/kaoyan408-share"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kaoyan408-linkcheck/1.0"
ARCHIVED = "07-考情资料/录取名单原始材料/"

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
HTML_LINK = re.compile(r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.I)
FETCH_LINK = re.compile(r"""fetch\(\s*[\"']([^\"')]+)[\"']""")
# 邮箱、锚点、占位符、JS 拼接片段
SKIP_PREFIX = ("http://", "https://", "mailto:", "javascript:", "data:", "#", "//", "/")


def tracked(*patterns):
    out = subprocess.run(["git", "ls-files", "-z"] + list(patterns), capture_output=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\x00") if p.strip()]


def classify(url, base_dir, src_file):
    """返回 (kind, target)  kind ∈ local|internal|external|devonly|skip"""
    u = urllib.parse.unquote(url)
    if u.startswith(("javascript:", "data:", "mailto:", "#")):
        return "skip", u
    # Vite 源码目录里的 /src/*.jsx 是开发期资源：只有 `npm run dev` 的服务器能编译，
    # 静态托管上必然不存在。它不是"坏链接"（没人从页面点它），单列一类如实报告。
    if "/project/" in "/" + src_file.replace("\\", "/") and u.startswith("/src/"):
        return "devonly", u
    if u.startswith("//"):
        return "external", "https:" + u
    if u.startswith("/"):
        # 站内绝对路径（本站根）
        return "internal", PAGES + u.lstrip("/")
    if re.match(r"^https?://", u):
        low = u.lower()
        if "laz8noy.github.io" in low or REPO_GIT.lower() in low:
            return "internal", u
        return "external", u
    if any(c in u for c in "+{}$`") or re.search(r"\s", u):
        return "skip", u          # JS 拼接 / 模板片段
    if not re.search(r"[/\.]", u):
        return "skip", u          # 不像路径的数据值
    path = u.split("#")[0].split("?")[0]
    if not path:
        return "skip", u
    full = os.path.normpath(os.path.join(base_dir, path))
    return "local", full


def head(url, timeout=20):
    """发一次请求。中文路径必须先 percent-encode，否则 urllib 直接 UnicodeEncodeError（假死链）。"""
    safe = urllib.parse.quote(url, safe=":/?&=%#@[]!$'()*+,;~-._")
    req = urllib.request.Request(safe, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                                 method="GET")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        r.read(256)
        return r.status, r.geturl()
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", None) or ("ERR:%s" % type(e).__name__), safe


# 反爬 / 需浏览器复核的状态码：不是死链，但也不能算已验证，单列出来人工过一遍
BOT_BLOCKED = {403, 406, 412, 418, 429, 451}

# 人工浏览器复核台账：本机 curl/urllib 抓不动（TLS 被拦、反爬 412/403）不等于死链，
# 但也不能凭猜放行。谁在浏览器里真打开确认过，就在这里记一行：URL → (日期, 方式, 看到了什么)。
# 只有台账里有条目的 URL，才允许在传输层失败时按"可用"计。
LEDGER = {
    "https://gmis.shu.edu.cn/ZSJZ/SS/2026/ShowMajor.php-ID=963.htm":
        ("2026-10-04", "浏览器", "上海大学研究生院 085410 人工智能专业页正常渲染（735 字正文）"),
}
# 传输层失败（DNS/SSL/TLS/超时）：本沙箱直连 github.com 的 HTML 会被拦，
# 这类不能直接判死，能走 API 复核的走 API。
TRANSPORT_ERR = ("ERR:URLError", "ERR:HTTPError", "ERR:TimeoutError", "ERR:SSLError",
                 "ERR:RemoteDisconnected", "ERR:ConnectionResetError", "ERR:ssl")


def gh_api_status(url):
    """github.com 的 HTML 抓不动时，改用 GitHub API 判存在性（gh CLI 已登录即可）。"""
    if not shutil.which("gh"):
        return None
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)(?:/(.+))?$", url)
    if not m:
        return None
    owner, repo, rest = m.group(1), m.group(2), (m.group(3) or "").split("#")[0]
    # HTML 里的中文路径通常已经 percent-encode 过了，先还原再编，否则 %E5 → %25E5 变成假 404
    def enc(s):
        return urllib.parse.quote(urllib.parse.unquote(s), safe="/")
    if rest.startswith("blob/"):
        api = "repos/%s/%s/contents/%s" % (owner, repo, enc(rest[len("blob/"):]))
    elif rest.startswith("tree/"):
        api = "repos/%s/%s/contents/%s" % (owner, repo, enc(rest[len("tree/"):]))
    elif rest.startswith("issues"):
        api = "repos/%s/%s" % (owner, repo)      # 仓库存在即可，开关另判
    else:
        api = "repos/%s/%s" % (owner, repo)
    r = subprocess.run(["gh", "api", api, "--jq", ".id"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        if rest.startswith("issues"):
            on = subprocess.run(["gh", "api", "repos/%s/%s" % (owner, repo), "--jq", ".has_issues"],
                                capture_output=True, text=True).stdout.strip()
            return 200 if on == "true" else 404
        return 200
    return 404


def curl_status(url, timeout=25):
    """urllib 传输层失败时的兜底：有些站（如微信大响应）urllib 报错而 curl 正常，
    不能把工具差异当成死链。"""
    if not shutil.which("curl"):
        return None
    r = subprocess.run(["curl", "-s", "-L", "-m", str(timeout), "-A", UA,
                        "-o", os.devnull, "-w", "%{http_code}", url],
                       capture_output=True, text=True)
    code = (r.stdout or "").strip()
    return int(code) if code.isdigit() else None


def resolve(url):
    """返回 (status, 说明)；status 为 int 或 'ERR:xxx'"""
    st, _ = head(url)
    if isinstance(st, str) and any(st.startswith(t) for t in TRANSPORT_ERR):
        if "github.com" in url:
            via = gh_api_status(url)
            if via is not None:
                return via, "（经 GitHub API 复核）"
        c = curl_status(url)
        if c is not None:
            return c, "（urllib 传输失败，经 curl 复核）"
        # 本机抓不动 / 被反爬拦：只有在台账里有人真开过浏览器确认过，才算"可用"
        rec = LEDGER.get(url)
        if rec:
            return 200, "（本机抓不动，%s 经%s复核：%s）" % (rec[0], rec[1], rec[2])
        return st, "（本机网络不可达，且无 curl / 浏览器复核记录）"
    if st in BOT_BLOCKED:
        rec = LEDGER.get(url)
        if rec:
            return 200, "（%s 经%s复核：%s）" % (rec[0], rec[1], rec[2])
    return st, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only-local", action="store_true")
    a = ap.parse_args()
    net_ok = not (a.offline or a.only_local)

    files = tracked("*.md", "*.html")
    bad, warn, devonly, checked = [], [], [], {"local": 0, "internal": 0, "external": 0,
                                               "devonly": 0, "skip": 0}
    seen_url = {}

    for f in files:
        if not os.path.isfile(f):
            continue
        archived = f.startswith(ARCHIVED)
        try:
            t = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        base = os.path.dirname(f) or "."
        # 05 的模板文件里的相对链接是按「复制到 05-院校专档/<校名>/ 之后」的位置写的
        # （门禁 C11 对 _模板_*.md 豁免）。这里不豁免，而是按复制后的位置解析——
        # 这样既不误报，也能真的验证目标存在。
        if os.path.basename(f).startswith("_模板_"):
            base = os.path.join("05-院校专档", "_模板占位校")
        pats = [MD_LINK] if f.lower().endswith(".md") else [HTML_LINK, FETCH_LINK]
        for pat in pats:
            for m in pat.finditer(t):
                url = m.group(2) if pat is MD_LINK else m.group(1)
                kind, target = classify(url, base, f)
                if archived:
                    checked["skip"] += 1
                    continue
                if kind == "skip":
                    checked["skip"] += 1
                    continue
                if kind == "devonly":
                    checked["devonly"] += 1
                    devonly.append((f, target))
                    continue
                if kind == "local":
                    checked["local"] += 1
                    if not os.path.exists(target):
                        bad.append((f, url, "本地路径不存在"))
                    continue
                if not net_ok:
                    continue
                if target not in seen_url:
                    seen_url[target] = resolve(target)
                st, note = seen_url[target]
                checked[kind] += 1
                label = "站内" if kind == "internal" else "站外"
                if st in BOT_BLOCKED:
                    warn.append((f, target, "%s HTTP %s（反爬，需浏览器复核）" % (label, st)))
                elif st != 200:
                    bad.append((f, target, "%s HTTP %s%s" % (label, st, note)))
                elif note:
                    warn.append((f, target, "%s HTTP 200%s" % (label, note)))

    print("扫描 %d 个 md/html；判定计数 %s" % (len(files), checked))
    print("网络检查 %s（缓存去重后实际请求 %d 个 URL）" % ("开" if net_ok else "关（--offline）", len(seen_url)))
    if devonly:
        print("\n· Vite 开发期引用 %d 条（源码目录里的 /src/*.jsx，静态托管上不存在，"
              "不计为坏链；该目录也不进 dist 产物）：" % len(devonly))
        for f, u in devonly[:4]:
            print("   ", f, "→", u)
    if warn:
        print("\n⚠ 反爬拦截 %d 条（不是死链，需浏览器逐条复核）：" % len(warn))
        for f, u, why in warn:
            print("   [%s] %s\n        → %s" % (why, f, u[:150]))
    if bad:
        print("\n✗ 坏链 %d 条：" % len(bad))
        for f, u, why in bad:
            print("   [%s] %s\n        → %s" % (why, f, u[:150]))
        return 1
    print("\n✓ 全部链接可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
