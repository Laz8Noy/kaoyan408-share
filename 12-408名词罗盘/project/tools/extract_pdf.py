# -*- coding: utf-8 -*-
"""Extract 408 term handbooks (chapter/section/term/definition) into books.json."""
import json
import re
import sys
from pathlib import Path

import pypdf

SRC = Path(r"E:\for408\new thing\408备考资料")
OUT = Path(__file__).resolve().parent.parent / "src" / "data" / "books.json"

BOOKS = [
    {
        "id": "ds",
        "name": "数据结构",
        "abbr": "DS",
        "en": "Data Structures",
        "file": "数据结构专业名词手册.pdf",
        "tagline": "线性表、树、图、查找与排序全家族",
        "hue": 213,
    },
    {
        "id": "co",
        "name": "计算机组成原理",
        "abbr": "CO",
        "en": "Computer Organization",
        "file": "计算机组成原理专业名词手册.pdf",
        "tagline": "数据表示、存储层次、指令系统、CPU、总线与 I/O",
        "hue": 168,
    },
    {
        "id": "os",
        "name": "操作系统",
        "abbr": "OS",
        "en": "Operating Systems",
        "file": "操作系统专业名词手册.pdf",
        "tagline": "进程线程、同步死锁、内存管理、文件与 I/O",
        "hue": 348,
    },
    {
        "id": "cn",
        "name": "计算机网络",
        "abbr": "CN",
        "en": "Computer Networks",
        "file": "计算机网络专业名词手册.pdf",
        "tagline": "一册通览六层协议栈：释义、缩写与考点",
        "hue": 40,
    },
]

RE_CHAPTER = re.compile(r"^第\s*([1-9]\d?)\s*章\s*(\S.*)$")
RE_SECTION = re.compile(r"^([1-9]\d?)\s*[.．]\s*([1-9]\d?)\s+(\S.*)$")
RE_NOISE = re.compile(
    r"^("
    r"[-–—]\s*\d+\s*[-–—]"           # page footer "- 3 -"
    r"|表\s*\d+[-–—]\d+.*"            # table caption
    r"|图\s*\d+[-–—]\d+.*"            # figure caption (standalone line)
    r"|名词\s*$|英文/缩写\s*$|含义与要点\s*$"
    r"|.*手册\s*·\s*408统考.*"
    r"|名词\s*·\s*含义\s*·\s*关系.*"
    r"|408\s*统考.*|考纲全覆盖.*"
    r")$"
)
RE_ENG = re.compile(r"^[A-Za-z][A-Za-z0-9 ()/\-\u2013\u2019',.&+:%×~\[\]#\"]*$")
RE_DEF_END = re.compile(r"[。．]\s*$|[）)]\s*$")


def looks_eng(line: str) -> bool:
    l = line.strip()
    if l in ("—", "-", "--", "/"):
        return True  # empty english marker
    return bool(RE_ENG.match(l))


def parse_text(text: str):
    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip() != ""]
    chapters = {}  # num -> {"title", "sections": {num -> {...}}}
    cur_ch, cur_sec = None, None
    # section body modes
    mode = "desc"  # desc | term | eng | def
    term_buf, def_buf, eng_buf = [], [], []

    def close_section():
        nonlocal mode, term_buf, def_buf, eng_buf, cur_sec
        flush_entry()
        cur_sec = None

    def flush_entry():
        nonlocal mode, term_buf, def_buf, eng_buf
        if term_buf and def_buf and cur_sec is not None:
            cur_sec["terms"].append(
                {
                    "term": "".join(term_buf),
                    "en": " ".join(eng_buf).strip(),
                    "def": "".join(def_buf),
                }
            )
        term_buf, def_buf, eng_buf = [], [], []
        mode = "term"

    i = 0
    for raw in lines:
        line = raw.strip()
        if RE_NOISE.match(line):
            continue
        m = RE_CHAPTER.match(line)
        if m:
            close_section()
            num = int(m.group(1))
            cur_ch = chapters.setdefault(num, {"num": num, "title": m.group(2).strip(), "sections": {}})
            cur_sec, mode = None, "desc"
            continue
        m = RE_SECTION.match(line)
        # section headers inside a chapter, with num matching chapter (guard: 1.2 style)
        if m and cur_ch is not None and int(m.group(1)) == cur_ch["num"]:
            close_section()
            snum = f"{m.group(1)}.{m.group(2)}"
            cur_sec = {"num": snum, "title": m.group(3).strip(), "desc": "", "terms": []}
            cur_ch["sections"][snum] = cur_sec
            mode = "desc"
            continue
        if cur_sec is None:
            continue  # chapter intro / cover noise
        # inside a section table
        if mode == "desc":
            if line.startswith("名词"):
                mode = "term"
            else:
                cur_sec["desc"] += line
            continue
        if mode == "term":
            if looks_eng(line):
                if term_buf:
                    eng_buf.append(line)
                    mode = "eng"
                # stray english without term -> skip
                continue
            term_buf.append(line)
            continue
        if mode == "eng":
            if looks_eng(line):
                eng_buf.append(line)
                continue
            mode = "def"
        if mode == "def":
            def_buf.append(line)
            if RE_DEF_END.search(line) and len("".join(def_buf)) >= 4:
                # definition may still continue if it ended with ）but no 。— check next:
                # simple rule: ends with 。 -> close; ends with ） -> keep collecting until 。 or next term-ish line
                if line.rstrip().endswith("。") or line.rstrip().endswith("．"):
                    flush_entry()
            continue
    close_section()
    return chapters


def clean_book(spec):
    path = SRC / spec["file"]
    reader = pypdf.PdfReader(str(path))
    text = "".join((pg.extract_text() or "") + "\n" for pg in reader.pages)
    chapters = parse_text(text)
    out = []
    for cnum in sorted(chapters):
        ch = chapters[cnum]
        secs = []
        for s in ch["sections"].values():
            if s["terms"]:
                secs.append(
                    {
                        "num": s["num"],
                        "title": s["title"],
                        "desc": s["desc"].strip()[:220],
                        "terms": s["terms"],
                    }
                )
        if secs:
            out.append({"num": ch["num"], "title": ch["title"], "sections": secs})
    return out


def main():
    books = []
    for spec in BOOKS:
        chapters = clean_book(spec)
        n_terms = sum(len(t["terms"]) for c in chapters for t in c["sections"])
        print(f"{spec['name']}: {len(chapters)} chapters, {n_terms} terms")
        books.append({**{k: spec[k] for k in ("id", "name", "abbr", "en", "tagline", "hue")}, "chapters": chapters})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(books, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    sys.exit(main())
