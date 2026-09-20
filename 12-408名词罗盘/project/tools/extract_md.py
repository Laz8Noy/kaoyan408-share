# -*- coding: utf-8 -*-
"""Parse the 4 term-handbook Markdown files into src/data/books.json."""
import json
import re
from pathlib import Path

SRC = Path(r"E:\for408\new thing\408备考资料\md_输出")
OUT = Path(__file__).resolve().parent.parent / "src" / "data" / "books.json"

BOOKS = [
    ("ds", "数据结构", "DS", "Data Structures", "数据结构专业名词手册.md",
     "线性表、树、图、查找与排序全家族", "#5b8cff"),
    ("co", "计算机组成原理", "CO", "Computer Organization", "计算机组成原理专业名词手册.md",
     "数据表示、存储层次、指令系统、CPU、总线与 I/O", "#35d0ba"),
    ("os", "操作系统", "OS", "Operating Systems", "操作系统专业名词手册.md",
     "进程线程、同步死锁、内存管理、文件与 I/O", "#ff5c7a"),
    ("cn", "计算机网络", "CN", "Computer Networks", "计算机网络专业名词手册.md",
     "一册通览六层协议栈：释义、缩写与考点", "#ffb454"),
]

RE_CHAPTER = re.compile(r"^#\s*第([1-9]\d?)章\s+(.+)$")
RE_SECTION = re.compile(r"^##\s*([1-9]\d?)\.([1-9]\d?)\s+(.+)$")
RE_TABLE_HDR = re.compile(r"^\|\s*名词\s*\|\s*英文/缩写\s*\|\s*含义与要点\s*\|\s*$")
RE_SEP = re.compile(r"^\|[\s:|-]+\|$")


def cells(line):
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def main():
    books = []
    for bid, name, abbr, en, fname, tagline, color in BOOKS:
        text = (SRC / fname).read_text(encoding="utf-8")
        chapters = []
        cur_ch = cur_sec = None
        in_terms_table = False
        intro_buf = []
        for raw in text.splitlines():
            line = raw.strip()
            m = RE_CHAPTER.match(line)
            if m:
                cur_ch = {"num": int(m.group(1)), "title": m.group(2).strip(),
                          "intro": "", "sections": []}
                chapters.append(cur_ch)
                cur_sec, in_terms_table = None, False
                intro_buf = []
                continue
            m = RE_SECTION.match(line)
            if m and cur_ch and int(m.group(1)) == cur_ch["num"]:
                cur_sec = {"num": f"{m.group(1)}.{m.group(2)}", "title": m.group(3).strip(),
                           "terms": []}
                cur_ch["sections"].append(cur_sec)
                in_terms_table = False
                continue
            if RE_TABLE_HDR.match(line):
                in_terms_table = True
                continue
            if in_terms_table:
                if RE_SEP.match(line):
                    continue
                if line.startswith("|"):
                    cs = cells(line)
                    if len(cs) >= 3 and cur_sec:
                        term = cs[0].replace("<br>", "")
                        en_txt = cs[1].replace("<br>", " ").replace(" — ", "").strip()
                        d = cs[2].replace("<br>", "")
                        if en_txt in ("—", "-", ""):
                            en_txt = ""
                        cur_sec["terms"].append({"t": term, "e": en_txt, "d": d})
                    continue
                in_terms_table = False
            if cur_sec is None and cur_ch is not None and line and not line.startswith(("#", ">", "!", "*", "|", "-")):
                intro_buf.append(line)
            if cur_sec is not None and intro_buf:
                cur_ch["intro"] = "".join(intro_buf)
                intro_buf = []
        for ch in chapters:
            ch["sections"] = [s for s in ch["sections"] if s["terms"]]
        chapters = [ch for ch in chapters if ch["sections"]]
        n_terms = sum(len(s["terms"]) for ch in chapters for s in ch["sections"])
        print(f"{name}: {len(chapters)} chapters / {n_terms} terms")
        books.append({"id": bid, "name": name, "abbr": abbr, "en": en,
                      "tagline": tagline, "color": color, "file": fname, "chapters": chapters})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(books, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, f"{OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
