"""F16 rule & policy Q&A: Vertex AI Search (parsing), local fallback, citations under the honest answer."""
import asyncio

from conftest import REPO, H
from helpers import ready_india_case, sse

from app.agents import copilot
from app.knowledge import search
from app.knowledge.search import LocalSearch, VertexSearch


def test_local_search_finds_official_sources_per_country():
    s = LocalSearch(REPO / "knowledge")
    hits = s.search("compensation 85% report bank 1930 NCRP within 5 calendar days", "IN")
    assert hits and all(h["url"].startswith("https://") for h in hits)
    assert any("RBI" in h["title"] for h in hits)
    my = s.search("997 police report NSRC freeze", "MY")
    assert my and "997" in my[0]["title"]
    assert s.search("weather forecast cricket score", "IN") == []  # below the relevance threshold


def test_vertex_search_response_parsing(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"document": {"structData": {"title": "MY doc", "url": "https://my.example", "country": "MY"}}},
                {"document": {"structData": {"title": "RBI rules", "url": "https://rbi.example", "country": "IN", "publisher": "RBI"},
                              "derivedStructData": {"snippets": [{"snippet": "report within <b>5 days</b>"}]}}},
                {"document": {"structData": {"title": "dup", "url": "https://rbi.example", "country": "IN"}}},
            ]}

    class Session:
        def post(self, url, json, timeout):
            assert url.endswith("/servingConfigs/default_search:search") and json["relevanceThreshold"]
            assert json["contentSearchSpec"]["snippetSpec"]["returnSnippet"] is True
            return Resp()

    v = VertexSearch.__new__(VertexSearch)
    v.session, v.relevance = Session(), "LOW"
    v.serving_config = "projects/p/locations/global/collections/default_collection/engines/e/servingConfigs/default_search"
    hits = v.search("compensation", "IN")
    assert hits == [{"title": "RBI rules", "url": "https://rbi.example", "publisher": "RBI", "snippet": "report within 5 days"}]


def test_honest_answer_cites_an_official_source_without_invented_numbers(client):
    cid = ready_india_case(client)
    ev = sse(client, cid, {"text": "Will I definitely get my money back?"})
    msg = next(e for e in ev if e.get("type") == "done")["message"]
    assert "वादा नहीं" in msg["text"] and "25,000" in msg["text"]
    assert msg["sources"] and msg["sources"][0]["url"].startswith("https://")
    assert "50,000" not in msg["text"]  # a number that only appears in a search snippet never reaches the user
    stored = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    assert any(m.get("sources") for m in stored)


def test_snippet_numbers_are_not_post_check_verified(client):
    cid = ready_india_case(client)
    tb = copilot.Toolbox(cid)
    r = asyncio.run(tb.explain_rule("compensation"))
    assert r["text"] and r["sources"]
    assert all("sources" not in x for x in tb.results)  # only the playbook text feeds allowed_values
    assert tb.sources and set(tb.sources[0]) == {"title", "url", "publisher"}


def test_no_search_backend_falls_back_to_playbook_text(client):
    cid = ready_india_case(client)
    search.set_searcher(None)
    try:
        ev = sse(client, cid, {"text": "Will I definitely get my money back?"})
        msg = next(e for e in ev if e.get("type") == "done")["message"]
        assert "25,000" in msg["text"] and not msg.get("sources")
    finally:
        search._resolved = False
