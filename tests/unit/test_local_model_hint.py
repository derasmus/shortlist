"""A local model answering in prose is usually Ollama truncating the prompt's start (#152).

Measured 2026-10-11, Ollama 0.40.2: its default context is 2-4k tokens, the OpenAI-compatible API
cannot raise it per request, and the AI web-search prompts are 3-5k, so the system instructions were
dropped and the model replied in prose. Fixtures are real Ollama 0.40.2 responses.
"""

import json
from pathlib import Path

import httpx
import respx
from loguru import logger

from shortlist.engine.candidates import GatherStats, gather_candidates
from shortlist.engine.clients.search import TitleCandidate
from shortlist.engine.curator.openai_compatible import OpenAICompatibleCurator, ollama_context_warning
from tests.unit.test_candidates import _FakeExtractingSearch, _NonNativeCurator, make_result, seed, web_profile

FIXTURES = Path(__file__).parent.parent / "fixtures"
ROOT = "http://ollama.test:11434"


def _gather(curator, stats):
    search = _FakeExtractingSearch([make_result("a", "b")], [TitleCandidate(title="Dune", year=2021, media="movie")])
    return gather_candidates(
        _tmdb(),
        [seed(1, "Arrival")],
        sources=["llm_web"],
        curator=curator,
        profile=web_profile(),
        search=search,
        web_search_mode="exa",
        stats=stats,
    )


def _tmdb():
    from unittest.mock import MagicMock

    tmdb = MagicMock()
    tmdb.suggestions.return_value = []
    tmdb.genre_names.return_value = {}
    tmdb.search.return_value = {"id": 5, "title": "Dune", "genre_ids": [], "vote_average": 8.0}
    return tmdb


class _LocalCurator(_NonNativeCurator):
    name = "openai_compatible"


def _run(curator):
    seen: list[str] = []
    sink = logger.add(seen.append, level="WARNING")
    stats = GatherStats()
    try:
        _gather(curator, stats)
    finally:
        logger.remove(sink)
    return stats.trace["web"], "".join(seen)


def test_a_local_model_answering_in_prose_gets_the_context_hint():
    curator = _LocalCurator("Sure! Here are some films you might enjoy.")
    trace, log = _run(curator)
    assert "OLLAMA_CONTEXT_LENGTH=16384" in trace["hint"]
    assert "tokens" in trace["hint"]
    assert "OLLAMA_CONTEXT_LENGTH=16384" in log
    assert curator.last_system[:60] not in log and curator.last_user[:60] not in log  # never the prompt


def test_a_hosted_provider_gets_no_hint():
    trace, _ = _run(_NonNativeCurator("Sure! Here are some films you might enjoy."))
    assert "hint" not in trace


def test_a_local_model_that_answered_properly_gets_no_hint():
    trace, _ = _run(_LocalCurator('[{"title": "Dune", "year": 2021, "media": "movie"}]'))
    assert "hint" not in trace


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
def test_ollama_context_below_the_minimum_warns():
    ps = _fixture("ollama_api_ps.json")
    ps["models"][0]["context_length"] = 4096
    respx.get(f"{ROOT}/api/version").respond(json=_fixture("ollama_api_version.json"))
    respx.get(f"{ROOT}/api/ps").respond(json=ps)
    warning = ollama_context_warning(f"{ROOT}/v1", ps["models"][0]["name"])
    assert warning is not None
    assert "4,096" in warning and "OLLAMA_CONTEXT_LENGTH=16384" in warning


@respx.mock
def test_ollama_context_at_the_recorded_16384_adds_nothing():
    ps = _fixture("ollama_api_ps.json")
    respx.get(f"{ROOT}/api/version").respond(json=_fixture("ollama_api_version.json"))
    respx.get(f"{ROOT}/api/ps").respond(json=ps)
    assert ollama_context_warning(f"{ROOT}/v1", ps["models"][0]["name"]) is None


@respx.mock
def test_a_model_not_loaded_adds_nothing():
    respx.get(f"{ROOT}/api/version").respond(json=_fixture("ollama_api_version.json"))
    respx.get(f"{ROOT}/api/ps").respond(json={"models": []})
    assert ollama_context_warning(f"{ROOT}/v1", "llama3.1:8b") is None


@respx.mock
def test_not_ollama_or_unreachable_adds_nothing():
    respx.get(f"{ROOT}/api/version").respond(404)
    assert ollama_context_warning(f"{ROOT}/v1", "m") is None
    respx.get(f"{ROOT}/api/version").mock(side_effect=httpx.ConnectError("down"))
    assert ollama_context_warning(f"{ROOT}/v1", "m") is None


@respx.mock
def test_ping_appends_the_warning():
    ps = _fixture("ollama_api_ps.json")
    ps["models"][0]["context_length"] = 2048
    respx.get(f"{ROOT}/v1/models").respond(json={"object": "list", "data": [{"id": "llama3.1:8b", "object": "model"}]})
    respx.get(f"{ROOT}/api/version").respond(json=_fixture("ollama_api_version.json"))
    respx.get(f"{ROOT}/api/ps").respond(json=ps)
    result = OpenAICompatibleCurator(f"{ROOT}/v1", model="llama3.1:8b").ping()
    assert result.startswith("connected — 1 model(s) available")
    assert "2,048" in result
