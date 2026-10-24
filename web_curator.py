"""BPSC Category-Wise Current Affairs Curator.

Sources (RSS + Scrapers):
- The Hindu (National, International, Editorial, Business, Sci-Tech)
- The Indian Express (Explained, National, Editorials)
- PIB India (Press Information Bureau — official govt releases)
- Down To Earth (Environment & Bihar floods)
- TechCrunch AI / VentureBeat AI / MIT Tech Review (AI & Emerging Tech)
- State Civils (statecivils.com) & Drishti IAS (drishtiias.com)

Curates news grouped into strict BPSC Syllabus Categories with
in-depth academic summaries, exam pointers, source links, and follow-up prompts.
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

# ──────────────────────────────────────────────────────────────────────────────
# RSS FEED SOURCES
# ──────────────────────────────────────────────────────────────────────────────
FEEDS = {
    # The Hindu
    "The Hindu (National)": "https://www.thehindu.com/news/national/feeder/default.rss",
    "The Hindu (International)": "https://www.thehindu.com/news/international/feeder/default.rss",
    "The Hindu (Editorial & Opinion)": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
    "The Hindu (Business & Economy)": "https://www.thehindu.com/business/feeder/default.rss",
    "The Hindu (Science & Tech)": "https://www.thehindu.com/sci-tech/feeder/default.rss",
    # The Indian Express
    "The Indian Express (Explained)": "https://indianexpress.com/section/explained/feed/",
    "The Indian Express (National)": "https://indianexpress.com/section/india/feed/",
    "The Indian Express (Editorials)": "https://indianexpress.com/section/opinion/editorials/feed/",
    "The Indian Express (World)": "https://indianexpress.com/section/world/feed/",
    # PIB — Official Government Press Releases
    "PIB India (Official Govt Releases)": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    # Environment & Bihar floods
    "Down To Earth (Environment)": "https://www.downtoearth.org.in/rss/latest",
    # AI & Emerging Technology
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/ai/feed/",
}

# ──────────────────────────────────────────────────────────────────────────────
# SCRAPE-BASED SOURCES  (no RSS feed available)
# ──────────────────────────────────────────────────────────────────────────────
STATE_CIVILS_URL = "https://statecivils.com/current-affairs/"
DRISHTI_IAS_URL = "https://www.drishtiias.com/current-affairs-news-analysis-editorials"


@dataclass
class RawArticle:
    source: str
    title: str
    link: str
    summary: str


# ──────────────────────────────────────────────────────────────────────────────
# HTML LINK EXTRACTORS
# ──────────────────────────────────────────────────────────────────────────────

class SimpleLinkExtractor(HTMLParser):
    """Generic anchor-tag link extractor that filters by a URL fragment."""

    def __init__(self, url_fragment: str = ""):
        super().__init__()
        self.url_fragment = url_fragment
        self.articles: list[tuple[str, str]] = []
        self._current_href = ""
        self._text_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href") or ""
            if self.url_fragment in href and href != STATE_CIVILS_URL:
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


# ──────────────────────────────────────────────────────────────────────────────
# NETWORK HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean_xml_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


# ──────────────────────────────────────────────────────────────────────────────
# FEED PARSERS
# ──────────────────────────────────────────────────────────────────────────────

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
                    summary=desc[:400] if desc else "",
                ))
    except Exception as exc:
        logger.warning("Failed to fetch RSS from %s (%s): %s", source_name, url, exc)
    return articles


def fetch_state_civils(max_items: int = 8) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        html_content = fetch_url(STATE_CIVILS_URL).decode("utf-8", errors="ignore")
        parser = SimpleLinkExtractor(url_fragment="/current-affairs/")
        parser.feed(html_content)
        seen_links: set[str] = set()
        for title, link in parser.articles:
            if link not in seen_links:
                seen_links.add(link)
                articles.append(RawArticle(
                    source="State Civils / Bihar Current Affairs",
                    title=title,
                    link=link,
                    summary="Bihar-focused state government initiatives, schemes, and exam current affairs.",
                ))
                if len(articles) >= max_items:
                    break
    except Exception as exc:
        logger.warning("Failed to scrape State Civils: %s", exc)
    return articles


def fetch_drishti_ias(max_items: int = 6) -> list[RawArticle]:
    """Scrapes today's current affairs news from Drishti IAS."""
    articles: list[RawArticle] = []
    try:
        html_content = fetch_url(DRISHTI_IAS_URL).decode("utf-8", errors="ignore")
        parser = SimpleLinkExtractor(url_fragment="/current-affairs-news-analysis-editorials/")
        parser.feed(html_content)
        seen_links: set[str] = set()
        for title, link in parser.articles:
            if link not in seen_links and len(link) > len(DRISHTI_IAS_URL):
                seen_links.add(link)
                # Ensure absolute URL
                if link.startswith("/"):
                    link = "https://www.drishtiias.com" + link
                articles.append(RawArticle(
                    source="Drishti IAS",
                    title=title,
                    link=link,
                    summary="UPSC/BPSC-oriented analysis of current affairs for Prelims and Mains preparation.",
                ))
                if len(articles) >= max_items:
                    break
    except Exception as exc:
        logger.warning("Failed to scrape Drishti IAS: %s", exc)
    return articles


# ──────────────────────────────────────────────────────────────────────────────
# AGGREGATOR
# ──────────────────────────────────────────────────────────────────────────────

def collect_daily_feed_candidates() -> list[RawArticle]:
    candidates: list[RawArticle] = []
    for name, url in FEEDS.items():
        candidates.extend(parse_rss_feed(name, url, max_items=8))
    candidates.extend(fetch_state_civils(max_items=8))
    candidates.extend(fetch_drishti_ias(max_items=6))
    logger.info("Total raw candidates collected: %d", len(candidates))
    return candidates


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI CURATION
# ──────────────────────────────────────────────────────────────────────────────

def curate_with_gemini(
    articles: list[RawArticle],
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[dict[str, Any]]:
    """Uses Gemini to filter, structure, and categorize BPSC-relevant news."""
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
You are the Chief Academic Current Affairs Editor for BPSC (Bihar Public Service Commission) Examination.
Today's articles have been collected from multiple sources including:
The Hindu (National, International, Editorial, Business, Science & Tech),
The Indian Express (Explained, National, Editorials, World),
PIB India (official government press releases),
Down To Earth (environment & disasters),
TechCrunch AI, VentureBeat AI (artificial intelligence news),
State Civils (Bihar-focused current affairs portal),
and Drishti IAS (UPSC/BPSC-oriented analysis).

Here are today's candidate articles:
{json.dumps(input_payload, ensure_ascii=False, indent=2)}

BPSC EXAM CONTEXT:
- BPSC 70th/71st Mains: GS-2 covers Bihar Polity, Economy, Geography, History, Environment
- BPSC also tests: Indian national affairs, bilateral treaties, multilateral organizations (UN, SCO, BRICS, QUAD, G20, SAARC)
- Science & Tech: ISRO missions, Defence R&D, biotech, digital India, space policy
- International Affairs: India's foreign policy decisions, India-China/India-Pakistan, global summits
- AI & Emerging Tech: Government AI policy, NITI Aayog AI initiatives, generative AI regulation, AI in education/healthcare

SELECTION INSTRUCTIONS:
1. Select 12 to 16 articles of HIGHEST EXAM VALUE for BPSC Prelims & Mains.
2. MANDATORY COVERAGE — ensure at least:
   - 2 Bihar Special / State Affairs articles
   - 2 National Affairs articles (major India-level events, schemes, SC judgments)
   - 2 International Affairs articles (India's foreign relations, multilateral summits, UN bodies)
   - 1 Economy or Agriculture article (RBI, budget, MSP, India-specific economic data)
   - 1 Environment or Disaster Management article
   - 2 AI & Emerging Technology articles (prioritize India AI policy, ISRO, Defence tech, or global AI regulation that India is involved in)
3. CATEGORIZE EVERY ARTICLE into ONE of these strict BPSC categories:
   - "Bihar Special & State Affairs"
   - "Indian Polity & Governance (GS-2)"
   - "National Affairs & India in Focus"
   - "International Affairs & India's Foreign Policy"
   - "Economy & Agriculture (GS-2)"
   - "Environment, Climate & Disaster Management"
   - "Artificial Intelligence & Emerging Technology"
4. FOR EACH ARTICLE, PROVIDE A WELL-WRITTEN, THOROUGH ACADEMIC BRIEF:
   - title: Clear, professional headline.
   - category: One of the 7 categories above (exactly as written).
   - syllabus_tag: Exact paper link (e.g. "BPSC GS-2: Indian Polity", "BPSC GS-2: Bihar Economy", "BPSC Prelims: Environment", "BPSC GS-2: International Relations", "BPSC GS-2: Science & Technology").
   - exam_stage: "Prelims Fact" | "Mains Analytical" | "Both".
   - summary: A comprehensive, 2-3 sentence overview explaining what happened, background context, and key stakeholders.
   - exam_pointers: Array of 2-4 specific points with exact data, constitutional articles, ministry names, Bihar linkages, or international treaty names.
   - source: e.g. "The Hindu", "PIB India", "TechCrunch AI", "Drishti IAS".
   - link: EXACT original link from the input. Do NOT fabricate links.

Return a JSON array of objects following the exact schema. Do NOT include any markdown formatting or code fences — return raw JSON only.
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
                        "category": {"type": "string"},
                        "syllabus_tag": {"type": "string"},
                        "exam_stage": {"type": "string"},
                        "summary": {"type": "string"},
                        "exam_pointers": {"type": "array", "items": {"type": "string"}},
                        "source": {"type": "string"},
                        "link": {"type": "string"},
                    },
                    "required": ["title", "category", "syllabus_tag", "exam_stage", "summary", "exam_pointers", "source", "link"],
                },
            },
        },
    }

    req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(content)


# ──────────────────────────────────────────────────────────────────────────────
# TELEGRAM FORMATTER
# ──────────────────────────────────────────────────────────────────────────────

def format_for_telegram(curated_news: list[dict[str, Any]], edition_date: str) -> list[str]:
    """Formats curated news into category-wise Telegram HTML messages."""
    if not curated_news:
        return ["⚠️ <i>No high-priority BPSC current affairs found for today.</i>"]

    # Category display order
    categories_order = [
        ("🌾 BIHAR SPECIAL & STATE AFFAIRS",           ["Bihar Special & State Affairs", "Bihar"]),
        ("📰 NATIONAL AFFAIRS & INDIA IN FOCUS",       ["National Affairs & India in Focus", "National"]),
        ("🌐 INTERNATIONAL AFFAIRS & FOREIGN POLICY",  ["International Affairs & India's Foreign Policy", "International"]),
        ("⚖️ INDIAN POLITY & GOVERNANCE (GS-2)",       ["Indian Polity & Governance (GS-2)", "Polity", "Governance"]),
        ("📈 ECONOMY & AGRICULTURE (GS-2)",            ["Economy & Agriculture (GS-2)", "Economy", "Agriculture"]),
        ("🌿 ENVIRONMENT, CLIMATE & DISASTER MGMT",    ["Environment, Climate & Disaster Management", "Environment", "Climate"]),
        ("🤖 ARTIFICIAL INTELLIGENCE & EMERGING TECH", ["Artificial Intelligence & Emerging Technology", "AI", "Artificial Intelligence"]),
    ]

    grouped: dict[str, list[dict[str, Any]]] = {title: [] for title, _ in categories_order}
    grouped["🔖 OTHER NOTABLE DEVELOPMENTS"] = []

    for item in curated_news:
        cat_str = item.get("category", "")
        placed = False
        for title, keywords in categories_order:
            if any(k.lower() in cat_str.lower() for k in keywords):
                grouped[title].append(item)
                placed = True
                break
        if not placed:
            grouped["🔖 OTHER NOTABLE DEVELOPMENTS"].append(item)

    chunks: list[str] = []
    header = (
        f"🏛️ <b>BPSC Daily Current Affairs Digest — {edition_date}</b>\n"
        f"<i>📡 Sources: The Hindu · Indian Express · PIB India · Down To Earth · TechCrunch AI · VentureBeat · State Civils · Drishti IAS</i>\n\n"
    )
    current_chunk = header
    item_counter = 1

    for category_title, items in grouped.items():
        if not items:
            continue

        cat_header = f"━━━━━━━━━━━━━━━━━━━━\n<b>{category_title}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        if len(current_chunk) + len(cat_header) > 3600:
            chunks.append(current_chunk.strip())
            current_chunk = cat_header
        else:
            current_chunk += cat_header

        for item in items:
            safe_title   = html.escape(item.get("title", ""))
            safe_tag     = html.escape(item.get("syllabus_tag", "General Studies"))
            safe_stage   = html.escape(item.get("exam_stage", "Prelims & Mains"))
            safe_summary = html.escape(item.get("summary", ""))
            safe_source  = html.escape(item.get("source", "Source"))
            safe_link    = html.escape(item.get("link", "#"))

            block  = f"🔹 <b>{item_counter}. {safe_title}</b>\n"
            block += f"📌 <b>Syllabus:</b> <code>{safe_tag}</code> | <i>{safe_stage}</i>\n\n"
            block += f"📖 <b>Overview:</b>\n{safe_summary}\n\n"
            block += f"🎯 <b>BPSC Exam Pointers:</b>\n"
            for pt in item.get("exam_pointers", []):
                block += f"• {html.escape(pt)}\n"
            block += f"🔗 <b>Full Source:</b> <a href=\"{safe_link}\">Read on {safe_source} ↗</a>\n\n"

            item_counter += 1

            if len(current_chunk) + len(block) > 3600:
                chunks.append(current_chunk.strip())
                current_chunk = block
            else:
                current_chunk += block

    # ── Follow-up interactive prompt ──────────────────────────────────────────
    follow_up = (
        "💡 <b>Follow-Up Study Options:</b>\n"
        "• Send <b>Practice 5</b> to solve 5 BPSC MCQs on today's topics.\n"
        "• Ask <b>\"Mains Question on [Topic]\"</b> for a 38-mark answer writing prompt.\n"
        "• Ask <b>\"AI News Today\"</b> for a deeper dive into today's tech stories.\n"
        "• Ask any conceptual question to learn more!\n"
    )

    if len(current_chunk) + len(follow_up) > 3600:
        chunks.append(current_chunk.strip())
        chunks.append(follow_up)
    else:
        current_chunk += follow_up
        chunks.append(current_chunk.strip())

    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

def get_daily_brief(cfg: Config, target_date: str | None = None, force: bool = False) -> list[str]:
    """Retrieves or builds the category-wise daily brief."""
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

    candidates = collect_daily_feed_candidates()
    if not candidates:
        return ["⚠️ <i>Could not retrieve live news feeds right now. Check internet connectivity.</i>"]

    model = cfg.model if cfg.provider == "gemini" else "gemini-2.5-flash"
    api_key = cfg.api_key or os.getenv("GEMINI_API_KEY", "")

    curated = curate_with_gemini(candidates, api_key=api_key, model=model)
    if curated:
        cache_file.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")

    return format_for_telegram(curated, day)
