import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_douyin_knowledge_book import CHAPTERS, classify


class EbookDataError(RuntimeError):
    pass


def load_json_files(directory):
    if not directory.is_dir():
        raise EbookDataError(f"directory does not exist: {directory}")
    values = {}
    for path in sorted(directory.glob("*.json")):
        value = json.loads(path.read_text())
        aweme_id = value.get("aweme_id")
        if not aweme_id:
            raise EbookDataError(f"file has no aweme_id: {path}")
        if aweme_id in values:
            raise EbookDataError(f"duplicate aweme_id: {aweme_id}")
        value["_path"] = str(path.resolve())
        values[aweme_id] = value
    return values


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temp_path, path)


def paragraphs(text):
    values = [value.strip() for value in re.split(r"\n\s*\n+", text.strip()) if value.strip()]
    if not values:
        raise EbookDataError("corrected transcript has no paragraphs")
    return [{"id": f"p-{index:03d}", "index": index, "text": value} for index, value in enumerate(values, 1)]


def token_set(text):
    cleaned = str(text or "").lower()
    for phrase in ["作者认为", "作者主张", "作者观察到", "作者指出", "作者用", "作者以", "作者借", "在作者看来"]:
        cleaned = cleaned.replace(phrase, "")
    characters = [character for character in cleaned if "\u4e00" <= character <= "\u9fff" or character.isalnum()]
    compact = "".join(characters)
    tokens = set(re.findall(r"[a-z0-9][a-z0-9-]{1,}", cleaned))
    tokens.update(compact[index:index + 2] for index in range(max(0, len(compact) - 1)))
    tokens.update(compact[index:index + 3] for index in range(max(0, len(compact) - 2)))
    return {token for token in tokens if token}


def citation(query, transcript):
    query_tokens = token_set(query)
    if not query_tokens:
        return {"paragraph_id": None, "score": 0, "match": "video"}
    ranked = []
    for paragraph in transcript:
        paragraph_tokens = token_set(paragraph["text"])
        overlap = len(query_tokens & paragraph_tokens)
        coverage = overlap / len(query_tokens)
        union = len(query_tokens | paragraph_tokens)
        jaccard = overlap / union if union else 0
        ranked.append((coverage * 0.8 + jaccard * 0.2, paragraph["index"], paragraph["id"]))
    score, _, paragraph_id = max(ranked)
    if score < 0.05:
        return {"paragraph_id": None, "score": round(score, 4), "match": "video"}
    return {
        "paragraph_id": paragraph_id,
        "score": round(score, 4),
        "match": "strong" if score >= 0.14 else "related",
    }


def cited_strings(values, transcript):
    return [{"text": value, "citation": citation(value, transcript)} for value in values or []]


def cited_arguments(values, transcript):
    return [
        {
            "claim": value["claim"],
            "support": value["support"],
            "source": value["source"],
            "citation": citation(f"{value['claim']} {value['support']}", transcript),
        }
        for value in values or []
    ]


def cited_terms(values, transcript):
    return [
        {
            "term": value["term"],
            "contextual_meaning": value["contextual_meaning"],
            "citation": citation(f"{value['term']} {value['contextual_meaning']}", transcript),
        }
        for value in values or []
    ]


def entry_record(source, refinement, chapter_id, index):
    metadata = source["metadata"]
    text = metadata.get("text") or {}
    publication = metadata.get("publication") or {}
    knowledge = refinement["refinement"]["knowledge"]
    transcript = paragraphs(refinement["refinement"]["corrected_transcript"])
    title = text.get("item_title") or text.get("description") or source.get("title") or source["aweme_id"]
    transcript_text = "\n\n".join(paragraph["text"] for paragraph in transcript)
    return {
        "id": source["aweme_id"],
        "index": index,
        "chapter_id": chapter_id,
        "title": title,
        "description": text.get("description"),
        "published_at": publication.get("published_at"),
        "published_timestamp": publication.get("create_time"),
        "video_url": source.get("url"),
        "duration_seconds": source.get("audio_duration_s"),
        "hashtags": text.get("hashtags") or [],
        "engagement": metadata.get("engagement") or {},
        "thesis": knowledge["thesis"],
        "thesis_citation": citation(knowledge["thesis"], transcript),
        "viewpoints": cited_strings(knowledge["viewpoints"], transcript),
        "arguments": cited_arguments(knowledge["arguments"], transcript),
        "examples": cited_strings(knowledge["examples"], transcript),
        "references": cited_strings(knowledge["references"], transcript),
        "terms": cited_terms(knowledge["terms"], transcript),
        "topics": knowledge["book_topics"],
        "sections": refinement["refinement"]["sections"],
        "corrections": refinement["refinement"]["corrections"],
        "uncertainties": refinement["refinement"]["uncertainties"],
        "transcript": transcript,
        "transcript_sha256": hashlib.sha256(transcript_text.encode()).hexdigest(),
        "source_asr_sha256": refinement.get("source_asr_sha256"),
        "prompt_sha256": refinement.get("prompt_sha256"),
        "source_record_sha256": hashlib.sha256(Path(source["_path"]).read_bytes()).hexdigest(),
        "refinement_record_sha256": hashlib.sha256(Path(refinement["_path"]).read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("refined", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    sources = load_json_files(args.source / "results")
    refinements = load_json_files(args.refined / "results")
    completed = {aweme_id: value for aweme_id, value in sources.items() if value.get("status") == "COMPLETED"}
    unavailable = {aweme_id: value for aweme_id, value in sources.items() if value.get("status") == "UNAVAILABLE"}
    invalid_statuses = sorted(
        (aweme_id, value.get("status"))
        for aweme_id, value in sources.items()
        if value.get("status") not in {"COMPLETED", "UNAVAILABLE"}
    )
    if invalid_statuses:
        raise EbookDataError(f"invalid source statuses: {invalid_statuses}")
    if set(completed) != set(refinements):
        missing = sorted(set(completed) - set(refinements))
        extra = sorted(set(refinements) - set(completed))
        raise EbookDataError(f"source/refinement mismatch: missing={missing}, extra={extra}")

    chapter_entries = {chapter["id"]: [] for chapter in CHAPTERS}
    classification = {}
    for aweme_id, source in completed.items():
        chapter_id, scores = classify(source, refinements[aweme_id])
        classification[aweme_id] = {"chapter_id": chapter_id, "scores": scores}
        chapter_entries[chapter_id].append((source, refinements[aweme_id]))
    for values in chapter_entries.values():
        values.sort(key=lambda pair: pair[0]["metadata"]["publication"].get("create_time") or 0)

    entries = []
    chapters = []
    index = 1
    for chapter in CHAPTERS:
        values = chapter_entries[chapter["id"]]
        if not values:
            continue
        entry_ids = []
        for source, refinement in values:
            record = entry_record(source, refinement, chapter["id"], index)
            entries.append(record)
            entry_ids.append(record["id"])
            index += 1
        chapters.append({
            "id": chapter["id"],
            "title": chapter["title"],
            "description": chapter["description"],
            "entry_ids": entry_ids,
        })

    authors = Counter(
        value["metadata"].get("author", {}).get("nickname")
        for value in completed.values()
        if value["metadata"].get("author", {}).get("nickname")
    )
    author = authors.most_common(1)[0][0] if authors else "未知作者"
    generated_at = max(value.get("completed_at") or "" for value in refinements.values())
    tags = Counter(tag for value in completed.values() for tag in value["metadata"].get("text", {}).get("hashtags") or [])
    total_corrections = sum(len(value["refinement"]["corrections"]) for value in refinements.values())
    total_uncertainties = sum(len(value["refinement"]["uncertainties"]) for value in refinements.values())
    citations = [
        citation_value
        for entry in entries
        for citation_value in [
            entry["thesis_citation"],
            *[value["citation"] for value in entry["viewpoints"]],
            *[value["citation"] for value in entry["arguments"]],
            *[value["citation"] for value in entry["examples"]],
            *[value["citation"] for value in entry["references"]],
            *[value["citation"] for value in entry["terms"]],
        ]
    ]
    citation_matches = Counter(value["match"] for value in citations)
    payload = {
        "schema_version": 1,
        "title": f"{author}知识全景书",
        "subtitle": "把观点还给原文，把知识连成一本书",
        "author": author,
        "generated_at": generated_at,
        "method": "公开元数据 + 单次本地 ASR + 单次 Codex 校订与知识提取",
        "stats": {
            "input_count": len(sources),
            "entry_count": len(entries),
            "unavailable_count": len(unavailable),
            "audio_hours": round(sum(value.get("audio_duration_s") or 0 for value in completed.values()) / 3600, 2),
            "correction_count": total_corrections,
            "uncertainty_count": total_uncertainties,
            "citation_count": len(citations),
            "citation_matches": dict(citation_matches),
        },
        "frequent_hashtags": [{"name": name, "count": count} for name, count in tags.most_common(30)],
        "chapters": chapters,
        "entries": entries,
        "unavailable": [
            {
                "id": aweme_id,
                "video_url": value.get("url"),
                "reason": (value.get("filter_detail") or {}).get("detail_msg") or (value.get("filter_detail") or {}).get("notice") or "不可访问",
            }
            for aweme_id, value in sorted(unavailable.items())
        ],
        "classification": classification,
    }
    write_json(args.output, payload)
    print(json.dumps({
        "output": str(args.output),
        "entries": len(entries),
        "chapters": len(chapters),
        "paragraphs": sum(len(entry["transcript"]) for entry in entries),
        "citations": sum(
            1 + len(entry["viewpoints"]) + len(entry["arguments"]) + len(entry["examples"]) + len(entry["references"]) + len(entry["terms"])
            for entry in entries
        ),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
