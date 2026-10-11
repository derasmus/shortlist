"""A credited AI web-search title ranks and reads like a similar title from its watch (#152)."""

from shortlist.engine import ranking
from shortlist.engine.models import Candidate, MediaType, Seed
from shortlist.engine.picker import build_picks, reason_for


def _seed(n: int) -> Seed:
    return Seed(tmdb_id=n, title=f"Watched {n}", media_type=MediaType.MOVIE, weight=1.0)


def _similar(n: int) -> Candidate:
    return Candidate(
        tmdb_id=1000 + n,
        title=f"Similar {n}",
        media_type=MediaType.MOVIE,
        rating=7.0,
        genres=["Drama"],
        seeds=[_seed(n)],
        sources={"tmdb_similar"},
        affinity=0.8,
    )


def _web(n: int, *, credited: bool) -> Candidate:
    seed = _seed(100 + n)
    return Candidate(
        tmdb_id=5000 + n,
        title=f"Web {n}",
        media_type=MediaType.MOVIE,
        rating=7.0,
        genres=["Drama"],
        seeds=[seed] if credited else [],
        web_seeds=[seed] if credited else [],
        sources={"llm_web"},
    )


def _row(web: list[Candidate], keep: int = 15) -> list[Candidate]:
    pool = [*(_similar(n) for n in range(20)), *web]
    ranked = ranking.pre_rank(pool, 40)
    return ranking.diversify_by_seed(ranked, keep)


def test_an_uncredited_web_title_gets_no_slot_among_seeded_ones():
    row = _row([_web(n, credited=False) for n in range(4)])
    assert not [c for c in row if "llm_web" in c.sources]


def test_a_credited_web_title_competes_with_the_similar_titles_of_its_watch():
    row = _row([_web(n, credited=True) for n in range(4)])
    assert len([c for c in row if "llm_web" in c.sources]) == 4


def test_a_credited_title_scores_like_a_seeded_one():
    assert ranking.score(_web(0, credited=True)) > ranking.score(_web(0, credited=False))
    assert ranking.score(_web(0, credited=True)) == ranking.score(_web(0, credited=False)) * 2 * 2


def test_the_reason_names_the_watch_that_found_a_credited_title():
    assert reason_for(_web(1, credited=True)) == "Because you watched Watched 101 — more drama"
    assert reason_for(_web(1, credited=False)) == "Recommended on the web right now"


def test_the_pick_keeps_its_ai_source_and_credits_the_seed_in_its_reason_but_not_its_name():
    pick = build_picks([_web(1, credited=True)], 1)[0]
    assert "Watched 101" in pick.reason and "llm_web" in pick.sources
    assert pick.seed_title is None, "a row is named only from seeds a similarity source gave"
