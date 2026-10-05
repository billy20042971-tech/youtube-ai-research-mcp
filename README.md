# YouTube Research MCP

MCP server for structured YouTube trend research using the YouTube Data API v3.

## Purpose

This server is the raw-data layer for the AI Lab YouTube research radar.

It exposes three MCP tools:

- `youtube_search_videos`
- `youtube_top_comments`
- `youtube_research_sample`

The fixed research sample defaults to:

1. Search `AI賺錢`, ordered by `viewCount`, top 20.
2. Search `AI副業`, ordered by `viewCount`, top 20.
3. Deduplicate by video ID for the combined analysis.
4. Collect up to 20 relevant public top-level comments per unique video.
5. Record the actual number obtained; never fabricate missing comments.

## Important research rules

- View count is a sampling signal, not a credibility score.
- High views do not automatically mean a new 72-hour trend.
- Creator claims about income or success are unverified claims until independently checked.
- Missing comments are recorded with their actual count.
- General web search must not be presented as a fixed YouTube API sample.

## Security

The YouTube API key is read only from the environment variable:

`YOUTUBE_API_KEY`

Never put the API key in:

- this repository
- source code
- README
- chat messages
- Notion
- GitHub Issues
- client-side code

For cloud deployment, configure `YOUTUBE_API_KEY` as a secret/environment variable.

## Local run

Python 3.10+ is required.

Install:

```bash
pip install -r requirements.txt
```

Set the API key:

```bash
export YOUTUBE_API_KEY="YOUR_KEY"
```

Run:

```bash
python server.py
```

MCP endpoint:

```
http://localhost:8000/mcp
```

Health check:

```
http://localhost:8000/health
```

The project uses the official MCP Python SDK v2 and Streamable HTTP for deployment.

## Next deployment step

Deploy this repository to a cloud host that provides a public HTTPS endpoint, then configure:

- `YOUTUBE_API_KEY` as a secret
- the service port through the platform's `PORT` variable
- the resulting HTTPS `/mcp` endpoint as the remote MCP URL

Do not claim the MCP is connected to ChatGPT until the deployed endpoint has been tested and its tools have been discovered successfully.
