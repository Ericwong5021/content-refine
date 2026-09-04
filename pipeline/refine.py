import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


class RefinementError(RuntimeError):
    pass


LOG_LOCK = threading.Lock()


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp_path, path)


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(value)
    os.replace(temp_path, path)


def emit(log_path, event, **fields):
    row = {"at": now(), "event": event, **fields}
    serialized = json.dumps(row, ensure_ascii=False)
    with LOG_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as handle:
            handle.write(serialized + "\n")
        print(serialized, flush=True)


def load_results(input_dir):
    results_dir = input_dir / "results"
    if not results_dir.is_dir():
        raise RefinementError(f"results directory does not exist: {results_dir}")
    rows = []
    for path in sorted(results_dir.glob("*.json")):
        value = json.loads(path.read_text())
        if value.get("status") == "COMPLETED":
            value["_source_path"] = path
            rows.append(value)
        elif value.get("status") != "UNAVAILABLE":
            raise RefinementError(f"invalid source status in {path}: {value.get('status')}")
    if not rows:
        raise RefinementError(f"no completed transcripts found in {results_dir}")
    return rows


def compact_author(author):
    if not isinstance(author, dict):
        return None
    keys = [
        "uid",
        "unique_id",
        "nickname",
        "signature",
        "custom_verify",
        "enterprise_verify_reason",
        "verification_type",
        "follower_count",
        "following_count",
        "favoriting_count",
        "total_favorited",
        "personal_tag_list",
    ]
    return {key: author.get(key) for key in keys if key in author}


def compact_collection(collection):
    if not isinstance(collection, dict):
        return None
    keys = ["mix_id", "mix_name", "desc", "create_time", "update_time", "mix_type", "statis", "status"]
    return {key: collection.get(key) for key in keys if key in collection}


def compact_promotions(promotions):
    keys = [
        "promotion_id",
        "gid",
        "title",
        "elastic_title",
        "title_prefix",
        "price",
        "market_price",
        "sales",
        "views",
        "item_type",
        "promotion_source",
        "cos_radio",
        "clicks",
        "label",
    ]
    return [{key: item.get(key) for key in keys if key in item} for item in promotions or [] if isinstance(item, dict)]


def compact_commerce(commerce):
    if not isinstance(commerce, dict):
        return None
    return {
        "is_ads": commerce.get("is_ads"),
        "is_from_ad_auth": commerce.get("is_from_ad_auth"),
        "is_life_item": commerce.get("is_life_item"),
        "promotions": compact_promotions(commerce.get("promotions")),
        "entertainment_product_info": commerce.get("entertainment_product_info"),
        "product_genre_info": commerce.get("product_genre_info"),
    }


def compact_relations(relations):
    if not isinstance(relations, dict):
        return None
    anchor_keys = ["id", "anchor_id", "type", "anchor_type", "title", "name", "keyword", "description"]
    anchors = [
        {key: item.get(key) for key in anchor_keys if key in item}
        for item in relations.get("anchors") or []
        if isinstance(item, dict)
    ]
    return {
        "anchors": anchors,
        "origin_comment_ids": relations.get("origin_comment_ids"),
        "origin_duet_resource_uri": relations.get("origin_duet_resource_uri"),
        "is_share_post": relations.get("is_share_post"),
        "is_duet_sing": relations.get("is_duet_sing"),
    }


def semantic_metadata(metadata):
    text = metadata.get("text") or {}
    taxonomy = metadata.get("taxonomy") or {}
    video = metadata.get("video") or {}
    music = metadata.get("music") or {}
    return {
        "identity": metadata.get("identity"),
        "publication": metadata.get("publication"),
        "text": {
            "description": text.get("description"),
            "item_title": text.get("item_title"),
            "preview_title": text.get("preview_title"),
            "caption": text.get("caption"),
            "video_text": text.get("video_text"),
            "hashtags": text.get("hashtags"),
            "mentions": text.get("mentions"),
        },
        "engagement": metadata.get("engagement"),
        "author": compact_author(metadata.get("author")),
        "media": {
            "duration": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
            "ratio": video.get("ratio"),
            "format": video.get("format"),
            "is_long_video": video.get("is_long_video"),
            "has_watermark": video.get("has_watermark"),
        },
        "music": {
            key: music.get(key)
            for key in ["id", "title", "author", "owner_nickname", "album", "duration", "is_original", "is_original_sound", "artists"]
            if key in music
        },
        "taxonomy": {
            "video_tags": taxonomy.get("video_tags"),
            "aweme_type_tags": taxonomy.get("aweme_type_tags"),
            "social_tags": taxonomy.get("social_tags"),
            "video_labels": taxonomy.get("video_labels"),
        },
        "collection": compact_collection(metadata.get("collection")),
        "series": metadata.get("series"),
        "relations": compact_relations(metadata.get("relations")),
        "commerce": compact_commerce(metadata.get("commerce")),
        "content_flags": metadata.get("content_flags"),
        "availability": metadata.get("availability"),
        "location": metadata.get("location"),
    }


def corpus_context(rows):
    hashtags = Counter()
    collections = {}
    author = None
    for row in rows:
        metadata = row.get("metadata") or {}
        text = metadata.get("text") or {}
        hashtags.update(tag for tag in text.get("hashtags") or [] if tag)
        collection = compact_collection(metadata.get("collection"))
        if collection and collection.get("mix_id"):
            collections[collection["mix_id"]] = collection
        candidate = compact_author(metadata.get("author"))
        if candidate and (not author or len(candidate) > len(author)):
            author = candidate
    return {
        "creator": author,
        "frequent_hashtags": [{"name": name, "count": count} for name, count in hashtags.most_common(30)],
        "collections": list(collections.values()),
    }


def ordered_rows(rows):
    return sorted(rows, key=lambda row: ((row.get("metadata") or {}).get("publication") or {}).get("create_time") or 0)


def neighbor_context(rows, index):
    neighbors = []
    for position in range(max(0, index - 2), min(len(rows), index + 3)):
        if position == index:
            continue
        row = rows[position]
        metadata = row.get("metadata") or {}
        text = metadata.get("text") or {}
        publication = metadata.get("publication") or {}
        neighbors.append(
            {
                "aweme_id": row.get("aweme_id"),
                "published_at": publication.get("published_at"),
                "description": text.get("description") or row.get("description") or row.get("title"),
                "hashtags": text.get("hashtags"),
                "collection": compact_collection(metadata.get("collection")),
            }
        )
    return neighbors


def build_prompt(row, creator_context, neighbors):
    metadata = row.get("metadata")
    transcription = row.get("transcription") or {}
    if row.get("pipeline_schema_version") != 2 or not metadata:
        raise RefinementError(f"source result must be enriched to pipeline_schema_version 2: {row['_source_path']}")
    if not transcription.get("text"):
        raise RefinementError(f"source result has no ASR text: {row['_source_path']}")
    payload = {
        "aweme_id": row["aweme_id"],
        "video_metadata": semantic_metadata(metadata),
        "creator_context": creator_context,
        "nearby_videos": neighbors,
        "asr": transcription,
    }
    rules = [
        "你只处理输入中的一个视频，不调用任何工具，不读取任何文件。",
        "corrected_transcript 必须是忠实逐字校订稿，不是改写、摘要或事实核查稿。",
        "保留作者立场、语气、论证、例子和可辨认的口语，只修正有证据支持的同音错字、专名、标点、断句和明显 ASR 重复。",
        "视频文案、标签、作者资料、合集和相邻视频只用于理解主题与校正术语，不能据此虚构音频中没有说出的句子。",
        "遇到无法由上下文可靠恢复的内容，保留最接近的 ASR 表达并写入 uncertainties，不要猜成确定事实。",
        "corrections 只记录实质性文字修正，不记录普通标点和分段。basis 必须明确指出依据来自 ASR 上下文、视频文案、标签、合集或作者上下文。",
        "把 corrected_transcript 按语义转换和论证层次分成自然段，可添加小标题，但不得删除内容。",
        "knowledge 只提取作者在本视频中明确表达的观点、论据、例子、引用和术语，不把作者观点表述成客观事实。",
        "description 独有而口播未出现的信息只能标记为 description 来源，不能混入 corrected_transcript。",
        "必须严格输出符合以下 JSON Schema 的单一 JSON 对象，不得遗漏必填字段：schema_version 必须为 1，language 必须为 \"zh-CN\"，aweme_id 必须等于输入的 aweme_id，且必须包含 corrected_transcript, sections, corrections, uncertainties, knowledge（含 thesis, viewpoints, arguments, examples, references, terms, book_topics）。",
    ]
    return "\n".join(["任务规则：", *[f"{index}. {rule}" for index, rule in enumerate(rules, 1)], "", "输入：", json.dumps(payload, ensure_ascii=False)])


def validate_refinement(value, aweme_id):
    if not isinstance(value, dict):
        raise RefinementError("Codex output is not a JSON object")
    if value.get("schema_version") != 1:
        raise RefinementError(f"Codex output schema_version is invalid: {value.get('schema_version')}")
    if value.get("aweme_id") != aweme_id:
        raise RefinementError(f"Codex output aweme_id mismatch: expected {aweme_id}, got {value.get('aweme_id')}")
    if not value.get("corrected_transcript"):
        raise RefinementError("Codex output corrected_transcript is empty")
    for key in ["sections", "corrections", "uncertainties"]:
        if not isinstance(value.get(key), list):
            raise RefinementError(f"Codex output {key} is not a list")
    if not isinstance(value.get("knowledge"), dict):
        raise RefinementError("Codex output knowledge is not an object")


def codex_version(codex_bin):
    process = subprocess.run([codex_bin, "--version"], capture_output=True, text=True)
    if process.returncode != 0:
        raise RefinementError(f"codex --version failed: {process.stderr[-1000:]}")
    return process.stdout.strip()


def run_codex(codex_bin, schema_path, prompt, model, timeout):
    with tempfile.TemporaryDirectory(prefix="douyin-codex-") as temp_dir:
        output_path = Path(temp_dir) / "last-message.json"
        command = [
            codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--cd",
            temp_dir,
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")
        started = time.monotonic()
        process = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout)
        elapsed = time.monotonic() - started
        if process.returncode != 0:
            raise RefinementError(
                f"codex exec failed with exit code {process.returncode}: stdout={process.stdout[-2000:]!r} stderr={process.stderr[-2000:]!r}"
            )
        if not output_path.exists():
            raise RefinementError("codex exec succeeded without output-last-message")
        raw_output = output_path.read_text().strip()
        if raw_output.startswith("```"):
            lines = raw_output.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_output = "\n".join(lines).strip()
        output = json.loads(raw_output, strict=False)
        events = []
        for line_number, line in enumerate(process.stdout.splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RefinementError(f"invalid Codex JSON event on line {line_number}: {error}") from error
        completed_turns = [event for event in events if event.get("type") == "turn.completed"]
        if len(completed_turns) != 1:
            raise RefinementError(f"expected exactly one completed Codex turn, got {len(completed_turns)}")
        tool_items = [
            event
            for event in events
            if event.get("type") == "item.completed"
            and (event.get("item") or {}).get("type") in {"command_execution", "mcp_tool_call", "web_search"}
        ]
        if tool_items:
            raise RefinementError(f"Codex used tools despite the single-pass constraint: {tool_items}")
        return output, process.stdout, process.stderr, elapsed, events


def build_index(results_dir, index_path):
    rows = []
    for path in sorted(results_dir.glob("*.json")):
        rows.append(json.loads(path.read_text()))
    temp_path = index_path.with_suffix(f"{index_path.suffix}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temp_path, index_path)
    return rows


def refine_target(
    position,
    source_index,
    row,
    rows,
    creator,
    run_id,
    codex_bin,
    cli_version,
    schema_path,
    model,
    timeout,
    output,
    results_dir,
    event_dir,
    log_path,
):
    aweme_id = row["aweme_id"]
    prompt = build_prompt(row, creator, neighbor_context(rows, source_index))
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    emit(log_path, "item_started", run_id=run_id, aweme_id=aweme_id, position=position, prompt_chars=len(prompt))
    refinement, stdout, stderr, elapsed, events = run_codex(codex_bin, schema_path, prompt, model, timeout)
    validate_refinement(refinement, aweme_id)
    turn_event = next(event for event in events if event.get("type") == "turn.completed")
    codex_event_path = event_dir / f"{aweme_id}.jsonl"
    write_text(codex_event_path, stdout)
    result = {
        "pipeline_schema_version": 1,
        "aweme_id": aweme_id,
        "url": row.get("url"),
        "status": "COMPLETED",
        "source_result_path": str(row["_source_path"]),
        "source_asr_sha256": hashlib.sha256(row["transcription"]["text"].encode()).hexdigest(),
        "prompt_sha256": prompt_sha256,
        "codex": {
            "cli_version": cli_version,
            "model": model or "configured-default",
            "elapsed_sec": round(elapsed, 3),
            "event_count": len(events),
            "turn_count": 1,
            "usage": turn_event.get("usage"),
            "event_path": str(codex_event_path.relative_to(output)),
            "stderr": stderr.strip(),
        },
        "refinement": refinement,
        "completed_at": now(),
    }
    write_json(results_dir / f"{aweme_id}.json", result)
    emit(
        log_path,
        "item_completed",
        run_id=run_id,
        aweme_id=aweme_id,
        elapsed_sec=round(elapsed, 3),
        corrected_chars=len(refinement["corrected_transcript"]),
        correction_count=len(refinement["corrections"]),
        uncertainty_count=len(refinement["uncertainties"]),
    )
    return aweme_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--schema", type=Path, default=Path(__file__).resolve().parent.parent / "schemas/douyin-transcript-refinement.schema.json")
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--aweme-id")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.schema.is_file():
        raise RefinementError(f"output schema does not exist: {args.schema}")
    if args.limit is not None and args.limit < 1:
        raise RefinementError("--limit must be at least 1")
    if args.timeout < 1:
        raise RefinementError("--timeout must be at least 1")
    if args.workers < 1:
        raise RefinementError("--workers must be at least 1")
    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise RefinementError("codex executable is not available")

    rows = ordered_rows(load_results(args.input))
    creator = corpus_context(rows)
    targets = [(index, row) for index, row in enumerate(rows) if not args.aweme_id or row.get("aweme_id") == args.aweme_id]
    if args.aweme_id and not targets:
        raise RefinementError(f"aweme_id not found among completed transcripts: {args.aweme_id}")
    if args.limit is not None:
        targets = targets[: args.limit]

    run_id = uuid.uuid4().hex
    results_dir = args.output / "results"
    event_dir = args.output / "codex-events"
    log_path = args.output / "events.jsonl"
    results_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)
    cli_version = codex_version(codex_bin)
    emit(
        log_path,
        "run_started",
        run_id=run_id,
        target_count=len(targets),
        codex_version=cli_version,
        model=args.model,
        workers=args.workers,
    )

    completed = 0
    skipped = 0
    work = []
    for position, (source_index, row) in enumerate(targets, 1):
        aweme_id = row["aweme_id"]
        result_path = results_dir / f"{aweme_id}.json"
        if result_path.exists() and not args.force:
            existing = json.loads(result_path.read_text())
            if existing.get("status") != "COMPLETED" or existing.get("aweme_id") != aweme_id:
                raise RefinementError(f"existing refinement result is invalid: {result_path}")
            skipped += 1
            emit(log_path, "item_skipped", run_id=run_id, aweme_id=aweme_id)
            continue
        work.append((position, source_index, row))

    work_iterator = iter(work)
    executor = ThreadPoolExecutor(max_workers=args.workers)
    active = {}
    try:
        for _ in range(min(args.workers, len(work))):
            position, source_index, row = next(work_iterator)
            future = executor.submit(
                refine_target,
                position,
                source_index,
                row,
                rows,
                creator,
                run_id,
                codex_bin,
                cli_version,
                args.schema.resolve(),
                args.model,
                args.timeout,
                args.output,
                results_dir,
                event_dir,
                log_path,
            )
            active[future] = row["aweme_id"]
        while active:
            future = next(as_completed(active))
            active.pop(future)
            future.result()
            completed += 1
            try:
                position, source_index, row = next(work_iterator)
            except StopIteration:
                continue
            next_future = executor.submit(
                refine_target,
                position,
                source_index,
                row,
                rows,
                creator,
                run_id,
                codex_bin,
                cli_version,
                args.schema.resolve(),
                args.model,
                args.timeout,
                args.output,
                results_dir,
                event_dir,
                log_path,
            )
            active[next_future] = row["aweme_id"]
    except Exception:
        for future in active:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)

    indexed = build_index(results_dir, args.output / "index.jsonl")
    summary = {
        "run_id": run_id,
        "status": "COMPLETED",
        "target_count": len(targets),
        "newly_completed": completed,
        "skipped": skipped,
        "result_count": len(indexed),
        "finished_at": now(),
    }
    write_json(args.output / "summary.json", summary)
    emit(log_path, "run_completed", **summary)


if __name__ == "__main__":
    main()
