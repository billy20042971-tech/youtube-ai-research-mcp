import json
from pathlib import Path

src = json.loads(Path("data/latest.json").read_text(encoding="utf-8"))
recent = src["recent_72h_sample"]

out = {
    "generated_at": src["generated_at"],
    "fixed_sample": {
        q: {
            "videos": [
                {
                    "video_id": v.get("video_id"),
                    "title": v.get("title"),
                    "channel_title": v.get("channel_title"),
                    "published_at": v.get("published_at"),
                    "views": v.get("views"),
                    "likes": v.get("likes"),
                    "comments_count": v.get("comments"),
                    "url": v.get("url"),
                    "query_rank": v.get("query_rank"),
                }
                for v in d.get("videos", [])
            ]
        }
        for q, d in src["fixed_sample"].get("per_query", {}).items()
    },
    "recent_72h_sample": {
        q: {
            "videos": [
                {
                    "video_id": v.get("video_id"),
                    "title": v.get("title"),
                    "channel_title": v.get("channel_title"),
                    "published_at": v.get("published_at"),
                    "views": v.get("views"),
                    "likes": v.get("likes"),
                    "comments_count": v.get("comments"),
                    "url": v.get("url"),
                    "query_rank": v.get("query_rank"),
                    "comments_obtained_count": v.get("comments_obtained_count"),
                    "comments": [
                        {
                            "text": c.get("text"),
                            "likes": c.get("likes"),
                            "published_at": c.get("published_at"),
                            "reply_count": c.get("reply_count"),
                        }
                        for c in v.get("comments", [])
                    ],
                }
                for v in d.get("videos", [])
            ]
        }
        for q, d in recent.get("per_query", {}).items()
    }
}

Path("data/analysis-input.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2),
    encoding="utf-8"
)
print("analysis-input.json created")
