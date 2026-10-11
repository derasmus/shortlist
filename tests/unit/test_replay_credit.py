"""The replay ranks one gathered pool twice, with the AI-search credit on and off (#152)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from shortlist.engine.clients.search import SearchResult, TitleCandidate
from shortlist.engine.eval.replay import holdout_cases, replay_case, row_web_share, without_web_credit
from shortlist.engine.models import Candidate, EngineConfig, MediaType, Seed, UserProfile, UserType, WatchedItem

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def watched(title, days_ago, tmdb_id, *, plays=1) -> WatchedItem:
    return WatchedItem(
        title=title,
        media_type=MediaType.MOVIE,
        watched_at=NOW - timedelta(days=days_ago),
        tmdb_id=tmdb_id,
        watch_count=plays,
    )


@pytest.fixture
def user() -> UserProfile:
    return UserProfile(username="mike", plex_account_id=202, user_type=UserType.SHARED)


class _Search:
    """Exa-shaped: the titles extracted depend on which watched title the query is about."""

    name = "exa"
    results_per_query = 10

    def __init__(self, by_watched):
        self._by_watched = by_watched

    def search(self, query, *, num_results=8):
        return [SearchResult(title="An article", url="https://example.com", text="body")]

    def search_detailed(self, query, *, num_results=8):
        for watched_title, titles in self._by_watched.items():
            if watched_title in query:
                return self.search(query), [TitleCandidate(title=t, year=2025, media="movie") for t in titles]
        return self.search(query), []


class _NoAi:
    supports_native_web_search = False
    can_complete = False
    last_tokens = 0
    last_output_tokens = 0


WEB_IDS = {"Target": 999, "Web B": 998, "Web C": 997}


def _tmdb():
    """Each seed suggests one decently rated title of its own, so a seedless web title is crowded out."""
    tmdb = SimpleNamespace()
    tmdb.suggestions = lambda tid, mt: [
        ({"id": 5000 + tid, "title": f"Similar {tid}", "genre_ids": [], "vote_average": 7.0}, 0.8)
    ]
    tmdb.genre_names = lambda mt: {}
    tmdb.genre_ids_for = lambda tid, mt: []
    tmdb.search = lambda title, mt, year=None: (
        {"id": WEB_IDS[title], "title": title, "genre_ids": [], "vote_average": 8.0} if title in WEB_IDS else None
    )
    return tmdb


def _library():
    ids = {5000 + 200 + i: 1 for i in range(8)} | {5000 + 300 + i: 1 for i in range(8)}
    ids |= {999: 1, 998: 1, 997: 1}
    return {MediaType.MOVIE: ids, MediaType.SHOW: {}}


def _replay(user, search, *, credit=True, older_count=0, row_size=3, recent=4, modes=()):
    history = [watched(f"Earlier {i}", i + 1, 200 + i) for i in range(12)]
    history += [watched(f"Old {i}", 300 + i, 300 + i) for i in range(6)]
    case = holdout_cases(user, [watched("Held", 0, 1), *history])[0]
    config = EngineConfig(
        row_size=row_size,
        candidates_pre_rank=20,
        max_seeds=recent,
        recent_count=recent,
        candidate_sources=["tmdb_similar", "llm_web"],
        web_search_provider="exa",
        older_count=older_count,
        credit_web_titles=credit,
    )
    return replay_case(
        case,
        config,
        config_label="x",
        tmdb=_tmdb(),
        library_index=_library(),
        resolve_tmdb_id=lambda item: item.tmdb_id,
        curator=_NoAi(),
        search=search,
        modes=modes,
    )


def test_without_credit_a_web_title_is_crowded_out_and_with_it_the_title_leads(user):
    outcome = _replay(user, _Search({"Earlier": ["Target"]}))
    assert outcome.in_final_row_uncredited is False
    assert [t.tmdb_id for t in outcome.final_row if t.from_web] == [999]
    assert [t.tmdb_id for t in outcome.final_row_uncredited if t.from_web] == []


def test_the_uncredited_ranking_is_the_ranking_of_a_pool_gathered_with_credit_off(user):
    search = _Search({"Earlier": ["Target", "Web B"]})
    on = _replay(user, search, credit=True)
    off = _replay(user, search, credit=False)
    assert on.rank_uncredited == off.rank
    assert on.final_row_uncredited == off.final_row
    assert off.final_row_uncredited == off.final_row


def test_a_title_only_an_older_watchs_search_found_is_counted_as_from_history(user):
    search = _Search({"Earlier": ["Target"], "Old": ["Web B"]})
    outcome = _replay(user, search, older_count=2, row_size=6)
    by_id = {t.tmdb_id: t for t in outcome.final_row}
    assert by_id[999].from_web and not by_id[999].via_history
    assert by_id[998].from_web and by_id[998].via_history


def test_row_web_share_counts_titles_from_the_search_with_credit_on_and_off(user):
    search = _Search({"Earlier": ["Target"], "Old": ["Web B"]})
    outcome = _replay(user, search, older_count=2, row_size=6)
    on = row_web_share([outcome], credited=True)
    off = row_web_share([outcome], credited=False)
    assert on.titles == len(outcome.final_row) and on.web >= 2 and on.via_history == 1
    assert off.titles == len(outcome.final_row_uncredited) and off.web <= on.web


def test_without_web_credit_strips_only_what_the_search_added():
    kept = Seed(1, "Kept", MediaType.MOVIE)
    added = Seed(2, "Added", MediaType.MOVIE)
    web_only = Candidate(
        tmdb_id=10, title="W", media_type=MediaType.MOVIE, seeds=[added], web_seeds=[added], sources={"llm_web"}
    )
    web_only.affinity = 0.7
    both = Candidate(
        tmdb_id=11,
        title="B",
        media_type=MediaType.MOVIE,
        seeds=[kept, added],
        web_seeds=[added],
        sources={"llm_web", "tmdb_similar"},
        affinity=0.9,
        pre_web_affinity=0.6,
    )
    plain = Candidate(tmdb_id=12, title="P", media_type=MediaType.MOVIE, seeds=[kept], sources={"tmdb_similar"})
    stripped = without_web_credit([web_only, both, plain])
    assert (stripped[0].seeds, stripped[0].web_seeds, stripped[0].affinity) == ([], [], 1.0)
    assert (stripped[1].seeds, stripped[1].affinity) == ([kept], 0.6)
    assert stripped[2] is plain
    assert web_only.seeds == [added], "the gathered pool is left as it was"


def test_the_replay_weighs_history_seeds_like_a_row_does(user, monkeypatch):
    from statistics import median

    from shortlist.engine import history as history_mod
    from shortlist.engine.eval import replay as replay_mod

    seen = {}
    real = replay_mod.history_mix

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(replay_mod, "history_mix", spy)
    _replay(user, _Search({}), older_count=2)
    recent = history_mod.derive_seeds(
        [watched(f"Earlier {i}", i + 1, 200 + i) for i in range(12)]
        + [watched(f"Old {i}", 300 + i, 300 + i) for i in range(6)],
        lambda item: item.tmdb_id,
        max_seeds=4,
    )
    assert seen["seed_weight"] == median(s.weight for s in recent)


def _gathered(credit):
    from shortlist.engine.candidates import GatherStats, gather_candidates
    from tests.unit.test_candidates_favourites import _Cache

    tmdb = _tmdb()
    similar = {
        200: [({"id": 999, "title": "Target", "genre_ids": [], "vote_average": 8.0}, 0.8)],
        201: [({"id": 5201, "title": "Similar 201", "genre_ids": [], "vote_average": 7.0}, 0.6)],
    }
    tmdb.suggestions = lambda tid, mt: similar.get(tid, [])
    return gather_candidates(
        tmdb,
        [Seed(200, "Earlier 0", MediaType.MOVIE), Seed(201, "Earlier 1", MediaType.MOVIE)],
        sources=["tmdb_similar", "llm_web"],
        curator=_NoAi(),
        profile=SimpleNamespace(history=[]),
        search=_Search({"Earlier 1": ["Target", "Web B"]}),
        web_search_mode="exa",
        web_search_cache=_Cache(),
        stats=GatherStats(),
        credit_web_titles=credit,
    )


def test_without_web_credit_gives_the_pool_a_credit_off_gather_would_have_made():
    def shape(pool):
        return sorted((c.tmdb_id, c.affinity, [s.tmdb_id for s in c.seeds]) for c in pool)

    credited = _gathered(True)
    assert shape(credited) != shape(_gathered(False)), "the credit must change something for this to mean anything"
    assert shape(without_web_credit(credited)) == shape(_gathered(False))


def test_every_mode_is_ranked_from_the_one_gathered_pool(user):
    from shortlist.engine.ranking import WEB_CREDIT_MODES

    search = _Search({"Earlier": ["Target", "Web B"]})
    outcome = _replay(user, search, modes=WEB_CREDIT_MODES)
    assert set(outcome.by_mode) == set(WEB_CREDIT_MODES)
    assert outcome.by_mode["off"].row == outcome.final_row_uncredited
    assert outcome.by_mode["off"].rank == outcome.rank_uncredited
    assert outcome.by_mode["full"].row == outcome.final_row
    assert outcome.by_mode["full"].in_row == outcome.in_final_row
