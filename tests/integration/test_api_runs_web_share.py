"""The run page's AI-search share: how much of what a run delivered came from the AI web search (#152)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shortlist.server.db.models import Run, RunUser, User

pytestmark = pytest.mark.integration


def _pick(title: str, sources: list[str]) -> dict:
    return {"rank": 1, "title": title, "tmdb_id": 1, "media_type": "movie", "sources": sources}


def _run(client: TestClient, breakdown: list[dict], **user_fields) -> int:
    with client.app.state.sessions() as session:
        user_id = session.query(User).first().id
        run = Run(trigger="manual", status="ok")
        session.add(run)
        session.flush()
        session.add(RunUser(run_id=run.id, user_id=user_id, status="ok", breakdown=breakdown, **user_fields))
        session.commit()
        return run.id


def _entry(slug: str, *picks: dict) -> dict:
    return {"row_slug": slug, "row_title": slug, "library_key": "1", "picks": list(picks)}


def test_the_share_counts_picks_from_the_ai_search_for_the_default_row_and_for_all_rows(client: TestClient):
    run_id = _run(
        client,
        [
            _entry("picked", _pick("A", ["llm_web", "tmdb_similar"]), _pick("B", ["tmdb_similar"])),
            _entry("because", _pick("C", ["tmdb_similar"]), _pick("D", ["tmdb_similar"])),
        ],
        llm_tokens_by_step={"llm_web": 900},
    )
    assert client.get(f"/api/runs/{run_id}").json()["web_share"] == {"picked": 0.5, "all": 0.25}


def test_a_run_with_no_default_row_picks_has_no_picked_share(client: TestClient):
    run_id = _run(
        client,
        [_entry("because", _pick("C", ["llm_web"]), _pick("D", ["tmdb_similar"]))],
        llm_tokens_by_step={"llm_web": 9},
    )
    assert client.get(f"/api/runs/{run_id}").json()["web_share"] == {"picked": None, "all": 0.5}


def test_a_run_that_never_used_the_ai_search_has_no_share(client: TestClient):
    run_id = _run(client, [_entry("picked", _pick("A", ["tmdb_similar"]))])
    assert client.get(f"/api/runs/{run_id}").json()["web_share"] is None


def test_exa_searches_alone_mean_the_ai_search_ran(client: TestClient):
    run_id = _run(client, [_entry("picked", _pick("A", ["tmdb_similar"]))], exa_searches=3)
    assert client.get(f"/api/runs/{run_id}").json()["web_share"] == {"picked": 0.0, "all": 0.0}


def test_a_run_with_no_picks_has_no_share_to_report(client: TestClient):
    run_id = _run(client, [], llm_tokens_by_step={"llm_web": 9})
    assert client.get(f"/api/runs/{run_id}").json()["web_share"] == {"picked": None, "all": None}
