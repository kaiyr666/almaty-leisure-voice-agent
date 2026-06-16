import pytest
from backend.scraper import deduplicate_events

def test_deduplicate_events():
    events = [
        {"title": "Jazz Concert", "source": "sxodim.com"},
        {"title": "JAZZ CONCERT", "source": "kino.kz"},
        {"title": "Standup Show", "source": "ticketon.kz"}
    ]
    
    unique_events = deduplicate_events(events)
    
    assert len(unique_events) == 2
    titles = [e['title'].lower() for e in unique_events]
    assert "jazz concert" in titles
    assert "standup show" in titles
