"""AI web-search titles credited to the watches that found them (#152)."""

import json
from types import SimpleNamespace

from shortlist.engine.candidates import GatherStats, gather_candidates
from shortlist.engine.clients.search import SearchResult, TitleCandidate
from shortlist.engine.curator.base import build_web_pick_prompt, build_web_prompt, build_web_rag_prompt
from shortlist.engine.models import MediaType
from tests.unit.test_candidates_favourites import TASTE, _Cache, _Curator, seed


class _BySeedSearch:
    """Exa-shaped; the extracted titles depend on which watched title the query is about."""

    name = "exa"
    results_per_query = 10

    def __init__(self, by_title):
        self._by_title = by_title

    def search(self, query, *, num_results=8):
        return [SearchResult(title="An article", url="https://example.com", text="body")]

    def search_detailed(self, query, *, num_results=8):
        for watched, titles in self._by_title.items():
            if watched in query:
                return self.search(query), [TitleCandidate(title=t, year=2020, media="movie") for t in titles]
        return self.search(query), []


class _SnippetSearch:
    """SearXNG-shaped: prose snippets per watched title, no extraction."""

    name = "searxng"
    results_per_query = 10

    def __init__(self, by_title):
        self._by_title = by_title

    def search(self, query, *, num_results=8):
        for watched, value in self._by_title.items():
            if watched in query:
                title, text = value if isinstance(value, tuple) else (f"About {watched}", value)
                return [SearchResult(title=title, url=f"https://example.com/{watched}", text=text)]
        return []


class _NativeCurator:
    supports_native_web_search = True

    def __init__(self, recs):
        self.recs = recs
        self.kwargs: dict = {}

    def recommend_web(self, profile, seeds, k, **kwargs):
        self.kwargs = kwargs
        return [dict(r) for r in self.recs]


def _tmdb(mock_tmdb, genres_by_title=None):
    ids = {}
    seed_genres = {1: [18], 10: [18], 20: [35]}
    mock_tmdb.suggestions.side_effect = lambda tid, mt: []
    mock_tmdb.genre_names.return_value = {18: "Drama", 35: "Comedy"}
    mock_tmdb.genre_ids_for.side_effect = lambda tid, mt: seed_genres.get(tid, [])

    def search(title, media_type, year=None):
        n = ids.setdefault(title, 1000 + len(ids))
        return {"id": n, "title": title, "genre_ids": (genres_by_title or {}).get(title, [18]), "vote_average": 7.0}

    mock_tmdb.search.side_effect = search
    return mock_tmdb


def _pick(*titles):
    return json.dumps([{"title": t, "year": 2020, "media": "movie"} for t in titles])


def _gather(mock_tmdb, search, curator, seeds, *, mode="exa", credit=True, genres=None, **kwargs):
    stats = GatherStats()
    pool = gather_candidates(
        _tmdb(mock_tmdb, genres),
        seeds,
        sources=["llm_web"],
        curator=curator,
        profile=SimpleNamespace(history=[]),
        search=search,
        web_search_mode=mode,
        web_search_cache=_Cache(),
        stats=stats,
        credit_web_titles=credit,
        **kwargs,
    )
    return {c.title: c for c in pool}


def test_a_title_found_by_two_searches_is_credited_to_both(mock_tmdb):
    search = _BySeedSearch({"R1": ["Shared", "Only R"], "F1": ["Shared"]})
    pool = _gather(
        mock_tmdb,
        search,
        _Curator(_pick("Shared", "Only R")),
        [seed(1, "R1")],
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert [s.title for s in pool["Shared"].seeds] == ["R1", "F1"]
    assert [s.title for s in pool["Shared"].web_seeds] == ["R1", "F1"]
    assert [s.title for s in pool["Only R"].seeds] == ["R1"]


def test_older_seeds_are_credited_too(mock_tmdb):
    search = _BySeedSearch({"O1": ["Old find"]})
    pool = _gather(
        mock_tmdb,
        search,
        _Curator(_pick("Old find")),
        [seed(1, "R1")],
        older_seeds=[seed(20, "O1")],
        older_count=1,
    )
    assert [s.title for s in pool["Old find"].seeds] == ["O1"]


def test_a_credited_title_takes_the_genre_coherence_a_similar_title_gets(mock_tmdb):
    search = _BySeedSearch({"R1": ["Inside", "Straying"]})
    pool = _gather(
        mock_tmdb,
        search,
        _Curator(_pick("Inside", "Straying")),
        [seed(1, "R1")],
        genres={"Inside": [18], "Straying": [18, 35]},
    )
    assert pool["Inside"].affinity == 1.0
    assert pool["Straying"].affinity == 0.75


def test_a_title_the_model_invented_stays_uncredited(mock_tmdb):
    pool = _gather(mock_tmdb, _BySeedSearch({"R1": ["Silo"]}), _Curator(_pick("Made up")), [seed(1, "R1")])
    assert pool["Made up"].seeds == [] and pool["Made up"].web_seeds == [] and pool["Made up"].affinity == 1.0


def test_exa_without_an_ai_credits_the_seeds_that_found_each_title(mock_tmdb):
    class _NoAi(_Curator):
        can_complete = False

    pool = _gather(mock_tmdb, _BySeedSearch({"R1": ["Silo"]}), _NoAi(), [seed(1, "R1")])
    assert [s.title for s in pool["Silo"].seeds] == ["R1"]


def test_credit_off_leaves_every_web_title_seedless(mock_tmdb):
    search = _BySeedSearch({"R1": ["Silo"]})
    pool = _gather(mock_tmdb, search, _Curator(_pick("Silo")), [seed(1, "R1")], credit=False)
    assert pool["Silo"].seeds == [] and pool["Silo"].web_seeds == [] and pool["Silo"].affinity == 1.0


def test_a_seed_already_on_the_candidate_is_not_added_twice(mock_tmdb):
    mock_tmdb.suggestions.side_effect = None
    search = _BySeedSearch({"R1": ["Silo"]})
    tmdb = _tmdb(mock_tmdb)
    tmdb.suggestions.side_effect = lambda tid, mt: [({"id": 1000, "title": "Silo", "genre_ids": [18]}, 0.5)]
    pool = gather_candidates(
        tmdb,
        [seed(1, "R1")],
        sources=["tmdb_similar", "llm_web"],
        curator=_Curator(_pick("Silo")),
        profile=SimpleNamespace(history=[]),
        search=search,
        web_search_mode="exa",
        web_search_cache=_Cache(),
        credit_web_titles=True,
    )
    silo = next(c for c in pool if c.title == "Silo")
    assert [s.title for s in silo.seeds] == ["R1"] and silo.web_seeds == []


def _snippets():
    return _SnippetSearch(
        {
            "R1": ("Fans of R1 should try Slow Horses, a spy comedy", "Body text."),
            "F1": ("Another one, Dark Waters, is a great film", "Body text."),
        }
    )


def test_rag_credits_the_seed_whose_snippet_names_the_title(mock_tmdb):
    pool = _gather(
        mock_tmdb,
        _snippets(),
        _Curator(_pick("Slow Horses", "Dark Waters")),
        [seed(1, "R1")],
        mode="searxng",
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert [s.title for s in pool["Slow Horses"].seeds] == ["R1"]
    assert [s.title for s in pool["Dark Waters"].seeds] == ["F1"]


def test_rag_snippet_match_is_on_whole_words(mock_tmdb):
    pool = _gather(mock_tmdb, _snippets(), _Curator(_pick("Slow Hors")), [seed(1, "R1")], mode="searxng")
    assert pool["Slow Hors"].seeds == []


def test_rag_falls_back_to_because_when_no_snippet_names_the_title(mock_tmdb):
    reply = json.dumps([{"title": "Elsewhere", "year": 2020, "media": "movie", "because": "f1"}])
    pool = _gather(
        mock_tmdb,
        _snippets(),
        _Curator(reply),
        [seed(1, "R1")],
        mode="searxng",
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert [s.title for s in pool["Elsewhere"].seeds] == ["F1"]


def test_an_unknown_because_is_ignored(mock_tmdb):
    reply = json.dumps([{"title": "Elsewhere", "year": 2020, "media": "movie", "because": "Not Watched"}])
    pool = _gather(mock_tmdb, _snippets(), _Curator(reply), [seed(1, "R1")], mode="searxng")
    assert pool["Elsewhere"].seeds == []


def test_the_rag_prompt_asks_for_because_only_when_crediting(mock_tmdb):
    curator = _Curator(_pick("Slow Horses"))
    _gather(mock_tmdb, _snippets(), curator, [seed(1, "R1")], mode="searxng")
    assert '"because"' in curator.system
    curator = _Curator(_pick("Slow Horses"))
    _gather(mock_tmdb, _snippets(), curator, [seed(1, "R1")], mode="searxng", credit=False)
    assert "because" not in curator.system


def test_the_structured_pick_prompt_never_asks_for_because(mock_tmdb):
    curator = _Curator(_pick("Silo"))
    _gather(mock_tmdb, _BySeedSearch({"R1": ["Silo"]}), curator, [seed(1, "R1")], taste=TASTE)
    assert "because" not in curator.system


def test_the_native_path_credits_a_listed_because(mock_tmdb):
    recs = [
        {"title": "Mentioned", "year": 2020, "media": "movie", "because": "R1"},
        {"title": "Stranger", "year": 2020, "media": "movie", "because": "Never Watched"},
        {"title": "Plain", "year": 2020, "media": "movie"},
    ]
    curator = _NativeCurator(recs)
    pool = _gather(mock_tmdb, None, curator, [seed(1, "R1")], mode="native")
    assert curator.kwargs["because"] is True
    assert [s.title for s in pool["Mentioned"].seeds] == ["R1"]
    assert pool["Stranger"].seeds == [] and pool["Plain"].seeds == []


def test_the_native_path_accepts_a_favourite_as_because(mock_tmdb):
    recs = [{"title": "Mentioned", "year": 2020, "media": "movie", "because": "F1"}]
    pool = _gather(
        mock_tmdb,
        None,
        _NativeCurator(recs),
        [seed(1, "R1")],
        mode="native",
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert [s.title for s in pool["Mentioned"].seeds] == ["F1"]


def test_the_native_path_passes_no_because_when_credit_is_off(mock_tmdb):
    recs = [{"title": "Mentioned", "year": 2020, "media": "movie", "because": "R1"}]
    curator = _NativeCurator(recs)
    pool = _gather(mock_tmdb, None, curator, [seed(1, "R1")], mode="native", credit=False)
    assert "because" not in curator.kwargs
    assert pool["Mentioned"].seeds == []


def test_a_native_curator_that_predates_because_is_still_called_as_before(mock_tmdb):
    class _Old:
        supports_native_web_search = True

        def recommend_web(self, profile, seeds, k, *, guidance=None):
            return [{"title": "Plain", "year": 2020, "media": "movie"}]

    pool = _gather(mock_tmdb, None, _Old(), [seed(1, "R1")], mode="native")
    assert "Plain" in pool


def test_the_prompts_are_unchanged_without_because():
    profile = SimpleNamespace(history=[])
    for build in (build_web_prompt, build_web_rag_prompt):
        args = (profile, [seed(1, "R1")] if build is build_web_prompt else [], 10)
        assert build(*args, year=2026) == build(*args, year=2026, because=False)
        assert "because" not in build(*args, year=2026)[0]
        assert '"because"' in build(*args, year=2026, because=True)[0]
    assert "because" not in build_web_pick_prompt(profile, [], 10, year=2026)[0]


def test_media_type_of_a_credited_show_title(mock_tmdb):
    reply = json.dumps([{"title": "Silo", "year": 2023, "media": "show"}])
    search = SimpleNamespace(
        name="exa",
        results_per_query=10,
        search=lambda q, num_results=8: [],
        search_detailed=lambda q, num_results=8: ([], [TitleCandidate(title="Silo", year=2023, media="show")]),
    )
    pool = _gather(mock_tmdb, search, _Curator(reply), [seed(1, "R1", MediaType.SHOW)])
    assert [s.title for s in pool["Silo"].seeds] == ["R1"]


def test_rag_does_not_credit_a_title_only_named_in_snippet_body_text(mock_tmdb):
    search = _SnippetSearch({"R1": ("An article about R1", "Unrelated, but Slow Horses is mentioned in passing.")})
    pool = _gather(mock_tmdb, search, _Curator(_pick("Slow Horses")), [seed(1, "R1")], mode="searxng")
    assert pool["Slow Horses"].seeds == []


def test_rag_does_not_credit_from_a_snippet_the_model_was_not_shown(mock_tmdb, monkeypatch):
    monkeypatch.setattr("shortlist.engine.candidates._WEB_SEARCH_RAG_CAP", 1)
    search = _SnippetSearch(
        {"R1": ("Nothing to see in R1", "Body."), "F1": ("Try Dark Waters after F1", "Body.")},
    )
    pool = _gather(
        mock_tmdb,
        search,
        _Curator(_pick("Dark Waters")),
        [seed(1, "R1")],
        mode="searxng",
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert pool["Dark Waters"].seeds == []


def test_a_title_found_by_twenty_searches_carries_three_seeds(mock_tmdb):
    watched = [seed(100 + i, f"W{i:02d}") for i in range(20)]
    search = _BySeedSearch({s.title: ["Everywhere"] for s in watched})
    pool = _gather(
        mock_tmdb, search, _Curator(_pick("Everywhere")), watched[:1], favourite_seeds=watched[1:], favourite_count=19
    )
    assert [s.title for s in pool["Everywhere"].seeds] == ["W00", "W01", "W02"]
    assert [s.title for s in pool["Everywhere"].web_seeds] == ["W00", "W01", "W02"]


def _similar_then_web(mock_tmdb, *, similar_genres):
    """A pool where tmdb_similar already found 'Known' (affinity 0.8 x coherence) before the web credits it."""
    _tmdb(mock_tmdb)
    mock_tmdb.suggestions.side_effect = lambda tid, mt: [
        ({"id": 1000, "title": "Known", "genre_ids": similar_genres, "vote_average": 7.0}, 0.8)
    ]
    mock_tmdb.search.side_effect = lambda title, mt, year=None: {
        "id": 1000,
        "title": "Known",
        "genre_ids": [18, 35],
        "vote_average": 7.0,
    }
    return gather_candidates(
        mock_tmdb,
        [seed(1, "R1")],
        sources=["tmdb_similar", "llm_web"],
        curator=_Curator(_pick("Known")),
        profile=SimpleNamespace(history=[]),
        search=_BySeedSearch({"R1": ["Known"]}),
        web_search_mode="exa",
        web_search_cache=_Cache(),
        stats=GatherStats(),
        credit_web_titles=True,
    )


def test_a_title_another_source_found_keeps_its_affinity_and_remembers_it(mock_tmdb):
    (known,) = _similar_then_web(mock_tmdb, similar_genres=[18])
    assert known.affinity == 0.8
    assert known.pre_web_affinity == 0.8


def test_a_title_only_the_web_found_has_no_prior_affinity(mock_tmdb):
    pool = _gather(mock_tmdb, _BySeedSearch({"R1": ["Fresh"]}), _Curator(_pick("Fresh")), [seed(1, "R1")])
    assert pool["Fresh"].pre_web_affinity is None


def test_a_title_discover_also_found_is_priced_like_one_the_web_found_alone(mock_tmdb):
    """Discover claims no affinity, so its neutral 1.0 must not shield a credited title from the coherence."""
    search = _BySeedSearch({"R1": ["Straying"]})
    tmdb = _tmdb(mock_tmdb, {"Straying": [18, 35]})
    tmdb.discover.side_effect = lambda mt, genre_ids: [{"id": 1000, "title": "Straying", "genre_ids": [18, 35]}]
    pool = gather_candidates(
        tmdb,
        [seed(1, "R1")],
        sources=["tmdb_discover", "llm_web"],
        curator=_Curator(_pick("Straying")),
        profile=SimpleNamespace(history=[]),
        search=search,
        web_search_mode="exa",
        web_search_cache=_Cache(),
        credit_web_titles=True,
        web_credit_mode="full",
    )
    straying = next(c for c in pool if c.title == "Straying")
    assert straying.sources == {"tmdb_discover", "llm_web"}
    assert straying.affinity == 0.75 and straying.pre_web_affinity is None
