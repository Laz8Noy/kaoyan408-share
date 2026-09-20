# -*- coding: utf-8 -*-
"""Flatten the 408 mind-map Markdown into per-subject ordered trees -> mindmap.json.

Document order + depth gives a single fisheye list: ancestors above, siblings
below, each scaled by distance from focus. kind: part|chapter|section|bullet.
"""
import json
import re
from pathlib import Path

SRC = Path(r"E:\for408\new thing\408备考资料\md_输出\408四科融合思维导图 1.md")
OUT = Path(__file__).resolve().parent.parent / "src" / "data" / "mindmap.json"

COLORS = {"数据结构": "#5b8cff", "计算机组成原理": "#35d0ba", "操作系统": "#ff5c7a", "计算机网络": "#ffb454"}
RE_H2 = re.compile(r"^##\s+(.*\S)\s*$")
RE_H3 = re.compile(r"^###\s+(.*\S)\s*$")
RE_H4 = re.compile(r"^####\s+(.*\S)\s*$")
RE_BULLET = re.compile(r"^(\s*)[-*]\s+(.*\S)\s*$")


def clean(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    subjects = []
    cur = None

    def new_subject(name):
        return {
            "name": name.replace("第一部分　", "").replace("第二部分　", "")
            .replace("第三部分　", "").replace("第四部分　", "").replace("（408）", "").strip(),
            "color": COLORS.get(name, "#5b8cff"),
            "items": [],
        }

    for raw in lines:
        if not raw.strip():
            continue
        m = RE_H2.match(raw)
        if m:
            name = m.group(1)
            # skip the doc preamble H1; keep only the four parts
            if "部分" not in name:
                continue
            cur = new_subject(name)
            subjects.append(cur)
            cur["items"].append({"t": clean(name), "d": 0, "k": "part"})
            continue
        if cur is None:
            continue
        m = RE_H3.match(raw)
        if m:
            cur["items"].append({"t": clean(m.group(1)), "d": 1, "k": "chapter"})
            continue
        m = RE_H4.match(raw)
        if m:
            cur["items"].append({"t": clean(m.group(1)), "d": 2, "k": "section"})
            continue
        m = RE_BULLET.match(raw)
        if m:
            indent = len(m.group(1))
            level = min(indent // 2, 6)
            cur["items"].append({"t": clean(m.group(2)), "d": 3 + level, "k": "bullet"})
            continue

    for s in subjects:
        print(f"{s['name']}: {len(s['items'])} nodes, max depth {max(i['d'] for i in s['items'])}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(subjects, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, f"{OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
