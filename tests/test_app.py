"""Tests for PaperFinder. OpenAlex is replaced by fake answers, so the tests run offline and never use the real API."""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as paperfinder #noqa: E402
import openalex # noqa: E402

SAMPLE_WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1000/example",
    "display_name": "Mobile money and household savings in Rwanda",
    "publication_year": 2021,
    "type": "article",
    "cited_by_count": 42,
    "authorships": [
        {"author": {"display_name": "A. Uwase"}},
        {"author": {"display_name": "B. Mugisha"}},
        {"author": {"display_name": "C. Keza"}},
        {"author": {"display_name": "D. Habimana"}},
        {"author": {"display_name": "E. Ingabire"}},
    ],
    "primary_location": {
        "source": {"display_name": "Journal of African Economies"},
        "landing_page_url": "https://example.org/paper",
    },
    "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
    "open_access": {"is_oa": True, "oa_url": "https://example.org/oa"},
    "primary_topic": {"display_name": "Mobile Money and Financial Inclusion"},
    "abstract_inverted_index": {"Mobile": [0], "money": [1], "helps": [2], "savings.": [3]},
}


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    
    def json(self):
        if self._data is None:
            raise ValueError("no JSON")
        return self._data


@pytest.fixture
def calls(monkeypatch):
    """Replace requests.get with a fake and record every call."""
    recorded = {"count": 0, "params": None, "answer": FakeResponse(200, {"meta": {"count": 45}, "results": [SAMPLE_WORK]})}


    def fake_get(url, params=None, timeout=None, headers=None):
        recorded["count"] += 1
        recorded["params"] = params
        answer = recorded["answer"]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(openalex.requests, "get", fake_get)
    paperfinder.client.cache.clear()
    return recorded


@pytest.fixture
def web():
    return paperfinder.app.test_client()


def test_rebuild_abstract_puts_words_in_order():
    index = {"world":[1], "Hello": [0], "again": [3], "hello": [2]}
    assert openalex.rebuild_abstract(index) == "Hello world hello again"
    assert openalex.rebuild_abstract(None) is None


def test_simplify_work_picks_free_pdf_and_trims_authors():
    work = openalex.simplify_work(SAMPLE_WORK)
    assert work["title"] == SAMPLE_WORK["display_name"]
    assert work["free_url"] == "https://example.org/paper.pdf"
    assert work["free_is_pdf"] is True
    assert work["authors"] == ["A. Uwase", "B. Mugisha", "C. Keza", "D. Habimana"]
    assert work["more_authors"] == 1
    assert work["venue"] == "Journal of African Economies"
    assert work["abstract"] == "Mobile money helps savings."


def test_simplify_work_handles_missing_data():
    work = openalex.simplify_work({"id": "W1"})
    assert work["title"] == "Untitled"
    assert work["authors"] == []
    assert work["is_free"] is False
    assert work["free_url"] is None
    assert work["venue"] is None


def test_search_returns_simplified_results(web, calls):
    reply = web.get("/api/search?q=mobile money&sort=citations&from=2015&to=2024&type=article")
    assert reply.status_code == 200
    body = reply.get_json()
    assert body["total"] == 45
    assert body["pages"] == 3
    assert body["results"][0]["citations"] == 42
    assert body["served_by"]
    sent = calls["params"]
    assert sent["search"] == "mobile money"
    assert sent["sort"] == "cited_by_count:desc"
    assert sent["filter"] == ("is_oa:true,publication_year:2015-2024,type:article")


def test_free_only_can_be_switched_off(web, calls):
    web.get("/api/search?q=inflation&free=0")
    assert "filter" not in calls["params"]


def test_single_year_bound(web, calls):
    web.get("/api/search?q=inflation&from=2020")
    assert "publication_year:>2019" in calls["params"]["filter"]


def test_same_search_twice_uses_cache(web, calls):
    first = web.get("/api/search?q=climate finance").get_json()
    second = web.get("/api/search?q=climate finance").get_json()
    assert calls["count"] == 1
    assert first["cached"] is False
    assert second["cached"] is True




@pytest.mark.parametrize("url, message", [
    ("/api/search?q=a", "at least 2"),
    ("/api/search?q=" + "x" * 201, "under 200"),
    ("/api/search?q=tax&sort=random", "sort"),
    ("/api/search?q=tax&type=poem", "type"),
    ("/api/search?q=tax&from=abc", "numbers"),
    ("/api/search?q=tax&from=1800", "between"),
    ("/api/search?q=tax&from=2022&to=2010", "before"),
    ("/api/search?q=tax&page=0", "Page"),
])
def test_bad_input_gets_clear_400(web, calls, url, message):
    reply = web.get(url)
    assert reply.status_code == 400
    assert message in reply.get_json()["error"]
    assert calls["count"] == 0


@pytest.mark.parametrize("answer, status, message", [
    (FakeResponse(429, {}), 503, "Too many searches"),
    (FakeResponse(403, {}), 502, "API key"),
    (FakeResponse(500, {}), 502, "status 500"),
    (FakeResponse(200, None), 502, "couldn't read"),
    (requests.Timeout(), 504, "too long"),
    (requests.ConnectionError(), 502, "Couldn't reach"),
])
def test_openalex_problems_become_friendly_errors(web, calls, answer, status,
                                                  message):
    calls["answer"] = answer
    reply = web.get("/api/search?q=poverty")
    assert reply.status_code == status
    assert message in reply.get_json()["error"]




def test_api_key_is_sent_but_not_cached_or_returned(web, calls, monkeypatch):
    monkeypatch.setattr(paperfinder.client, "api_key", "secret-key")
    body = web.get("/api/search?q=trade").get_json()
    assert calls["params"]["api_key"] == "secret-key"
    assert "secret-key" not in str(body)


def test_health_and_security_headers(web):
    reply = web.get("/api/health")
    assert reply.get_json()["status"] == "ok"
    assert "default-src 'self'" in reply.headers["Content-Security-Policy"]
    assert reply.headers["X-Content-Type-Options"] == "nosniff"


def test_home_page_and_unknown_api_route(web):
    assert web.get("/").status_code == 200
    assert web.get("/api/nope").get_json()["error"]