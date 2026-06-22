"""Ingestion connectors — pull the content you consume into HydraDB.

The north-star goal is "dump in *all* the content I take in." `capture`/`sync` cover
text and files; connectors cover the web. Each connector fetches a source, extracts
clean text, and hands it to `add_memory(infer=True)` so HydraDB wires the graph.

Dependency-light by design, all free / no-auth:
  • Article / web pages — `requests` + a stdlib HTML→text extractor (no extra deps).
  • Tweets — the free Twitter oEmbed endpoint (no API key, no auth).
  • YouTube transcripts — `youtube_transcript_api` (a bundled dependency; works OOTB).
  • LinkedIn — best-effort via the article reader; login-walled posts get a "paste it" hint.

Add a connector by writing one `fetch_*(url) -> Source` function and routing it in
`fetch(url)`. Everything downstream (`BrainEngine.ingest_url`, the CLI `read` command)
stays unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs

import requests

_UA = "Mozilla/5.0 (compatible; hydrabrain/0.1; +https://hydradb.com)"
_SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "aside", "form", "svg"}
_BLOCK_TAGS = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


@dataclass
class Source:
    """A fetched piece of web content, normalized for capture."""

    title: str
    text: str
    url: str
    kind: str = "article"  # article | youtube


class _TextExtractor(HTMLParser):
    """Minimal readable-text extractor: drop boilerplate tags, keep block structure."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")

    def result(self) -> tuple[str, str]:
        raw = "".join(self.parts)
        # Collapse runs of blank lines / spaces.
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw).strip()
        return self.title.strip(), raw


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, readable_text) from an HTML string. Pure, testable, no network."""
    ex = _TextExtractor()
    ex.feed(html)
    return ex.result()


def fetch_article(url: str) -> Source:
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=(10, 30),
                        allow_redirects=True)
    resp.raise_for_status()
    title, text = html_to_text(resp.text)
    if not text.strip():
        host = (urlparse(url).hostname or "").lower()
        if "linkedin.com" in host:
            raise ValueError("LinkedIn posts usually require a login, so the public page has no "
                             "readable text. Copy the post text and use 'Add a note' instead.")
        raise ValueError(f"no readable text extracted from {url}")
    return Source(title=title or url, text=text, url=url, kind="article")


def is_tweet(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return ("twitter.com" in host or host == "x.com" or host.endswith(".x.com")) and "/status/" in url


def fetch_tweet(url: str) -> Source:
    """Fetch a tweet via the free, no-auth Twitter oEmbed endpoint."""
    resp = requests.get(
        "https://publish.twitter.com/oembed",
        params={"url": url, "omit_script": "1", "dnt": "true"},
        headers={"User-Agent": _UA}, timeout=(10, 30),
    )
    resp.raise_for_status()
    data = resp.json()
    _, text = html_to_text(data.get("html", ""))
    author = data.get("author_name", "")
    if not text.strip():
        raise ValueError(f"no text found for tweet {url}")
    body = f"Tweet by {author}: {text}" if author else f"Tweet: {text}"
    return Source(title=f"Tweet by {author}" if author else "Tweet", text=body, url=url, kind="tweet")


def _youtube_id(url: str) -> str:
    u = urlparse(url)
    if u.hostname in ("youtu.be",):
        return u.path.lstrip("/")
    if u.hostname and "youtube" in u.hostname:
        if u.path.startswith("/watch"):
            return parse_qs(u.query).get("v", [""])[0]
        if u.path.startswith(("/embed/", "/shorts/")):
            return u.path.split("/")[2]
    return ""


def is_youtube(url: str) -> bool:
    return bool(_youtube_id(url))


def fetch_youtube(url: str) -> Source:
    vid = _youtube_id(url)
    if not vid:
        raise ValueError(f"not a recognizable YouTube URL: {url}")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "YouTube ingestion needs `youtube-transcript-api`: pip install youtube-transcript-api"
        ) from e
    # The API moved from a static get_transcript() (<1.0) to an instance .fetch() (>=1.0).
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        segments = YouTubeTranscriptApi.get_transcript(vid)
        text = " ".join(s.get("text", "") for s in segments).strip()
    else:
        fetched = YouTubeTranscriptApi().fetch(vid)
        text = " ".join(getattr(s, "text", "") for s in fetched).strip()
    if not text:
        raise ValueError(f"no transcript available for {url}")
    return Source(title=f"YouTube {vid}", text=text, url=url, kind="youtube")


def fetch(url: str) -> Source:
    """Route a URL to the right connector and return normalized content."""
    if is_youtube(url):
        return fetch_youtube(url)
    if is_tweet(url):
        return fetch_tweet(url)
    return fetch_article(url)
