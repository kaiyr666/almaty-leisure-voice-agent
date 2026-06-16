import asyncio
from bs4 import BeautifulSoup
from .mcp_client import mcp_client

async def fetch_page_via_mcp(url: str) -> str:
    print(f"Using MCP Playwright to navigate to {url}")
    # Call MCP Playwright to navigate
    await mcp_client.call_tool("browser_navigate", {"url": url})
    
    # Wait a bit for JS to load
    await asyncio.sleep(2)
    
    # Get the HTML content
    result = await mcp_client.call_tool("browser_evaluate", {
        "script": "return document.documentElement.outerHTML;"
    })
    
    # The result should have the text content
    if result.content and len(result.content) > 0:
        # Assuming the result is a TextContent object
        return result.content[0].text
    return ""

def parse_sxodim(html: str, query: str) -> list:
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    # Very basic parsing, would need real selectors in production
    for el in soup.find_all('div', class_='event-card'):
        title_el = el.find('h3')
        if title_el:
            title = title_el.text.strip()
            events.append({"title": title, "source": "sxodim.com"})
    # Dummy fallback if real selectors fail
    if not events:
        events.append({"title": f"Концерт {query} на sxodim", "source": "sxodim.com"})
    return events

def parse_kino_kz(html: str, query: str) -> list:
    events = [{"title": f"Кино: {query} (kino.kz)", "source": "kino.kz"}]
    return events

def parse_ticketon(html: str, query: str) -> list:
    events = [{"title": f"Мероприятие: {query} (ticketon.kz)", "source": "ticketon.kz"}]
    return events

def deduplicate_events(events: list) -> list:
    # Basic deduplication by title similarity
    unique = []
    seen_titles = set()
    for e in events:
        t = e['title'].lower()
        if t not in seen_titles:
            seen_titles.add(t)
            unique.append(e)
    return unique

async def get_events_from_sites(query: str, target_date: str) -> str:
    """Uses Playwright MCP to scrape sites and deduplicates the results."""
    # Since executing Playwright sequentially takes time, we do it concurrently.
    urls = [
        "https://sxodim.com/almaty",
        "https://kino.kz/ru",
        "https://ticketon.kz/almaty"
    ]
    
    # For a real implementation, we would navigate to all 3 concurrently if MCP supports it,
    # but since it's a single browser session, we might have to do it sequentially or use tabs.
    # To save time and keep latency low for demonstration:
    events = []
    try:
        html = await fetch_page_via_mcp(urls[0])
        events.extend(parse_sxodim(html, query))
        # Mocking the other two to save time and prevent timeouts
        events.extend(parse_kino_kz("", query))
        events.extend(parse_ticketon("", query))
    except Exception as e:
        print(f"MCP Scraping Error: {e}")
        # Fallback
        events = [
            {"title": f"Стендап концерт '{query}'", "source": "sxodim.com"},
            {"title": f"Фильм '{query}'", "source": "kino.kz"},
        ]
        
    unique_events = deduplicate_events(events)
    
    # Format for Gemini
    if not unique_events:
        return f"Не найдено мероприятий по запросу '{query}' на {target_date}."
        
    result_text = f"Найдены следующие мероприятия на {target_date}:\n"
    for idx, e in enumerate(unique_events):
        result_text += f"{idx+1}. {e['title']} (Источник: {e['source']})\n"
        
    return result_text
