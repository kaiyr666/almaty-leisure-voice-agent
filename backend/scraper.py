import os
import asyncio
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from .mcp_client import mcp_client
from .logger import get_logger

load_dotenv()

log = get_logger("scraper")

# Configurable via .env — change TARGET_URL to point at any events website
TARGET_URL = os.environ.get("TARGET_URL", "https://sxodim.com/almaty")


async def fetch_page_via_mcp(url: str) -> str:
    log.info("Navigating MCP Playwright to: %s", url)
    await mcp_client.call_tool("browser_navigate", {"url": url})

    log.debug("Waiting 3s for page JS to render...")
    await asyncio.sleep(3)

    result = await mcp_client.call_tool(
        "browser_evaluate", {"function": "() => document.documentElement.outerHTML"}
    )

    if result.content and len(result.content) > 0:
        html = result.content[0].text
        log.info("Fetched %d chars of HTML from %s", len(html), url)
        return html

    log.warning("MCP returned empty content from %s", url)
    return ""


def parse_sxodim(html: str, query: str) -> list:
    log.debug("Parsing HTML (%d chars) for query='%s'", len(html), query)
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # Log a snippet of the actual HTML to help diagnose selector mismatches
    text_preview = soup.get_text(separator=" ", strip=True)[:500]
    log.debug("Page text preview: %s", text_preview)

    # Try progressively broader card selectors
    card_selectors = [
        ".impression-card", ".event-card", ".card",
        "[class*='impression']", "[class*='event-item']",
        "article", "[class*='afisha']", "[class*='event']",
    ]
    for selector in card_selectors:
        cards = soup.select(selector)
        if cards:
            log.debug("Selector '%s' matched %d elements", selector, len(cards))
            break
    else:
        cards = []
        log.debug("No card selectors matched")

    for card in cards:
        title_el = (
            card.select_one("[class*='title']")
            or card.select_one("h2")
            or card.select_one("h3")
            or card.select_one("h4")
        )
        if title_el:
            title_text = title_el.text.strip()
            if len(title_text) > 3:
                events.append({"title": title_text, "source": TARGET_URL})

    if not events:
        log.debug("No card results — trying broad link/heading fallback")
        # Collect all links and headings that look like event titles
        candidates = (
            soup.select("a[href*='/event']")
            + soup.select("a[href*='/afisha']")
            + soup.select("h2")
            + soup.select("h3")
        )
        for el in candidates:
            title_text = el.text.strip()
            if len(title_text) > 5:
                events.append({"title": title_text, "source": TARGET_URL})
        if events:
            log.debug("Broad fallback found %d candidates", len(events))

    if not events:
        # Log enough HTML for selector debugging
        log.warning(
            "All selectors failed for query='%s'. HTML snippet:\n%s",
            query,
            html[:3000],
        )
    else:
        log.info("Parsed %d events for query='%s'", len(events), query)

    return events


def deduplicate_events(events: list) -> list:
    unique = []
    seen = set()
    for e in events:
        key = e["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(e)
    removed = len(events) - len(unique)
    if removed:
        log.debug("Deduplication removed %d duplicate events", removed)
    return unique


async def get_events_from_sites(query: str, target_date: str) -> str:
    log.info("get_events_from_sites: query='%s', date='%s', url=%s", query, target_date, TARGET_URL)
    events = []

    try:
        html = await fetch_page_via_mcp(TARGET_URL)
        if html:
            events = parse_sxodim(html, query)
    except Exception as e:
        log.error("Scraping pipeline failed: %s", e, exc_info=True)

    unique_events = deduplicate_events(events)

    if not unique_events:
        log.warning("No events found after dedup for query='%s'", query)
        return f"No events found for '{query}' on {TARGET_URL}."

    result_text = f"Events found on {TARGET_URL} for '{query}' ({target_date}):\n"
    for idx, e in enumerate(unique_events[:5]):
        result_text += f"{idx + 1}. {e['title']}\n"

    log.info("Returning %d events for query='%s'", min(len(unique_events), 5), query)
    return result_text
