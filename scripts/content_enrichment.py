"""Free, bounded enrichment helpers for YouTube report content.

Uses public caption tracks and Google's unauthenticated translate web endpoint.
Both integrations are best-effort, time-bounded, cached, and never fabricate source facts.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_TRANSLATION_CACHE: dict[str, str] = {}
_TRANSCRIPT_CACHE: dict[str, str] = {}
_TIMEOUT = 8


def _get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DailyAIResearch/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return response.read()


def translate_to_traditional_chinese(text: str) -> str:
    """Translate foreign-language text into Taiwan Traditional Chinese; return empty on failure."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    if value in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[value]
    chunks = [value[i:i + 3500] for i in range(0, len(value), 3500)]
    translated = []
    try:
        for chunk in chunks:
            query = urllib.parse.urlencode({
                "client": "gtx", "sl": "auto", "tl": "zh-TW", "dt": "t", "q": chunk,
            })
            url = "https://translate.googleapis.com/translate_a/single?" + query
            last_error = None
            for attempt in range(2):
                try:
                    payload = json.loads(_get(url))
                    translated.append("".join(part[0] for part in payload[0] if part and part[0]))
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
        result = " ".join(translated).strip()
        _TRANSLATION_CACHE[value] = result
        return result
    except Exception:
        return ""


def _video_caption_text(video_id: str) -> str:
    """Read a public caption track from the watch page without consuming YouTube Data API quota."""
    if video_id in _TRANSCRIPT_CACHE:
        return _TRANSCRIPT_CACHE[video_id]
    try:
        page = _get("https://www.youtube.com/watch?" + urllib.parse.urlencode({"v": video_id})).decode("utf-8", "replace")
        match = re.search(r'"captionTracks":(\[.*?\])', page)
        if not match:
            return ""
        tracks = json.loads(match.group(1))
        if not tracks:
            return ""
        track = next((item for item in tracks if str(item.get("languageCode", "")).startswith(("zh", "en", "ja"))), tracks[0])
        base_url = track.get("baseUrl")
        if not base_url:
            return ""
        xml = ET.fromstring(_get(base_url))
        segments = [node.text or "" for node in xml.iter() if node.tag.endswith("text")]
        transcript = re.sub(r"\s+", " ", " ".join(segments)).strip()
        _TRANSCRIPT_CACHE[video_id] = transcript[:16000]
        return _TRANSCRIPT_CACHE[video_id]
    except Exception:
        return ""


def extract_chapters(description: str) -> list[str]:
    """Extract timestamped chapter labels from a YouTube description."""
    lines = str(description or "").splitlines()
    found = []
    for line in lines:
        value = re.sub(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\s*[-–|:：]?\s*", "", line).strip()
        if value != line.strip() and value:
            found.append(value)
    return found[:30]


def enrich_video_content(video: dict, fetch_transcript: bool = True) -> dict:
    """Return a copy enriched from existing transcript/chapter fields or public captions."""
    result = dict(video)
    description = str(result.get("description") or "")
    transcript = (
        result.get("transcript_zh") or result.get("transcript") or
        result.get("transcript_text") or result.get("captions_text") or ""
    )
    if not transcript and fetch_transcript and len(description.strip()) < 280:
        video_id = str(result.get("video_id") or "").strip()
        if video_id:
            transcript = _video_caption_text(video_id)
    if transcript:
        result["transcript_source_text"] = str(transcript)[:16000]
        result["transcript_zh"] = translate_to_traditional_chinese(str(transcript)[:12000]) or str(transcript)
    chapters = result.get("chapters") or extract_chapters(description)
    if chapters:
        result["chapters"] = chapters
        result["chapters_zh"] = [
            translate_to_traditional_chinese(str(item)) or str(item)
            for item in chapters[:30]
        ]
    source = result.get("description_zh") or result.get("translated_description") or result.get("description") or ""
    if not result.get("description_zh") and source:
        result["description_zh"] = translate_to_traditional_chinese(str(source)) or ""
    if not result.get("title_zh") and result.get("title"):
        result["title_zh"] = translate_to_traditional_chinese(str(result["title"])) or ""
    return result
