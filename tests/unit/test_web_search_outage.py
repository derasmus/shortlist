"""A SearXNG page that is empty because every engine was rate-limited is an outage, not an answer (#152).

Measured 2026-10-11 on a fresh SearXNG: after ~400 searches Brave, DuckDuckGo and Google CSE all answered
"Suspended: too many requests" and 388 of 429 searches came back empty. Cached as a thin result, each of
those hid that title's suggestions for 24 hours — into the next night's run.
"""

from shortlist.engine.candidates import gather_candidates
from shortlist.engine.clients.search import SearchResult, SearxngClient
from tests.unit.test_candidates import _DictCache, _NonNativeCurator, seed, web_profile


class _Searx:
    name = "searxng"
    results_per_query = 10

    def __init__(self, pages):
        self.pages = pages  # query substring -> (results, dead engines)
        self.queries: list[str] = []

    def search_status(self, query, num_results=10):
        self.queries.append(query)
        for watched, page in self.pages.items():
            if watched in query:
                return page
        return [], []

    def search(self, query, num_results=10):
        return self.search_status(query, num_results)[0]


def _gather(mock_tmdb, search, cache, seeds):
    mock_tmdb.suggestions.side_effect = lambda tid, mt: []
    mock_tmdb.genre_names.return_value = {}
    mock_tmdb.search.side_effect = lambda title, mt, year=None: None
    return gather_candidates(
        mock_tmdb,
        seeds,
        sources=["llm_web"],
        curator=_NonNativeCurator("[]"),
        profile=web_profile(),
        search=search,
        web_search_mode="searxng",
        web_search_cache=cache,
    )


def test_an_empty_page_from_dead_engines_is_not_cached(mock_tmdb):
    ok = [SearchResult(title="Shows like Arrival", url="https://example.com/a", text="Try Contact")]
    search = _Searx({"Dune": ([], ["brave", "duckduckgo"]), "Arrival": (ok, [])})
    cache = _DictCache()
    _gather(mock_tmdb, search, cache, [seed(1, "Dune"), seed(2, "Arrival")])
    assert set(cache.store) == {"websearch2:searxng:movie:2"}


def test_a_genuinely_empty_page_is_still_cached_as_thin(mock_tmdb):
    ok = [SearchResult(title="Shows like Arrival", url="https://example.com/a", text="Try Contact")]
    search = _Searx({"Dune": ([], []), "Arrival": (ok, [])})
    cache = _DictCache()
    _gather(mock_tmdb, search, cache, [seed(1, "Dune"), seed(2, "Arrival")])
    assert "websearch2:searxng:movie:1" in cache.store


def test_the_client_reports_the_dead_engines(respx_mock):
    import httpx

    body = {"results": [], "unresponsive_engines": [["brave", "Suspended: too many requests"]]}
    respx_mock.get("http://searx.local/search").mock(return_value=httpx.Response(200, json=body))
    assert SearxngClient("http://searx.local").search_status("q") == ([], ["brave"])
