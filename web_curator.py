"""BPSC Web & Newspaper Current Affairs Curator.

Fetches the latest articles from:
- The Indian Express (Explained, India, Editorials)
- The Hindu (National, Editorials, Business)
- State Civils (statecivils.com) & Bihar-focused current affairs

Curates and formats high-yield BPSC Prelims & Mains bullet points
with direct clickable source links using Google Gemini.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from core import Config

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Top Feeds for UPSC / BPSC current affairs
IE_FEEDS = {
    "IE Explained": "https://indianexpress.com/section/explained/feed/",
    "IE National": "https://indianexpress.com/section/india/feed/",
    "IE Editorials": "https://indianexpress.com/section/opinion/editorials/feed/",
}

TH_FEEDS = {
    "The Hindu National": "https://www.thehindu.com/news/national/feeder/default.rss",
    "The Hindu Editorial": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
    "The Hindu Business": "https://www.thehindu.com/business/feeder/default.rss",
}

STATE_CIVILS_URL = "https://statecivils.com/current-affairs/"


@dataclass
class RawArticle:
    source: str
    title: str
    link: str
    summary: str


class SimpleLinkExtractor(HTMLParser):
    """Extracts article headlines and URLs from statecivils.com."""

    def __init__(self):
        super().__init__()
        self.articles: list[tuple[str, str]] = []
        self._current_tag = ""
        self._current_href = ""
        self._text_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self._current_tag = tag
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href") or ""
            if "/current-affairs/" in href and href != STATE_CIVILS_URL:
                self._current_href = href
                self._text_buffer = []

    def handle_data(self, data: str):
        if self._current_href:
            self._text_buffer.append(data.strip())

    def handle_endtag(self, tag: str):
        if tag == "a" and self._current_href:
            title = " ".join(t for t in self._text_buffer if t)
            if len(title) > 15:  # meaningful title length
                self.articles.append((title, self._current_href))
            self._current_href = ""
            self._text_buffer = []


def fetch_url(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean_xml_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def parse_rss_feed(source_name: str, url: str, max_items: int = 5) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        raw_xml = fetch_url(url)
        root = ET.fromstring(raw_xml)
        items = root.findall(".//item")
        for item in items[:max_items]:
            title = clean_xml_text(item.findtext("title"))
            link = clean_xml_text(item.findtext("link"))
            desc = clean_xml_text(item.findtext("description"))
            if title and link:
                articles.append(RawArticle(
                    source=source_name,
                    title=title,
                    link=link,
                    summary=desc[:250] if desc else "",
                ))
    except Exception as exc:
        logger.warning("Failed to fetch RSS from %s (%s): %s", source_name, url, exc)
    return articles


def fetch_state_civils(max_items: int = 5) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        html = fetch_url(STATE_CIVILS_URL).decode("utf-8", errors="ignore")
        parser = SimpleLinkExtractor()
        parser.feed(html)
        seen_links = set()
        for title, link in parser.articles:
            if link not in seen_links:
                seen_links.add(link)
                articles.append(RawArticle(
                    source="State Civils (Bihar)",
                    title=title,
                    link=link,
                    summary="Bihar-focused state news & daily current affairs update.",
                ))
                if len(articles) >= max_items:
                    break
    except Exception as exc:
        logger.warning("Failed to scrape State Civils: %s", exc)
    return articles


def collect_daily_feed_candidates() -> list[RawArticle]:
    """Collects news candidates from The Indian Express, The Hindu, and State Civils."""
    candidates: list[RawArticle] = []

    # Indian Express
    for name, url in IE_FEEDS.items():
        candidates.extend(parse_rss_feed(name, url, max_items=5))

    # The Hindu
    for name, url in TH_FEEDS.items():
        candidates.extend(parse_rss_feed(name, url, max_items=5))

    # State Civils
    candidates.extend(fetch_state_civils(max_items=5))

    return candidates


def curate_with_gemini(
    articles: list[RawArticle],
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[dict[str, Any]]:
    """Uses Gemini to filter and format BPSC-relevant news into structured bullet points with links."""
    if not articles:
        return []

    input_payload = [
        {
            "id": idx + 1,
            "source": a.source,
            "title": a.title,
            "link": a.link,
            "summary": a.summary,
        }
        for idx, a in enumerate(articles)
    ]

    prompt = f"""
You are the Senior Current Affairs Editor for the Bihar Public Service Commission (BPSC) exam.
Review the candidate articles gathered today from The Hindu, The Indian Express, and State Civils:

{json.dumps(input_payload, ensure_ascii=False, indent=2)}

CRITERIA:
1. Select 6 to 10 articles of HIGHEST value for BPSC candidates (CCE Prelims & Mains).
2. PRIORITIZE:
   - Bihar-specific initiatives, cabinet decisions, geography/flood management, economy & schemes.
   - National Polity & Governance (Supreme Court rulings, constitutional issues, federalism).
   - Indian Economy (RBI, trade, agriculture, budget, infrastructure).
   - Environment, Biodiversity & Climate Change.
   - Key Science & Technology developments (ISRO, energy, public health).
3. EXCLUDE:
   - Political party bickering, speeches, rallies, routine local crimes, sports trivia, celebrity news.

FOR EACH SELECTED STORY, RETURN:
- title: Crisp, clear headline
- source: e.g. "The Indian Express (Explained)", "The Hindu", "State Civils"
- syllabus_tag: e.g. "GS-2: Polity & Governance", "GS-2: Bihar Economy", "GS-1: National Events", "Prelims: Environment"
- exam_type: "Prelims Fact" | "Mains Analytical" | "Both"
- bullets: Array of 2-3 high-yield facts, data, constitutional articles, or policy points
- link: EXACT original link provided in the input

Return a JSON array of objects with the exact schema.
"""

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "source": {"type": "string"},
                        "syllabus_tag": {"type": "string"},
                        "exam_type": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "link": {"type": "string"},
                    },
                    "required": ["title", "source", "syllabus_tag", "exam_type", "bullets", "link"],
                },
            },
        },
    }

    req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(content)


def format_for_telegram(curated_news: list[dict[str, Any]], edition_date: str) -> list[str]:
    """Formats curated news into Telegram-friendly Markdown message chunks (<= 3800 chars each)."""
    if not curated_news:
        return ["⚠️ No high-priority BPSC current affairs found for today."]

    header = f"📰 *BPSC Current Affairs Radar — {edition_date}*\n"
    header += "_Curated from The Hindu, Indian Express & State Civils_\n\n"

    chunks: list[str] = []
    current_chunk = header

    for idx, item in enumerate(curated_news, 1):
        block = f"🔹 *{idx}. {item['title']}*\n"
        block += f"📌 *Tag:* `{item['syllabus_tag']}` | _{item.get('exam_type', 'Prelims & Mains')}_\n"
        for bullet in item.get("bullets", []):
            block += f"• {bullet}\n"
        block += f"🔗 *Source:* [{item['source']}]({item['link']})\n\n"

        if len(current_chunk) + len(block) > 3600:
            chunks.append(current_chunk.strip())
            current_chunk = block
        else:
            current_chunk += block

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def get_daily_brief(cfg: Config, target_date: str | None = None, force: bool = False) -> list[str]:
    """Retrieves or builds the daily brief. Caches output in data/briefs/YYYY-MM-DD.json."""
    day = target_date or date.today().isoformat()
    cache_dir = cfg.root / "briefs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{day}.json"

    if not force and cache_file.is_file():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            return format_for_telegram(cached_data, day)
        except Exception:
            pass

    # Fetch live feeds
    candidates = collect_daily_feed_candidates()
    if not candidates:
        return [f"⚠️ Could not retrieve live news feeds right now. Check internet connectivity."]

    # Curate with Gemini
    model = cfg.model if cfg.provider == "gemini" else "gemini-2.5-flash"
    api_key = cfg.api_key
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY", "")

    curated = curate_with_gemini(candidates, api_key=api_key, model=model)
    if curated:
        cache_file.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")

    return format_for_telegram(curated, day)

