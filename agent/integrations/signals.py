"""
agent/integrations/signals.py — unified news/headline signal source

Pulls headlines from a small set of verified RSS feeds plus GDELT.
Stdlib XML parsing (no feedparser dependency). Each source is fetched
concurrently, fails open, and individual 403s are tolerated.

Provides:
  fetch_headlines() -> list[dict]   — flat list of {title, url, source}
"""

import asyncio
import logging
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

RSS_FEEDS = [
    {
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
        "timeout": 8.0,
    },
    {
        "name": "Bitcoin.com",
        "url": "https://news.bitcoin.com/feed",
        "timeout": 8.0,
    },
    {
        "name": "Crypto.news",
        "url": "https://crypto.news/feed",
        "timeout": 8.0,
    },
    {
        "name": "CryptoPanic",
        "url": "https://cryptopanic.com/news/rss/",
        "timeout": 8.0,
    },
    # General + geopolitics coverage — gives non-crypto markets (Iran, macro,
    # elections) real headlines to cite instead of forcing the generator to
    # invent unverifiable facts.
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "timeout": 8.0,
    },
    {
        "name": "BBC Middle East",
        "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
        "timeout": 8.0,
    },
    {
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "timeout": 8.0,
    },
    {
        "name": "Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "timeout": 8.0,
    },
    {
        "name": "NPR World",
        "url": "https://feeds.npr.org/1004/rss.xml",
        "timeout": 8.0,
    },
]

GDELT_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=bitcoin+federal+reserve+iran+geopolitics+prediction"
    "&mode=ArtList&maxrecords=10&format=json"
)


def _parse_rss(xml_text: str, source_name: str) -> list[dict]:
    """Parse RSS 2.0 or Atom XML into list of headline dicts."""
    headlines = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0: items under channel
        items = root.findall(".//item")
        # Atom fallback: entries
        if not items:
            items = root.findall(".//atom:entry", ns)

        for item in items[:15]:
            # Title
            title_el = item.find("title")
            if title_el is None:
                title_el = item.find("atom:title", ns)
            title = ""
            if title_el is not None:
                title = (title_el.text or "").strip()
                # Strip CDATA if present
                title = title.replace("<![CDATA[", "").replace("]]>", "").strip()

            # Link
            link = ""
            link_el = item.find("link")
            if link_el is not None:
                link = (link_el.text or link_el.get("href", "")).strip()
            if not link:
                atom_link = item.find("atom:link", ns)
                if atom_link is not None:
                    link = atom_link.get("href", "").strip()

            if title and len(title) > 5:
                headlines.append({
                    "title": title,
                    "url": link,
                    "source": source_name,
                })
    except ET.ParseError as e:
        log.debug(f"[Signals] RSS parse error for {source_name}: {e}")
    except Exception as e:
        log.debug(f"[Signals] Unexpected parse error for {source_name}: {e}")
    return headlines


async def _fetch_rss(feed: dict) -> list[dict]:
    """Fetch and parse one RSS feed. Returns empty list on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=feed["timeout"],
            follow_redirects=True,
        ) as client:
            r = await client.get(
                feed["url"],
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code == 200:
                headlines = _parse_rss(r.text, feed["name"])
                log.debug(f"[Signals] {feed['name']}: {len(headlines)} headlines")
                return headlines
            log.debug(f"[Signals] {feed['name']} returned {r.status_code} — skipping")
    except Exception as e:
        log.debug(f"[Signals] {feed['name']} failed: {e}")
    return []


async def _fetch_gdelt() -> list[dict]:
    """Fetch GDELT articles matching the Polymarket-relevant query."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(GDELT_URL, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                log.debug(f"[Signals] GDELT returned {r.status_code} — skipping")
                return []
            try:
                data = r.json()
            except Exception:
                return []
            articles = data.get("articles", []) or []
            out = []
            for a in articles[:10]:
                title = (a.get("title", "") or "").strip()
                if title and len(title) > 5:
                    out.append({
                        "title": title,
                        "url": a.get("url", ""),
                        "source": "GDELT",
                    })
            log.debug(f"[Signals] GDELT: {len(out)} headlines")
            return out
    except Exception as e:
        log.debug(f"[Signals] GDELT failed: {e}")
        return []


async def fetch_headlines() -> list[dict]:
    """Concurrently fetch all signal sources; return flat headline list."""
    tasks = [_fetch_rss(f) for f in RSS_FEEDS] + [_fetch_gdelt()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    headlines: list[dict] = []
    for res in results:
        if isinstance(res, list):
            headlines.extend(res)
    log.info(
        f"[Signals] {len(headlines)} headlines from "
        f"{len({h['source'] for h in headlines})} sources"
    )
    return headlines
