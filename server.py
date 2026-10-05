import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
SERVER_NAME = "YouTube Research MCP"
DEFAULT_TIMEOUT = 30.0

mcp = MCPServer(SERVER_NAME)


def _api_key() -> str:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not configured. "
            "Set it as an environment variable; never hard-code it."
        )
    return key


async def _youtube_get(
    endpoint: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    params = dict(params)
    params["key"] = _api_key()

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params)

    if response.is_error:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"YouTube Data API error {response.status_code}: {detail}"
        )

    return response.json()


async def _video_details(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not video_ids:
        return {}

    data = await _youtube_get(
        "videos",
        {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
        },
    )

    result: dict[str, dict[str, Any]] = {}
    for item in data.get("items", []):
        result[item["id"]] = {
            "video_id": item["id"],
            "title": item.get("snippet", {}).get("title"),
            "channel_id": item.get("snippet", {}).get("channelId"),
            "channel_title": item.get("snippet", {}).get("channelTitle"),
            "published_at": item.get("snippet", {}).get("publishedAt"),
            "description": item.get("snippet", {}).get("description"),
            "tags": item.get("snippet", {}).get("tags", []),
            "views": int(item.get("statistics", {}).get("viewCount", 0)),
            "likes": int(item.get("statistics", {}).get("likeCount", 0)),
            "comments": int(item.get("statistics", {}).get("commentCount", 0)),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        }

    return result


async def _search_videos(
    query: str,
    max_results: int,
    order: str,
    published_after: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "maxResults": max(1, min(max_results, 50)),
    }
    if published_after:
        params["publishedAfter"] = published_after

    data = await _youtube_get("search", params)

    ids = [
        item["id"]["videoId"]
        for item in data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    details = await _video_details(ids)

    results: list[dict[str, Any]] = []
    for rank, video_id in enumerate(ids, start=1):
        item = details.get(video_id, {"video_id": video_id})
        item["query"] = query
        item["query_rank"] = rank
        results.append(item)

    return results


async def _top_comments(video_id: str, max_results: int) -> dict[str, Any]:
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max(1, min(max_results, 100)),
        "order": "relevance",
        "textFormat": "plainText",
    }

    try:
        data = await _youtube_get("commentThreads", params)
    except RuntimeError as exc:
        # Comments can legitimately be disabled for a video.
        if "commentsDisabled" in str(exc) or "403" in str(exc):
            return {
                "video_id": video_id,
                "obtained_count": 0,
                "comments": [],
                "comments_unavailable": True,
            }
        raise

    comments: list[dict[str, Any]] = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        top = snippet.get("topLevelComment", {})
        top_snippet = top.get("snippet", {})
        comments.append(
            {
                "comment_id": top.get("id"),
                "text": top_snippet.get("textDisplay"),
                "likes": int(top_snippet.get("likeCount", 0)),
                "published_at": top_snippet.get("publishedAt"),
                "updated_at": top_snippet.get("updatedAt"),
                "reply_count": int(snippet.get("totalReplyCount", 0)),
            }
        )

    return {
        "video_id": video_id,
        "obtained_count": len(comments),
        "comments": comments,
        "comments_unavailable": False,
    }


@mcp.tool()
async def youtube_search_videos(
    query: str,
    max_results: int = 20,
    order: str = "viewCount",
    published_after: str | None = None,
) -> dict[str, Any]:
    """Search YouTube videos and return enriched public metadata.

    Use order='viewCount' for the fixed trend-radar sampling rule.
    published_after is an optional RFC3339 timestamp such as
    2026-10-02T06:00:00Z. Views are a sampling signal, not a credibility score.
    """
    if order not in {"viewCount", "date", "relevance"}:
        raise ValueError("order must be viewCount, date, or relevance")

    results = await _search_videos(
        query=query,
        max_results=max_results,
        order=order,
        published_after=published_after,
    )

    return {
        "query": query,
        "order": order,
        "requested_count": max_results,
        "obtained_count": len(results),
        "videos": results,
    }


@mcp.tool()
async def youtube_top_comments(
    video_id: str,
    max_results: int = 20,
) -> dict[str, Any]:
    """Return up to max_results relevant public top-level comments.

    If fewer than requested comments exist, the actual obtained_count is returned.
    No comments are fabricated. User-reported income or success claims remain
    unverified claims until independently checked.
    """
    return await _top_comments(video_id, max_results)


@mcp.tool()
async def youtube_research_sample(
    queries: list[str] | None = None,
    videos_per_query: int = 20,
    comments_per_video: int = 20,
    published_after: str | None = None,
) -> dict[str, Any]:
    """Run the fixed YouTube research sample used by the AI trend radar.

    Default queries are exactly: AI賺錢 and AI副業.
    Each query is sampled separately, sorted by viewCount, then deduplicated
    by video ID only for the combined analysis. For each unique video, up to
    comments_per_video relevant top-level comments are collected.

    Raw fields are preserved: query, query_rank, video metadata, URL, and
    comment text/likes/time/reply count. Missing comments are recorded with
    their actual count.
    """
    if not queries:
        queries = ["AI賺錢", "AI副業"]

    all_videos: list[dict[str, Any]] = []
    per_query: dict[str, Any] = {}

    for query in queries:
        videos = await _search_videos(
            query=query,
            max_results=videos_per_query,
            order="viewCount",
            published_after=published_after,
        )
        per_query[query] = {
            "requested_count": videos_per_query,
            "obtained_count": len(videos),
            "videos": videos,
        }
        all_videos.extend(videos)

    deduped: dict[str, dict[str, Any]] = {}
    for video in all_videos:
        deduped.setdefault(video["video_id"], video)

    sampled_videos: list[dict[str, Any]] = []
    for video in deduped.values():
        comment_data = await _top_comments(
            video["video_id"],
            comments_per_video,
        )
        enriched = dict(video)
        enriched["comments_requested"] = comments_per_video
        enriched["comments_obtained_count"] = comment_data["obtained_count"]
        enriched["comments_unavailable"] = comment_data["comments_unavailable"]
        enriched["comments"] = comment_data["comments"]
        sampled_videos.append(enriched)

    return {
        "server": SERVER_NAME,
        "sampling_rule": {
            "queries": queries,
            "order": "viewCount",
            "videos_per_query": videos_per_query,
            "comments_per_video": comments_per_video,
            "published_after": published_after,
            "dedupe_key": "video_id",
        },
        "per_query": per_query,
        "combined_unique_video_count": len(sampled_videos),
        "videos": sampled_videos,
        "note": (
            "Views are a sampling signal only. High views do not by themselves "
            "prove a new 72-hour trend or the truth of a creator's claims."
        ),
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": SERVER_NAME,
            "mcp_endpoint": "/mcp",
        }
    )


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
