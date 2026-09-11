"""Everything YouTube-specific: recognizing a video URL, pulling video
metadata straight out of the page's own embedded JSON (free, no API key),
fetching comments and running keyword search via the official YouTube Data
API v3 (needs an API key), and the item pipeline that wires it all together.

Video metadata extraction deliberately does NOT use the YouTube Data API -
the page's ytInitialPlayerResponse JSON already has it for free, with no
quota cost and no API key requirement. The API is only used for the two
things the page HTML can't provide: comments and keyword search.

API key setup: set the YOUTUBE_API_KEY environment variable (the setting
YOUTUBE_API_KEY_ENV in settings.py names which env var to read, following the
same "config only ever references an env var NAME, never the secret itself"
convention as auth.py). Comments and keyword search are both skipped (with a
logged warning), not fatal, when no key is configured - a crawl with YouTube
seeds but no key behaves like one before this feature existed, just without
comments/search.
"""

import json
import os
from urllib.parse import urlparse, parse_qs

import requests
from itemadapter import ItemAdapter

YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# candidate ways YouTube's server-rendered HTML assigns the player-state JSON
# blob to a variable - tried in order since the exact form has changed over
# time and can differ between the plain and consent/embed page variants
YT_PLAYER_RESPONSE_MARKERS = (
    "var ytInitialPlayerResponse = ",
    "ytInitialPlayerResponse = ",
    'window["ytInitialPlayerResponse"] = ',
)


class YoutubeApiError(Exception):
    def __init__(self, reason, message):
        self.reason = reason
        super().__init__(message)


class CommentsDisabled(YoutubeApiError):
    pass


def is_youtube_domain(url):
    """True for any youtube.com/youtu.be URL, not just a specific video -
    used to detect "this crawl has a YouTube seed" for the keyword-search
    trigger, as opposed to is_youtube_video_url which requires an actual
    video id."""
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def extract_video_id(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.lstrip("/").split("/")[0] or None
    if "youtube.com" in host and parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v")
        return values[0] if values else None
    return None


def is_youtube_video_url(url):
    return extract_video_id(url) is not None


def _extract_json_object(html, markers):
    """Pull a `<marker>{...};` JSON object literal out of inline HTML/JS,
    balancing braces (respecting string content) instead of a regex that
    would stop at the first '};' - which can appear inside the JSON's own
    string values well before the object actually closes."""
    start = -1
    for marker in markers:
        idx = html.find(marker)
        if idx != -1:
            start = idx + len(marker)
            break
    if start == -1 or start >= len(html) or html[start] != "{":
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_video_details(html, url):
    """Best-effort structured extraction for a YouTube watch page: reads
    title/channel/description/etc. straight out of the ytInitialPlayerResponse
    JSON YouTube embeds in every watch page's HTML - this needs the plain
    (un-rendered) server HTML specifically, since a Playwright-rendered DOM
    doesn't reliably keep that inline script after YouTube's own JS runs and
    consumes it. Returns None for anything that isn't a recognizable YouTube
    watch page, or where the expected JSON isn't found/parseable (falls back
    to the generic extractor in that case).
    """
    if not is_youtube_video_url(url):
        return None

    data = _extract_json_object(html, YT_PLAYER_RESPONSE_MARKERS)
    if not data:
        return None

    details = data.get("videoDetails") or {}
    title = details.get("title")
    if not title:
        return None

    return {
        "title": title,
        "author": details.get("author"),
        "description": details.get("shortDescription"),
        "view_count": details.get("viewCount"),
        "length_seconds": details.get("lengthSeconds"),
        "keywords": details.get("keywords") or [],
    }


def render_video_text(details):
    """Flatten a video-details dict into prose for cleaned_content/relevance
    scoring. Comments are intentionally not included here - they're stored as
    a separate structured list (like tables), not merged into this text."""
    parts = [f"Video: {details['title']}."]
    if details.get("author"):
        parts.append(f"Channel: {details['author']}.")
    if details.get("view_count"):
        parts.append(f"Views: {details['view_count']}.")
    if details.get("length_seconds"):
        parts.append(f"Length: {details['length_seconds']} seconds.")
    if details.get("keywords"):
        parts.append(f"Keywords: {', '.join(details['keywords'])}.")
    if details.get("description"):
        parts.append(f"Description: {details['description']}")
    return " ".join(parts)


def _api_error_reason(response):
    try:
        return response.json().get("error", {}).get("errors", [{}])[0].get("reason")
    except ValueError:
        return None


def fetch_comments(video_id, api_key, max_comments=50, session=None):
    """Top-level comments for a video via the official YouTube Data API v3
    (commentThreads.list - 1 quota unit/call), paginated up to max_comments.
    Raises CommentsDisabled (caller should treat as "no comments", not an
    error) or YoutubeApiError for anything else (quota exceeded, bad key,
    video not found, ...)."""
    session = session or requests
    comments = []
    page_token = None

    while len(comments) < max_comments:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "key": api_key,
            "maxResults": min(100, max_comments - len(comments)),
            "order": "relevance",
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token

        response = session.get(YOUTUBE_COMMENTS_URL, params=params, timeout=15)
        if response.status_code != 200:
            reason = _api_error_reason(response)
            if reason == "commentsDisabled":
                raise CommentsDisabled(reason, f"Comments disabled for video {video_id}")
            raise YoutubeApiError(
                reason, f"YouTube comments API error ({response.status_code}) for video {video_id}: {response.text[:300]}"
            )

        data = response.json()
        for item in data.get("items", []):
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comments.append({
                "author": snippet.get("authorDisplayName", ""),
                "text": snippet.get("textDisplay", ""),
                "likes": snippet.get("likeCount", 0),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments[:max_comments]


def search_videos(query, api_key, max_results=25, session=None):
    """One page of youtube.com's video search for `query` (search.list - 100
    quota units/call, unlike the 1-unit comment/video-details calls, so this
    deliberately fetches a single page rather than paginating - each extra
    page would burn through the standard 10,000/day free quota fast). Returns
    a list of video ids."""
    session = session or requests
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": min(max_results, 50),
        "key": api_key,
    }
    response = session.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    if response.status_code != 200:
        reason = _api_error_reason(response)
        raise YoutubeApiError(reason, f"YouTube search API error ({response.status_code}) for {query!r}: {response.text[:300]}")

    video_ids = []
    for item in response.json().get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if video_id:
            video_ids.append(video_id)
    return video_ids


class YoutubePipeline:
    """Item pipeline stage: detects a YouTube video URL, parses its metadata
    from the (free) page HTML, and fetches its comments via the (API-key-
    gated) Data API. Must run before NormalizationPipeline, which builds
    cleaned_content from the `youtube_video` field this sets."""

    def __init__(self, api_key, max_comments):
        self.api_key = api_key
        self.max_comments = max_comments

    @classmethod
    def from_crawler(cls, crawler):
        env_name = crawler.settings.get("YOUTUBE_API_KEY_ENV", "YOUTUBE_API_KEY")
        return cls(
            api_key=os.environ.get(env_name),
            max_comments=crawler.settings.getint("YOUTUBE_MAX_COMMENTS", 50),
        )

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        url = adapter.get("url", "")
        video_id = extract_video_id(url)
        if not video_id:
            return item

        details = extract_video_details(adapter.get("html", ""), url)
        if details is None:
            spider.logger.warning("Recognized YouTube video URL but couldn't parse video details: %s", url)
            return item
        adapter["youtube_video"] = details

        if not self.api_key:
            spider.logger.warning("YOUTUBE_API_KEY not set - skipping comments for %s", url)
            adapter["comments"] = []
            return item

        try:
            adapter["comments"] = fetch_comments(video_id, self.api_key, self.max_comments)
        except CommentsDisabled:
            adapter["comments"] = []
        except YoutubeApiError as e:
            spider.logger.warning("YouTube comment fetch failed for %s: %s", url, e)
            adapter["comments"] = []

        return item
