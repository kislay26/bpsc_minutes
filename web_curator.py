"""BPSC Web & Newspaper Current Affairs Curator.

Fetches the latest articles from:
- The Indian Express (Explained, India, Editorials)
- The Hindu (National, Editorials, Business)
- State Civils (statecivils.com) & Bihar-focused current affairs

Curates 8-12 comprehensive BPSC Prelims & Mains stories with
in-depth summaries, exam takeaways, and clickable source links.
"""
from __future__ import annotations

import html
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

IE_FEEDS = {
    "The Indian Express (Explained)": "https://indianexpress.com/section/explained/feed/",
    "The Indian Express (National)": "https://indianexpress.com/section/india/feed/",
    "The Indian Express (Editorial)": "https://indianexpress.com/section/opinion/editorials/feed/",
}

TH_FEEDS = {
    "The Hindu (National)": "https://www.thehindu.com/news/national/feeder/default.rss",
    "The Hindu (Editorial)": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
    "The Hindu (Business & Economy)": "https://www.thehindu.com/business/feeder/default.rss",
}

STATE_CIVILS_URL = "https://statecivils.com/current-affairs/"


@dataclass
class RawArticle:
    source: str
    title: str
    link: str
    summary: str


class SimpleLinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles: list[tuple[str, str]] = []
        self._current_href = ""
        self._text_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
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
            if len(title) > 15:
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


def parse_rss_feed(source_name: str, url: str, max_items: int = 8) -> list[RawArticle]:
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
                    summary=desc[:350] if desc else "",
                ))
    except Exception as exc:
        logger.warning("Failed to fetch RSS from %s (%s): %s", source_name, url, exc)
    return articles


def fetch_state_civils(max_items: int = 8) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        html_content = fetch_url(STATE_CIVILS_URL).decode("utf-8", errors="ignore")
        parser = SimpleLinkExtractor()
        parser.feed(html_content)
        seen_links = set()
        for title, link in parser.articles:
            if link not in seen_links:
                seen_links.add(link)
                articles.append(RawArticle(
                    source="State Civils (Bihar)",
                    title=title,
                    link=link,
                    summary="Bihar-focused state news, cabinet decisions, and daily current affairs update.",
                ))
                if len(articles) >= max_items:
                    break
    except Exception as exc:
        logger.warning("Failed to scrape State Civils: %s", exc)
    return articles


def collect_daily_feed_candidates() -> list[RawArticle]:
    """Collects news candidates from The Indian Express, The Hindu, and State Civils."""
    candidates: list[RawArticle] = []

    # Indian Express (Explained, National, Opinion)
    for name, url in IE_FEEDS.items():
        candidates.extend(parse_rss_feed(name, url, max_items=8))

    # The Hindu (National, Editorial, Business)
    for name, url in TH_FEEDS.items():
        candidates.extend(parse_rss_feed(name, url, max_items=8))

    # State Civils (Bihar)
    candidates.extend(fetch_state_civils(max_items=8))

    return candidates


def curate_with_gemini(
    articles: list[RawArticle],
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[dict[str, Any]]:
    """Uses Gemini to filter and format BPSC-relevant news into structured, in-depth summaries."""
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
You are the Chief Academic Current Affairs Editor for the Bihar Public Service Commission (BPSC) Civil Services Examination.
Review the candidate articles collected today from The Hindu, The Indian Express, and State Civils:

{json.dumps(input_payload, ensure_ascii=False, indent=2)}

SELECTION INSTRUCTIONS:
1. Select 8 to 12 articles of HIGHEST ACADEMIC AND EXAM VALUE for BPSC candidates (CCE Prelims & Mains).
2. ENSURE BALANCED COVERAGE ACROSS:
   - Bihar Affairs: State government schemes, Bihar budget/economic survey, industrial updates, environmental issues (e.g. North Bihar floods/Kosi-Mechi).
   - Indian Polity & Constitution: Supreme Court judgments, federal relations, parliamentary bills, election reforms.
   - Economy & Agriculture: Inflation, RBI monetary policy, agricultural trends, trade, employment policies.
   - Environment, Climate & Biodiversity: Protected areas, disaster management, renewable energy.
   - Science, Tech & Health: Space (ISRO), AI policy, public healthcare initiatives.
3. EXCLUDE:
   - Routine party politics, election rally slogans, political rhetoric, local petty crimes, sports scores, celebrity gossip.

FOR EACH SELECTED ARTICLE, PROVIDE A WELL-WRITTEN, HIGH-YIELD ANALYSIS:
- title: A formal, informative headline (e.g. "Supreme Court Lays Down Norms on Governor's Assent to State Bills")
- source: e.g. "The Hindu", "The Indian Express (Explained)", "State Civils"
- syllabus_tag: Exact BPSC Paper link (e.g. "GS-2: Indian Polity & Governance", "GS-2: Bihar Economy", "GS-1: National Events", "Prelims: Environment")
- exam_type: "Prelims Fact" | "Mains Analytical" | "Both"
- summary: A comprehensive, 2-3 sentence overview explaining what happened, the context, and key background facts.
- exam_pointers: An array of 2-3 specific exam-oriented bullet points containing concrete data, constitutional articles, ministry names, or Bihar linkages.
- link: EXACT original URL provided in the input

Return a JSON array of objects following the exact schema.
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
                        "summary": {"type": "string"},
                        "exam_pointers": {"type": "array", "items": {"type": "string"}},
                        "link": {"type": "string"},
                    },
                    "required": ["title", "source", "syllabus_tag", "exam_type", "summary", "exam_pointers", "link"],
                },
            },
        },
    }

    req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=75) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(content)


def format_for_telegram(curated_news: list[dict[str, Any]], edition_date: str) -> list[str]:
    """Formats curated news into beautiful Telegram-ready HTML chunks (<= 3800 chars each)."""
    if not curated_news:
        return ["⚠️ <i>No high-priority BPSC current affairs found for today.</i>"]

    header = (
        f"📰 <b>BPSC Daily Current Affairs Radar — {edition_date}</b>\n"
        f"<i>Curated from The Hindu, Indian Express & State Civils</i>\n\n"
    )

    chunks: list[str] = []
    current_chunk = header

    for idx, item in enumerate(curated_news, 1):
        safe_title = html.escape(item.get("title", ""))
        safe_tag = html.escape(item.get("syllabus_tag", "General Studies"))
        safe_type = html.escape(item.get("exam_type", "Prelims & Mains"))
        safe_summary = html.escape(item.get("summary", ""))
        safe_source = html.escape(item.get("source", "Source"))
        safe_link = html.escape(item.get("link", "#"))

        block = f"🔹 <b>{idx}. {safe_title}</b>\n"
        block += f"📌 <b>Tag:</b> <code>{safe_tag}</code> | <i>{safe_type}</i>\n\n"
        block += f"📖 <b>Overview:</b>\n{safe_summary}\n\n"
        block += f"🎯 <b>BPSC Exam Pointers:</b>\n"
        for pt in item.get("exam_pointers", []):
            block += f"• {html.escape(pt)}\n"
        block += f"🔗 <b>Full Article:</b> <a href=\"{safe_link}\">Read on {safe_source} ↗</a>\n\n"
        block += "──────────────────────────\n\n"

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

    # Fetch live feeds from Indian Express, The Hindu, and State Civils
    candidates = collect_daily_feed_candidates()
    if not candidates:
        return [f"⚠️ <i>Could not retrieve live news feeds right now. Check internet connectivity.</i>"]

    # Curate with Gemini
    model = cfg.model if cfg.provider == "gemini" else "gemini-2.5-flash"
    api_key = cfg.api_key or os.getenv("GEMINI_API_KEY", "")

    curated = curate_with_gemini(candidates, api_key=api_key, model=model)
    if curated:
        cache_file.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")

    return format_for_telegram(curated, day)
