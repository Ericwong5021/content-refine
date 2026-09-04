import argparse
import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path


class BookError(RuntimeError):
    pass


CHAPTERS = [
    {
        "id": "self",
        "title": "第一部 自我、心理与行动",
        "description": "身份、成长型思维、自尊、执行力、比较、人生选择与行为改变。",
        "keywords": ["心理", "成长", "自尊", "执行力", "自己", "身份", "底层", "天赋", "成功", "行为改变", "任务", "比较"],
    },
    {
        "id": "wealth",
        "title": "第二部 财富、阶层与生产资料",
        "description": "时间、金钱、资产、投资、阶层、现金流与个人生产资料。",
        "keywords": ["生产资料", "资产", "投资", "消费", "财富", "阶层", "时间和金钱", "LTV", "CAC", "租", "买", "现金流"],
    },
    {
        "id": "entrepreneurship",
        "title": "第三部 创业、商机与创造",
        "description": "从需求和市场反馈发现机会，以验证、创造和差异化推进创业。",
        "keywords": ["创业", "商机", "垄断", "从零到一", "需求", "痛点", "预售", "市场反馈", "创造", "失败"],
    },
    {
        "id": "sales",
        "title": "第四部 销售与商业模型",
        "description": "销售心态、漏斗、关单、To B、To C、变现与商业闭环。",
        "keywords": ["销售", "关单", "To B", "To C", "卖", "变现", "漏斗", "成交", "商业模式", "客户", "蜜雪冰城"],
    },
    {
        "id": "brand",
        "title": "第五部 品牌、定价与出海",
        "description": "品牌哲学、定价权、复购、护城河、目标人群、品牌出海与平台关系。",
        "keywords": ["品牌", "定价", "复购", "护城河", "ICP", "出海", "亚马逊", "Temu", "宜家", "泡泡玛特", "工厂", "外贸", "IP"],
    },
    {
        "id": "marketing",
        "title": "第六部 市场、传播与自媒体",
        "description": "市场转化、内容平台、账号起盘、选题、传播表达与注意力。",
        "keywords": ["自媒体", "市场", "营销", "传播", "表达", "起号", "选题", "内容", "账号", "投放", "转化", "粉丝", "触达"],
    },
    {
        "id": "management",
        "title": "第七部 组织管理与职场",
        "description": "大公司方法、会议、SOP、效率、决策、领导力、人才培养与职场学习。",
        "keywords": ["大公司", "小公司", "职场", "领导", "会议", "SOP", "效率", "KPI", "组织", "打工", "决策", "贵人", "员工"],
    },
    {
        "id": "language",
        "title": "第八部 语言、逻辑与认知",
        "description": "语言、命名、标签、暗示、相关与因果、阅读、论证和多因素思维。",
        "keywords": ["语言", "逻辑", "论证", "暗示", "因果", "因素", "相关", "阅读", "标签", "话语权", "命名", "交流"],
    },
    {
        "id": "philosophy",
        "title": "第九部 道德经与人生哲学",
        "description": "道、德、无名、反、自然道、关系、生命、宗教与向内求。",
        "keywords": ["道德经", "自然道", "国家道", "道法", "奥义书", "哲学", "上帝", "人生", "生命", "关系", "妈妈", "造物主", "道", "德", "反", "无名"],
    },
    {
        "id": "other",
        "title": "附编 其他主题",
        "description": "未被当前主题词可靠覆盖的内容，保留原始知识结构和完整校订文字稿。",
        "keywords": [],
    },
]


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(value)
    os.replace(temp_path, path)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json_files(directory):
    if not directory.is_dir():
        raise BookError(f"directory does not exist: {directory}")
    values = {}
    for path in sorted(directory.glob("*.json")):
        value = json.loads(path.read_text())
        aweme_id = value.get("aweme_id")
        if not aweme_id:
            raise BookError(f"file has no aweme_id: {path}")
        if aweme_id in values:
            raise BookError(f"duplicate aweme_id: {aweme_id}")
        values[aweme_id] = value
    return values


def classify(source, refinement):
    metadata = source["metadata"]
    knowledge = refinement["refinement"]["knowledge"]
    text = metadata["text"]
    title = text.get("item_title") or text.get("description") or ""
    title_context = " ".join(
        value
        for value in [text.get("item_title"), text.get("description"), " ".join(text.get("hashtags") or []), " ".join(knowledge.get("book_topics") or [])]
        if value
    ).lower()
    body_context = " ".join(
        value
        for value in [knowledge.get("thesis"), " ".join(knowledge.get("viewpoints") or []), " ".join(item.get("term", "") for item in knowledge.get("terms") or [])]
        if value
    ).lower()
    scores = {}
    for chapter in CHAPTERS:
        score = 0
        for keyword in chapter["keywords"]:
            normalized = keyword.lower()
            if normalized in title_context:
                score += 4
            if normalized in body_context:
                score += 1
        scores[chapter["id"]] = score
    highest_score = max(scores.values())
    if highest_score == 0:
        return "other", scores
    best = max(
        (chapter for chapter in CHAPTERS if chapter["id"] != "other"),
        key=lambda chapter: (scores[chapter["id"]], -CHAPTERS.index(chapter)),
    )
    return best["id"], scores


def bullets(values):
    if not values:
        return "- 本视频未单独提取。\n"
    return "".join(f"- {value}\n" for value in values)


def numbered(values):
    if not values:
        return "1. 本视频未单独提取。\n"
    return "".join(f"{index}. {value}\n" for index, value in enumerate(values, 1))


def render_entry(index, source, refinement, base_dir):
    metadata = source["metadata"]
    text = metadata["text"]
    engagement = metadata.get("engagement") or {}
    publication = metadata.get("publication") or {}
    result = refinement["refinement"]
    knowledge = result["knowledge"]
    title = text.get("item_title") or text.get("description") or source.get("title") or source["aweme_id"]
    source_path = Path(os.path.relpath(source["_path"], base_dir))
    refinement_path = Path(os.path.relpath(refinement["_path"], base_dir))
    lines = [
        f"## {index}. {title}\n",
        f"> 发布时间：{publication.get('published_at') or '未知'}  ",
        f"> 点赞：{engagement.get('digg_count', '未知')} · 收藏：{engagement.get('collect_count', '未知')} · 评论：{engagement.get('comment_count', '未知')} · 分享：{engagement.get('share_count', '未知')}  ",
        f"> [原视频]({source.get('url')}) · [ASR与元数据]({source_path.as_posix()}) · [Codex校订证据]({refinement_path.as_posix()})\n",
        "### 核心命题\n",
        f"{knowledge['thesis']}\n",
        "### 作者观点\n",
        numbered(knowledge["viewpoints"]),
        "### 论证路径\n",
    ]
    if knowledge["arguments"]:
        for argument in knowledge["arguments"]:
            lines.append(f"- **{argument['claim']}**：{argument['support']}（来源：{argument['source']}）\n")
    else:
        lines.append("- 本视频未单独提取。\n")
    lines.extend(["### 案例\n", bullets(knowledge["examples"]), "### 提及与引用\n", bullets(knowledge["references"]), "### 关键术语\n"])
    if knowledge["terms"]:
        for term in knowledge["terms"]:
            lines.append(f"- **{term['term']}**：{term['contextual_meaning']}\n")
    else:
        lines.append("- 本视频未单独提取。\n")
    lines.extend(
        [
            "### 可进入全书的主题\n",
            bullets(knowledge["book_topics"]),
            f"### 校订状态\n- 实质修正：{len(result['corrections'])} 处\n- 存疑片段：{len(result['uncertainties'])} 处\n",
            "<details>\n<summary>展开完整校订文字稿</summary>\n\n",
            result["corrected_transcript"].strip(),
            "\n\n</details>\n\n",
        ]
    )
    return "\n".join(lines), {
        "aweme_id": source["aweme_id"],
        "title": title,
        "published_at": publication.get("published_at"),
        "url": source.get("url"),
        "source_path": source_path.as_posix(),
        "refinement_path": refinement_path.as_posix(),
        "source_asr_sha256": refinement.get("source_asr_sha256"),
        "prompt_sha256": refinement.get("prompt_sha256"),
        "correction_count": len(result["corrections"]),
        "uncertainty_count": len(result["uncertainties"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("refined", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title")
    args = parser.parse_args()

    source_values = load_json_files(args.source / "results")
    refined_values = load_json_files(args.refined / "results")
    completed_sources = {aweme_id: value for aweme_id, value in source_values.items() if value.get("status") == "COMPLETED"}
    unavailable_sources = [value for value in source_values.values() if value.get("status") == "UNAVAILABLE"]
    if set(completed_sources) != set(refined_values):
        missing = sorted(set(completed_sources) - set(refined_values))
        extra = sorted(set(refined_values) - set(completed_sources))
        raise BookError(f"source/refinement mismatch: missing={missing}, extra={extra}")

    base_dir = args.output.parent.resolve()
    for path, value in [(path, source_values[path.stem]) for path in (args.source / "results").glob("*.json")]:
        value["_path"] = str(path.resolve())
    for path, value in [(path, refined_values[path.stem]) for path in (args.refined / "results").glob("*.json")]:
        value["_path"] = str(path.resolve())

    chapter_rows = {chapter["id"]: [] for chapter in CHAPTERS}
    classification = {}
    for aweme_id, source in completed_sources.items():
        chapter_id, scores = classify(source, refined_values[aweme_id])
        chapter_rows[chapter_id].append((source, refined_values[aweme_id]))
        classification[aweme_id] = {"chapter_id": chapter_id, "scores": scores}
    for values in chapter_rows.values():
        values.sort(key=lambda pair: pair[0]["metadata"]["publication"].get("create_time") or 0)

    total_audio_hours = sum(value.get("audio_duration_s", 0) for value in completed_sources.values()) / 3600
    total_corrections = sum(len(value["refinement"]["corrections"]) for value in refined_values.values())
    total_uncertainties = sum(len(value["refinement"]["uncertainties"]) for value in refined_values.values())
    tags = Counter(
        tag
        for value in completed_sources.values()
        for tag in (value["metadata"]["text"].get("hashtags") or [])
    )
    author_names = Counter(
        value["metadata"].get("author", {}).get("nickname")
        for value in completed_sources.values()
        if value["metadata"].get("author", {}).get("nickname")
    )
    author_name = author_names.most_common(1)[0][0] if author_names else None
    book_title = args.title or (f"{author_name}知识全景书" if author_name else args.output.stem)
    active_chapters = [chapter for chapter in CHAPTERS if chapter_rows[chapter["id"]]]
    lines = [
        f"# {book_title}\n",
        "> 基于该账号当前可访问的全部公开视频，采用“公开元数据 + 单次本地 ASR + 单次 Codex 校订与知识提取”整理。\n",
        "## 阅读说明\n",
        f"- 主页条目：{len(source_values)} 个；成功处理：{len(completed_sources)} 个；不可访问：{len(unavailable_sources)} 个。\n",
        f"- 音频总时长：{total_audio_hours:.2f} 小时；实质性校订：{total_corrections} 处；仍存疑：{total_uncertainties} 处。\n",
        "- 本书忠实整理作者在视频中的观点，不代表这些观点已经经过事实核查，也不代表整理者赞同。\n",
        "- 每节先给知识结构，再提供完整校订文字稿；原始 ASR、元数据和 Codex 证据均可追溯。\n",
        "- 抖音网页详情接口对播放量及部分作者统计返回 0，这些 0 不应解释为真实数据。\n",
        "## 全书结构\n",
    ]
    for chapter in active_chapters:
        lines.append(f"- {chapter['title']}：{len(chapter_rows[chapter['id']])} 个视频。{chapter['description']}\n")
    lines.extend(["## 高频话题\n", bullets([f"#{name}（{count} 条）" for name, count in tags.most_common(30)]), "\n"])

    sources = []
    entry_index = 1
    for chapter in active_chapters:
        lines.extend([f"# {chapter['title']}\n", f"{chapter['description']}\n"])
        for source, refinement in chapter_rows[chapter["id"]]:
            rendered, source_record = render_entry(entry_index, source, refinement, base_dir)
            lines.append(rendered)
            source_record["chapter_id"] = chapter["id"]
            sources.append(source_record)
            entry_index += 1

    lines.extend(["# 附录一：不可访问作品\n"])
    for value in sorted(unavailable_sources, key=lambda item: item["aweme_id"]):
        detail = value.get("filter_detail") or {}
        lines.append(f"- `{value['aweme_id']}`：[原视频]({value.get('url')})；接口状态：{detail.get('detail_msg') or detail.get('notice') or '不可访问'}。\n")
    lines.extend(
        [
            "# 附录二：接口信息范围\n",
            "- 身份与类型：作品 ID、分组 ID、安全 ID、作者 ID、作品类型、媒体类型。\n",
            "- 发布信息：发布时间、地区、置顶/故事状态。\n",
            "- 文本信息：介绍文案、标题、预览标题、caption、话题、提及账号、分享文案与链接。\n",
            "- 互动数据：点赞、收藏、评论、分享、赞赏和接口返回的播放量。\n",
            "- 作者信息：昵称、抖音号、简介、认证、头像、关注/获赞等接口统计。\n",
            "- 视频与音频：时长、尺寸、比例、编码、码率、HDR/H.265、封面、播放/下载地址、原声资料。\n",
            "- 分类关系：平台分类标签、合集、集数、系列、章节、锚点、合拍/转发关系。\n",
            "- 商业信息：广告标记、商品卡、商品名称、价格、销量及商品类型。\n",
            "- 权限与状态：分享、下载、合拍、录制、审核、私密、删除、风险提示和可见性。\n",
            "- 内容标记：原创、AIGC、字幕、图文/故事、音乐使用和缓存标记。\n",
            "- 原始详情响应完整保存在每条 `source_response_path` 指向的 JSON 中；签名 URL 和内部技术字段不进入 LLM。\n",
        ]
    )

    book = "\n".join(lines).rstrip() + "\n"
    write_text(args.output, book)
    source_map_path = args.output.with_suffix(".sources.json")
    write_json(
        source_map_path,
        {
            "schema_version": 1,
            "generated_at": now(),
            "book_path": str(args.output),
            "book_title": book_title,
            "book_sha256": hashlib.sha256(book.encode()).hexdigest(),
            "source_count": len(sources),
            "unavailable_count": len(unavailable_sources),
            "chapter_counts": {chapter["id"]: len(chapter_rows[chapter["id"]]) for chapter in CHAPTERS},
            "classification": classification,
            "sources": sources,
        },
    )
    print(
        json.dumps(
            {
                "book": str(args.output),
                "source_map": str(source_map_path),
                "source_count": len(sources),
                "unavailable_count": len(unavailable_sources),
                "chars": len(book),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
