#!/usr/bin/env python3
"""
content-refine CLI: Standardized workflow for creator content distillation.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = ROOT_DIR / "pipeline"
TEMPLATE_DIR = ROOT_DIR / "template"
SITES_DIR = ROOT_DIR / "sites"
CONTENT_STORE_DIR = ROOT_DIR / "content-store"


def cmd_site_create(args):
    site_id = args.id
    target_dir = SITES_DIR / site_id
    if target_dir.exists():
        print(f"Error: Site '{site_id}' already exists at {target_dir}")
        sys.exit(1)

    print(f"Creating site instance '{site_id}' from template...")
    # Copy template files
    shutil.copytree(TEMPLATE_DIR / "app", target_dir / "app")
    shutil.copytree(TEMPLATE_DIR / "public", target_dir / "public")
    for f in ["tsconfig.json", "next.config.ts", "postcss.config.mjs", "eslint.config.mjs"]:
        src = TEMPLATE_DIR / f
        if src.exists():
            shutil.copy(src, target_dir / f)

    # Prepare data dir
    (target_dir / "data").mkdir(parents=True, exist_ok=True)
    with open(target_dir / "data" / "articles.json", "w", encoding="utf-8") as f:
        f.write("[]\n")

    # Prepare package.json
    pkg = {
        "name": f"site-{site_id}",
        "version": "1.0.0",
        "private": True,
        "engines": {"node": ">=22.13.0"},
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "start": "next start",
            "lint": "eslint . --ignore-pattern dist --ignore-pattern .next"
        },
        "dependencies": {
            "next": "16.2.6",
            "react": "19.2.6",
            "react-dom": "19.2.6"
        },
        "devDependencies": {
            "@tailwindcss/postcss": "4.2.1",
            "@types/node": "22.19.19",
            "@types/react": "19.2.14",
            "@types/react-dom": "19.2.3",
            "eslint": "9.39.4",
            "eslint-config-next": "16.2.6",
            "tailwindcss": "4.2.1",
            "typescript": "5.9.3"
        },
        "type": "module"
    }
    with open(target_dir / "package.json", "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Prepare site.config.json
    cfg = {
        "id": site_id,
        "title": args.title or f"{site_id} 知识全景书",
        "subtitle": "把观点还给原文，把知识连成一本书",
        "author": args.author or site_id,
        "brandMark": args.brand_mark or site_id[:1].upper(),
        "theme": args.theme or "slate",
        "dek": "从商业认知到行动闭环，从一人公司到终身事业。",
        "description": args.description or f"{args.author or site_id} 的知识全景书与可追溯逐字稿。"
    }
    with open(target_dir / "site.config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Prepare content-store directory
    (CONTENT_STORE_DIR / site_id).mkdir(parents=True, exist_ok=True)

    print(f"✓ Site '{site_id}' created successfully!")
    print(f"  Directory: sites/{site_id}")
    print(f"  To run: pnpm --filter site-{site_id} dev")


def cmd_site_sync_template(args):
    target_sites = [args.id] if args.id else [d.name for d in SITES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
    print(f"Syncing template to {len(target_sites)} site(s): {', '.join(target_sites)}...")

    for s in target_sites:
        site_path = SITES_DIR / s
        if not site_path.exists():
            print(f"Skipping non-existent site: {s}")
            continue

        # Sync directories in app/
        for d in ["components", "article", "read", "lib"]:
            src = TEMPLATE_DIR / "app" / d
            dst = site_path / "app" / d
            if src.exists():
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)

        # Sync files in app/
        for f in ["page.tsx", "layout.tsx", "globals.css"]:
            src = TEMPLATE_DIR / "app" / f
            dst = site_path / "app" / f
            if src.exists():
                shutil.copy(src, dst)

        # Sync configs
        for cfg_file in ["tsconfig.json", "next.config.ts", "postcss.config.mjs", "eslint.config.mjs"]:
            src = TEMPLATE_DIR / cfg_file
            if src.exists():
                shutil.copy(src, site_path / cfg_file)

        print(f"  ✓ Synced {s}")
    print("Done!")


def cmd_pipeline_export(args):
    site_id = args.id
    local_asr = CONTENT_STORE_DIR / site_id / "local-asr"
    refined = CONTENT_STORE_DIR / site_id / "refined"
    out_book = SITES_DIR / site_id / "data" / "book.json"

    if not local_asr.exists() or not refined.exists():
        print(f"Error: Missing local-asr or refined directory in {CONTENT_STORE_DIR / site_id}")
        sys.exit(1)

    out_book.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PIPELINE_DIR / "export_site_data.py"),
        str(local_asr),
        str(refined),
        str(out_book)
    ]
    print(f"Exporting site data for '{site_id}'...")
    subprocess.run(cmd, check=True)
    print(f"✓ Exported: {out_book}")


def cmd_pipeline_compile_articles(args):
    site_id = args.id
    naval_dir = CONTENT_STORE_DIR / site_id / "naval-style"
    out_json = SITES_DIR / site_id / "data" / "articles.json"
    book_json = SITES_DIR / site_id / "data" / "book.json"

    if not naval_dir.exists():
        print(f"Error: Naval style directory not found at {naval_dir}")
        sys.exit(1)

    cmd = [
        sys.executable,
        str(PIPELINE_DIR / "compile_articles.py"),
        str(naval_dir),
        str(out_json),
        str(book_json)
    ]
    print(f"Compiling first-person articles for '{site_id}'...")
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="content-refine CLI")
    subparsers = parser.add_subparsers(dest="subcommand")

    # site:create
    p_create = subparsers.add_parser("site:create", help="Create a new site instance from template")
    p_create.add_argument("id", help="Site identifier (e.g. laoyao, linxi)")
    p_create.add_argument("--title", help="Site display title")
    p_create.add_argument("--author", help="Author name")
    p_create.add_argument("--brand-mark", help="Single character or icon mark")
    p_create.add_argument("--theme", help="Theme color name (slate, amber, etc.)")
    p_create.add_argument("--description", help="Site meta description")

    # site:sync-template
    p_sync = subparsers.add_parser("site:sync-template", help="Sync latest template components to site(s)")
    p_sync.add_argument("id", nargs="?", default=None, help="Target site id (optional, defaults to all)")

    # pipeline:export
    p_export = subparsers.add_parser("pipeline:export", help="Compile local-asr and refined into site data/book.json")
    p_export.add_argument("id", help="Site identifier")

    # pipeline:compile-articles
    p_compile = subparsers.add_parser("pipeline:compile-articles", help="Compile first-person markdown articles into data/articles.json")
    p_compile.add_argument("id", help="Site identifier")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "site:create":
        cmd_site_create(args)
    elif args.subcommand == "site:sync-template":
        cmd_site_sync_template(args)
    elif args.subcommand == "pipeline:export":
        cmd_pipeline_export(args)
    elif args.subcommand == "pipeline:compile-articles":
        cmd_pipeline_compile_articles(args)


if __name__ == "__main__":
    main()
