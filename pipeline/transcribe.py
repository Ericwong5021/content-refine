import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import requests
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TTWID_REGISTER_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
DETAIL_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"


class PipelineError(RuntimeError):
    pass


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp_path, path)


def emit(log_path, event, **fields):
    row = {"at": now(), "event": event, **fields}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)


def refresh_ttwid(session):
    response = requests.post(
        TTWID_REGISTER_URL,
        json={
            "region": "cn",
            "aid": 6383,
            "needFid": False,
            "service": "www.douyin.com",
            "migrate_info": {"ticket": "", "source": "node"},
            "cbUrlProtocol": "https",
            "union": True,
        },
        headers={"User-Agent": UA, "Content-Type": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status_code") != 0 or not data.get("redirect_url"):
        raise PipelineError(f"ttwid registration failed: {data}")
    callback_session = requests.Session()
    callback_session.headers.update({"User-Agent": UA})
    callback = callback_session.get(data["redirect_url"], timeout=20)
    callback.raise_for_status()
    ttwid_values = {cookie.value for cookie in callback_session.cookies if cookie.name == "ttwid"}
    if len(ttwid_values) != 1:
        raise PipelineError(f"ttwid callback produced {len(ttwid_values)} unique cookie values")
    ttwid = ttwid_values.pop()
    session.cookies.set("ttwid", ttwid, domain=".douyin.com")
    return ttwid


def build_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.douyin.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    refresh_ttwid(session)
    return session


def fetch_detail(session, aweme_id, log_path):
    last_error = None
    for attempt in range(1, 4):
        try:
            response = session.get(DETAIL_API, params={"aweme_id": aweme_id}, timeout=20)
            if response.status_code == 403:
                refresh_ttwid(session)
                response = session.get(DETAIL_API, params={"aweme_id": aweme_id}, timeout=20)
            response.raise_for_status()
            if "application/json" not in response.headers.get("content-type", ""):
                raise PipelineError(
                    f"detail endpoint returned {response.headers.get('content-type')} with body {response.text[:160]!r}"
                )
            data = response.json()
            if data.get("status_code") != 0:
                raise PipelineError(f"detail endpoint status_code={data.get('status_code')}: {data}")
            detail = data.get("aweme_detail")
            if detail:
                return detail, None, data
            filter_detail = data.get("filter_detail")
            if filter_detail:
                return None, filter_detail, data
            raise PipelineError(f"detail endpoint returned no aweme_detail: keys={sorted(data)}")
        except Exception as error:
            last_error = error
            emit(log_path, "detail_retry", aweme_id=aweme_id, attempt=attempt, error=repr(error))
            try:
                refresh_ttwid(session)
            except Exception as refresh_err:
                emit(log_path, "ttwid_refresh_failed", aweme_id=aweme_id, attempt=attempt, error=repr(refresh_err))
            if attempt < 3:
                time.sleep(attempt * 2)
    raise PipelineError(f"detail fetch failed after 3 attempts for {aweme_id}: {last_error!r}")


def audio_source(detail):
    video_duration_ms = (detail.get("video") or {}).get("duration") or detail.get("duration")
    music = detail.get("music") or {}
    play_url = music.get("play_url") or {}
    urls = [value for value in play_url.get("url_list") or [] if value]
    if not urls and play_url.get("uri"):
        urls = [play_url["uri"]]
    if not video_duration_ms:
        raise PipelineError("video duration is missing")
    if not urls:
        raise PipelineError("original audio URL is missing")
    music_duration_s = music.get("duration")
    if music_duration_s and abs(video_duration_ms / 1000 - music_duration_s) > 1.1:
        raise PipelineError(
            f"video and original audio duration differ: video={video_duration_ms / 1000}, audio={music_duration_s}"
        )
    return urls, video_duration_ms


def download_audio(session, urls, output_path, aweme_id, log_path):
    last_error = None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls[:3]):
        started = time.monotonic()
        digest = hashlib.sha256()
        bytes_written = 0
        temp_path = output_path.with_suffix(f"{output_path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with session.get(url, stream=True, timeout=300) as response:
                response.raise_for_status()
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        bytes_written += len(chunk)
            if bytes_written == 0:
                raise PipelineError("audio download produced an empty file")
            os.replace(temp_path, output_path)
            return {
                "url": url,
                "bytes": bytes_written,
                "sha256": digest.hexdigest(),
                "download_sec": round(time.monotonic() - started, 3),
            }
        except Exception as error:
            temp_path.unlink(missing_ok=True)
            last_error = error
            emit(
                log_path,
                "audio_url_failed",
                aweme_id=aweme_id,
                url_index=index,
                error=repr(error),
            )
    raise PipelineError(f"all original audio URLs failed for {aweme_id}: {last_error!r}")


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def iso_timestamp(value):
    if not value:
        return None
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def selected(value, keys):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in keys if key in value}


def asset(value):
    return selected(value, ["uri", "url_list", "width", "height", "url_key", "data_size", "file_hash"])


def normalize_author(author):
    if not isinstance(author, dict):
        return None
    normalized = selected(
        author,
        [
            "uid",
            "sec_uid",
            "short_id",
            "unique_id",
            "nickname",
            "signature",
            "custom_verify",
            "enterprise_verify_reason",
            "verification_type",
            "account_cert_info",
            "follower_count",
            "following_count",
            "favoriting_count",
            "total_favorited",
            "max_follower_count",
            "user_age",
            "create_time",
            "status",
            "secret",
            "user_canceled",
            "prevent_download",
            "personal_tag_list",
            "data_label_list",
        ],
    )
    normalized["avatar"] = asset(author.get("avatar_thumb"))
    normalized["profile_cover"] = asset(author.get("cover_url"))
    return normalized


def normalize_video(video):
    if not isinstance(video, dict):
        return None
    normalized = selected(
        video,
        [
            "duration",
            "width",
            "height",
            "ratio",
            "format",
            "has_watermark",
            "is_h265",
            "is_long_video",
            "is_source_HDR",
            "cdn_url_expired",
            "bit_rate",
            "bit_rate_audio",
            "meta",
        ],
    )
    normalized["cover"] = asset(video.get("cover"))
    normalized["origin_cover"] = asset(video.get("origin_cover"))
    normalized["dynamic_cover"] = asset(video.get("dynamic_cover"))
    normalized["play_addr"] = asset(video.get("play_addr"))
    normalized["play_addr_h264"] = asset(video.get("play_addr_h264"))
    normalized["play_addr_265"] = asset(video.get("play_addr_265"))
    normalized["download_addr"] = asset(video.get("download_addr"))
    normalized["audio"] = video.get("audio")
    return normalized


def normalize_music(music):
    if not isinstance(music, dict):
        return None
    normalized = selected(
        music,
        [
            "id",
            "id_str",
            "mid",
            "title",
            "author",
            "owner_id",
            "owner_handle",
            "owner_nickname",
            "sec_uid",
            "album",
            "duration",
            "audition_duration",
            "shoot_duration",
            "video_duration",
            "start_time",
            "end_time",
            "is_original",
            "is_original_sound",
            "is_commerce_music",
            "is_restricted",
            "is_pgc",
            "source_platform",
            "music_collect_count",
            "user_count",
            "status",
            "music_status",
            "prevent_download",
            "offline_desc",
            "tag_list",
            "artists",
            "external_song_info",
        ],
    )
    normalized["play_url"] = asset(music.get("play_url"))
    normalized["cover"] = asset(music.get("cover_large") or music.get("cover_medium") or music.get("cover_thumb"))
    return normalized


def normalize_metadata(detail):
    create_time = detail.get("create_time")
    text_extra = detail.get("text_extra") or []
    hashtags = [entry.get("hashtag_name") for entry in text_extra if entry.get("hashtag_name")]
    mentions = [
        selected(entry, ["user_id", "sec_uid", "nickname", "start", "end", "type"])
        for entry in text_extra
        if entry.get("type") != 1 and any(entry.get(key) for key in ["user_id", "sec_uid", "nickname"])
    ]
    video_tags = [selected(entry, ["tag_id", "tag_name", "level"]) for entry in detail.get("video_tag") or []]
    collection = detail.get("mix_info")
    collection_summary = None
    if isinstance(collection, dict):
        collection_summary = selected(
            collection,
            ["mix_id", "mix_name", "desc", "create_time", "update_time", "mix_type", "mix_pic_type", "is_serial_mix", "statis", "status"],
        )
        collection_summary["cover"] = asset(collection.get("cover_url"))
        collection_summary["share_info"] = collection.get("share_info")
    return {
        "identity": selected(
            detail,
            ["aweme_id", "group_id", "sec_item_id", "comment_gid", "author_user_id", "aweme_type", "media_type", "activity_video_type"],
        ),
        "publication": {
            "create_time": create_time,
            "published_at": iso_timestamp(create_time),
            "region": detail.get("region"),
            "is_top": detail.get("is_top"),
            "is_story": detail.get("is_story"),
            "is_24_story": detail.get("is_24_story"),
            "is_25_story": detail.get("is_25_story"),
        },
        "text": {
            "description": detail.get("desc"),
            "item_title": detail.get("item_title"),
            "preview_title": detail.get("preview_title"),
            "caption": detail.get("caption"),
            "video_text": detail.get("video_text"),
            "share_info": detail.get("share_info"),
            "share_url": detail.get("share_url"),
            "hashtags": hashtags,
            "mentions": mentions,
            "text_extra": text_extra,
        },
        "engagement": detail.get("statistics"),
        "author": normalize_author(detail.get("author")),
        "video": normalize_video(detail.get("video")),
        "music": normalize_music(detail.get("music")),
        "taxonomy": {
            "video_tags": video_tags,
            "aweme_type_tags": detail.get("aweme_type_tags"),
            "social_tags": detail.get("social_tag_list"),
            "video_labels": detail.get("video_labels"),
            "cover_labels": detail.get("cover_labels"),
            "hybrid_label": detail.get("hybrid_label"),
        },
        "collection": collection_summary,
        "series": {
            "basic": detail.get("series_basic_info"),
            "paid": detail.get("series_paid_info"),
            "long_video": detail.get("long_video"),
            "chapters": detail.get("chapter_list"),
        },
        "relations": {
            "anchors": detail.get("anchors"),
            "interaction_stickers": detail.get("interaction_stickers"),
            "follow_shoot_clip_info": detail.get("follow_shoot_clip_info"),
            "follow_shoot_property": detail.get("follow_shoot_property"),
            "origin_comment_ids": detail.get("origin_comment_ids"),
            "origin_duet_resource_uri": detail.get("origin_duet_resource_uri"),
            "is_share_post": detail.get("is_share_post"),
            "is_duet_sing": detail.get("is_duet_sing"),
        },
        "commerce": {
            "is_ads": detail.get("is_ads"),
            "is_from_ad_auth": detail.get("is_from_ad_auth"),
            "is_life_item": detail.get("is_life_item"),
            "promotions": detail.get("promotions"),
            "commerce_config_data": detail.get("commerce_config_data"),
            "entertainment_product_info": detail.get("entertainment_product_info"),
            "product_genre_info": detail.get("product_genre_info"),
        },
        "content_flags": selected(
            detail,
            [
                "original",
                "is_aigc_media",
                "item_aigc_follow_shot",
                "is_subtitled",
                "is_use_music",
                "is_image_beat",
                "is_new_text_mode",
                "can_cache_to_local",
                "can_be_oc_cover",
                "shoot_way",
                "rate",
            ],
        ),
        "availability": {
            "status": detail.get("status"),
            "risk_infos": detail.get("risk_infos"),
            "video_control": detail.get("video_control"),
            "aweme_control": detail.get("aweme_control"),
            "comment_permission_info": detail.get("comment_permission_info"),
            "can_cache_to_local": detail.get("can_cache_to_local"),
        },
        "location": {
            "region": detail.get("region"),
            "geofencing": detail.get("geofencing"),
            "geofencing_regions": detail.get("geofencing_regions"),
        },
    }


def probe_duration(path):
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise PipelineError(f"ffprobe failed: {process.stderr[-500:]}")
    try:
        return float(process.stdout.strip())
    except ValueError as error:
        raise PipelineError(f"ffprobe returned invalid duration: {process.stdout!r}") from error


def load_items(path):
    items = []
    seen_aweme_ids = set()
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise PipelineError(f"invalid JSON on line {line_number}: {error}") from error
        if not item.get("aweme_id") or not item.get("url"):
            raise PipelineError(f"line {line_number} is missing aweme_id or url")
        aweme_id = str(item["aweme_id"])
        if aweme_id in seen_aweme_ids:
            raise PipelineError(f"duplicate aweme_id on line {line_number}: {aweme_id}")
        seen_aweme_ids.add(aweme_id)
        item["aweme_id"] = aweme_id
        items.append(item)
    if not items:
        raise PipelineError("input manifest is empty")
    return items


def load_completed(path):
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if value.get("status") not in {"COMPLETED", "UNAVAILABLE"}:
        raise PipelineError(f"existing result has invalid status: {path}")
    return value


def is_current_result(value, output):
    if value.get("pipeline_schema_version") != 2:
        return False
    raw_path = value.get("source_response_path")
    if not raw_path or not (output / raw_path).exists():
        return False
    if value.get("status") == "UNAVAILABLE":
        return True
    audio_path = value.get("audio_source", {}).get("local_path")
    return bool(audio_path and (output / audio_path).exists() and value.get("metadata"))


def transcribe(model, audio_path):
    started = time.monotonic()
    response = model.generate(
        input=str(audio_path),
        cache={},
        language="zh",
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
    )
    elapsed = time.monotonic() - started
    if not response or not response[0].get("text"):
        raise PipelineError(f"SenseVoice returned no text: {response!r}")
    text = rich_transcription_postprocess(response[0]["text"]).strip()
    if not text:
        raise PipelineError("SenseVoice text is empty after postprocessing")
    return text, elapsed


def build_index(results_dir, index_path, items):
    rows = []
    for item in items:
        path = results_dir / f"{item['aweme_id']}.json"
        if not path.exists():
            continue
        value = json.loads(path.read_text())
        rows.append(value)
    temp_path = index_path.with_suffix(f"{index_path.suffix}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temp_path, index_path)
    return rows


def json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise PipelineError(f"unsupported JSON value type: {type(value).__name__}")


def is_non_empty(value):
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def document_field_inventory(value):
    fields = {}

    def walk(current, path):
        if path:
            entry = fields.setdefault(path, {"types": set(), "non_null": False, "non_empty": False})
            entry["types"].add(json_type(current))
            entry["non_null"] = entry["non_null"] or current is not None
            entry["non_empty"] = entry["non_empty"] or is_non_empty(current)
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(current, list):
            for child in current:
                walk(child, f"{path}[]")

    walk(value, "")
    return fields


def build_field_inventory(raw_dir, output_path):
    paths = sorted(raw_dir.glob("*.json"))
    if not paths:
        raise PipelineError(f"raw response directory has no JSON files: {raw_dir}")
    combined = {}
    for path in paths:
        value = json.loads(path.read_text())
        for field_path, field in document_field_inventory(value).items():
            entry = combined.setdefault(
                field_path,
                {"present_documents": 0, "non_null_documents": 0, "non_empty_documents": 0, "types": set()},
            )
            entry["present_documents"] += 1
            entry["non_null_documents"] += int(field["non_null"])
            entry["non_empty_documents"] += int(field["non_empty"])
            entry["types"].update(field["types"])
    inventory = {
        "schema_version": 1,
        "generated_at": now(),
        "document_count": len(paths),
        "field_count": len(combined),
        "fields": [
            {
                "path": field_path,
                "present_documents": combined[field_path]["present_documents"],
                "non_null_documents": combined[field_path]["non_null_documents"],
                "non_empty_documents": combined[field_path]["non_empty_documents"],
                "types": sorted(combined[field_path]["types"]),
            }
            for field_path in sorted(combined)
        ],
    }
    write_json(output_path, inventory)
    return inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("items", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    items = load_items(args.items)
    if args.limit is not None:
        if args.limit < 1:
            raise PipelineError("--limit must be at least 1")
        items = items[: args.limit]

    run_id = uuid.uuid4().hex
    results_dir = args.output / "results"
    raw_dir = args.output / "raw"
    audio_dir = args.output / "audio"
    results_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "events.jsonl"
    index_path = args.output / "index.jsonl"
    emit(log_path, "run_started", run_id=run_id, item_count=len(items), device=args.device)

    session = build_session()
    emit(log_path, "anonymous_session_ready", run_id=run_id)

    pending = []
    for item in items:
        result_path = results_dir / f"{item['aweme_id']}.json"
        existing = load_completed(result_path)
        if not args.force and existing and is_current_result(existing, args.output):
            emit(log_path, "item_skipped", run_id=run_id, aweme_id=item["aweme_id"])
            continue
        pending.append((item, result_path, existing))

    model = None
    completed = 0
    unavailable = 0
    for position, (item, result_path, existing) in enumerate(pending, 1):
        aweme_id = item["aweme_id"]
        emit(
            log_path,
            "item_started",
            run_id=run_id,
            aweme_id=aweme_id,
            position=position,
            pending_count=len(pending),
        )
        detail, filter_detail, source_response = fetch_detail(session, aweme_id, log_path)
        raw_path = raw_dir / f"{aweme_id}.json"
        write_json(raw_path, source_response)
        raw_relative_path = str(raw_path.relative_to(args.output))
        if filter_detail:
            if existing and existing.get("status") == "COMPLETED":
                raise PipelineError(f"previously completed item is now unavailable: {aweme_id}: {filter_detail}")
            result = {
                "pipeline_schema_version": 2,
                "aweme_id": aweme_id,
                "url": item["url"],
                "title": item.get("title"),
                "status": "UNAVAILABLE",
                "filter_detail": filter_detail,
                "source_response_path": raw_relative_path,
                "completed_at": now(),
            }
            write_json(result_path, result)
            unavailable += 1
            emit(log_path, "item_unavailable", run_id=run_id, aweme_id=aweme_id, filter_detail=filter_detail)
            continue

        urls, video_duration_ms = audio_source(detail)
        audio_path = audio_dir / f"{aweme_id}.mp3"
        if audio_path.exists():
            file_info = hash_file(audio_path)
            download = {
                "url": urls[0],
                **file_info,
                "download_sec": 0,
                "reused": True,
            }
            emit(log_path, "audio_reused", run_id=run_id, aweme_id=aweme_id, **file_info)
        else:
            download = download_audio(session, urls, audio_path, aweme_id, log_path)
            download["reused"] = False
        audio_duration_s = probe_duration(audio_path)
        if abs(audio_duration_s - video_duration_ms / 1000) > 1.1:
            raise PipelineError(
                f"downloaded audio duration mismatch for {aweme_id}: video={video_duration_ms / 1000}, audio={audio_duration_s}"
            )

        reusable_transcription = None
        if existing and existing.get("status") == "COMPLETED":
            reusable_transcription = existing.get("transcription")
            if not reusable_transcription or not reusable_transcription.get("text"):
                raise PipelineError(f"existing completed result has no reusable transcription: {result_path}")
            emit(log_path, "asr_reused", run_id=run_id, aweme_id=aweme_id, chars=len(reusable_transcription["text"]))
        if reusable_transcription:
            transcription = reusable_transcription
            asr_sec = 0
            text = reusable_transcription["text"]
        else:
            if model is None:
                load_started = time.monotonic()
                model = AutoModel(
                    model="iic/SenseVoiceSmall",
                    vad_model="fsmn-vad",
                    vad_kwargs={"max_single_segment_time": 30000},
                    device=args.device,
                    disable_update=True,
                    disable_pbar=True,
                    log_level="ERROR",
                )
                emit(log_path, "model_ready", run_id=run_id, load_sec=round(time.monotonic() - load_started, 3))
            text, asr_sec = transcribe(model, audio_path)
            transcription = {
                "engine": "FunASR",
                "engine_version": version("funasr"),
                "model": "iic/SenseVoiceSmall",
                "device": args.device,
                "language": "zh",
                "asr_sec": round(asr_sec, 3),
                "text": text,
            }

        result = {
            "pipeline_schema_version": 2,
            "aweme_id": aweme_id,
            "url": item["url"],
            "title": item.get("title"),
            "status": "COMPLETED",
            "author": (detail.get("author") or {}).get("nickname"),
            "description": detail.get("desc"),
            "caption": detail.get("caption"),
            "is_subtitled": detail.get("is_subtitled"),
            "video_duration_ms": video_duration_ms,
            "audio_duration_s": round(audio_duration_s, 3),
            "audio_source": download,
            "metadata": normalize_metadata(detail),
            "source_response_path": raw_relative_path,
            "transcription": transcription,
            "completed_at": now(),
        }
        result["audio_source"]["local_path"] = str(audio_path.relative_to(args.output))
        write_json(result_path, result)
        completed += 1
        emit(
            log_path,
            "item_completed",
            run_id=run_id,
            aweme_id=aweme_id,
            chars=len(text),
            audio_bytes=download["bytes"],
            download_sec=download["download_sec"],
            asr_sec=round(asr_sec, 3),
        )

    rows = build_index(results_dir, index_path, items)
    field_inventory = build_field_inventory(raw_dir, args.output / "field-inventory.json")
    totals = {
        "run_id": run_id,
        "status": "COMPLETED",
        "input_count": len(items),
        "newly_completed": completed,
        "newly_unavailable": unavailable,
        "result_count": len(rows),
        "completed_count": sum(row.get("status") == "COMPLETED" for row in rows),
        "unavailable_count": sum(row.get("status") == "UNAVAILABLE" for row in rows),
        "raw_field_count": field_inventory["field_count"],
        "finished_at": now(),
    }
    write_json(args.output / "summary.json", totals)
    emit(log_path, "run_completed", **totals)


if __name__ == "__main__":
    main()
