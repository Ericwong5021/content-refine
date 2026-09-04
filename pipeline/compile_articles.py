#!/usr/bin/env python3
"""
Compile first-person markdown articles (Naval style) into structured articles.json.
"""

import json
import re
import sys
from pathlib import Path

def parse_article_md(file_path: Path, chapter_id: str):
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1. Title
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip().strip('"').strip("'")
            break

    # 2. Subtitle
    subtitle = ""
    for line in lines:
        if line.startswith("> "):
            subtitle = line[2:].strip().strip('"').strip("'")
            break

    # 3. Slug and Index
    stem = file_path.stem
    m = re.match(r"^(\d+)[-_](.*)$", stem)
    if m:
        index = int(m.group(1))
        slug_part = m.group(2)
    else:
        index = 1
        slug_part = stem

    article_id = f"{chapter_id}-{slug_part}"

    # 4. Citations & Sources from footer
    citations = []
    entry_ids = []

    # Find the sources block at the end
    source_block_started = False
    for line in lines:
        if re.search(r"(\*\*来源\*\*|### 来源)", line):
            source_block_started = True
            continue
        if source_block_started:
            # Match: - [1] [Label](URL) or - [1] Label (URL)
            cm = re.match(r"^\s*[-*]\s*\[(\d+)\]\s*\[(.*?)\]\((.*?)\)", line)
            if not cm:
                cm = re.match(r"^\s*[-*]\s*\[(\d+)\]\s*(.*?)\s*\((https?://.*?)\)", line)
            if cm:
                c_idx = int(cm.group(1))
                c_label = cm.group(2).strip().strip('"').strip("'")
                c_url = cm.group(3).strip()

                # Extract aweme_id from url
                id_m = re.search(r"/video/(\d+)", c_url)
                e_id = id_m.group(1) if id_m else ""
                
                citations.append({
                    "index": c_idx,
                    "entry_id": e_id,
                    "label": c_label
                })
                if e_id and e_id not in entry_ids:
                    entry_ids.append(e_id)

    return {
        "id": article_id,
        "chapter_id": chapter_id,
        "index": index,
        "title": title,
        "subtitle": subtitle,
        "source_entry_ids": entry_ids,
        "source_citations": citations,
        "body_md": text
    }

def compile_articles(naval_dir: Path, out_json: Path, book_json_path: Path = None):
    if not naval_dir.exists():
        raise FileNotFoundError(f"Naval directory not found: {naval_dir}")

    # Load book.json for chapter ordering if available
    chapter_order = []
    if book_json_path and book_json_path.exists():
        with open(book_json_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
            chapter_order = [c["id"] for c in book_data.get("chapters", [])]

    articles = []

    # Iterate chapters
    chapter_dirs = [d for d in naval_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]
    if chapter_order:
        chapter_dirs.sort(key=lambda d: chapter_order.index(d.name) if d.name in chapter_order else 999)
    else:
        chapter_dirs.sort(key=lambda d: d.name)

    for cdir in chapter_dirs:
        chapter_id = cdir.name
        md_files = sorted([f for f in cdir.glob("*.md") if not f.name.startswith((".", "_"))])
        for f in md_files:
            art = parse_article_md(f, chapter_id)
            articles.append(art)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Compiled {len(articles)} articles to {out_json}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: compile_articles.py <naval_dir> <out_json> [book_json]")
        sys.exit(1)
    book_json = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    compile_articles(Path(sys.argv[1]), Path(sys.argv[2]), book_json)
