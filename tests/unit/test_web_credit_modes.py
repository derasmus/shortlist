"""Calibration modes for the AI-search credit, applied to one gathered pool (#152)."""

import json
from dataclasses import replace

import pytest

from shortlist.engine.candidates import gather_candidates
from shortlist.engine.clients.tmdb import POSITION_DECAY
from shortlist.engine.models import Candidate, MediaType, Seed
from shortlist.engine.ranking import WEB_CREDIT_MODES, apply_web_credit_mode, without_web_credit
from tests.unit.test_candidates_credit import _BySeedSearch, _gather, _pick, _snippets, _tmdb
from tests.unit.test_candidates_favourites import _Cache, _Curator, seed

A = Seed(1, "A", MediaType.MOVIE)
B = Seed(2, "B", MediaType.MOVIE)


def web_only(*, position: float | None, coherence: float | None = 0.8) -> Candidate:
    return Candidate(
        tmdb_id=10,
        title="W",
        media_type=MediaType.MOVIE,
        seeds=[A, B],
        web_seeds=[A, B],
        sources={"llm_web"},
        affinity=1.0 if coherence is None else coherence,
        web_coherence=coherence,
        web_position=position,
    )


def test_off_is_the_pool_ranked_before_the_credit_existed():
    pool = [web_only(position=0.5)]
    assert apply_web_credit_mode(pool, "off") == without_web_credit(pool)


def test_full_leaves_every_candidate_as_gathered():
    pool = [web_only(position=0.5)]
    assert apply_web_credit_mode(pool, "full") == pool


def test_decayed_lowers_affinity_by_position_with_the_tmdb_constant():
    top, bottom = apply_web_credit_mode([web_only(position=0.0), web_only(position=1.0)], "decayed")
    assert top.affinity == pytest.approx(0.8)
    assert bottom.affinity == pytest.approx(0.8 * (1 - POSITION_DECAY))
    assert top.seeds == [A, B]


def test_decayed_without_a_position_or_coherence_changes_nothing():
    unplaced = web_only(position=None)
    unpriced = web_only(position=1.0, coherence=None)
    assert apply_web_credit_mode([unplaced, unpriced], "decayed") == [unplaced, unpriced]


def test_single_keeps_only_the_first_crediting_seed():
    kept = Seed(3, "Kept", MediaType.MOVIE)
    cand = web_only(position=0.5)
    cand.seeds.insert(0, kept)
    (out,) = apply_web_credit_mode([cand], "single")
    assert out.web_seeds == [A]
    assert out.seeds == [kept, A]


def test_decayed_single_does_both():
    (out,) = apply_web_credit_mode([web_only(position=1.0)], "decayed_single")
    assert out.web_seeds == [A] and out.seeds == [A]
    assert out.affinity == pytest.approx(0.8 * (1 - POSITION_DECAY))


def test_no_mode_mutates_the_gathered_pool():
    pool = [web_only(position=1.0)]
    before = replace(pool[0], seeds=list(pool[0].seeds), web_seeds=list(pool[0].web_seeds))
    for mode in WEB_CREDIT_MODES:
        apply_web_credit_mode(pool, mode)
    assert pool[0] == before


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="nope"):
        apply_web_credit_mode([], "nope")


def test_gather_records_the_position_in_each_extraction_and_keeps_the_best(mock_tmdb):
    search = _BySeedSearch({"R1": ["X", "Shared", "Z"], "F1": ["Shared", "Y"]})
    pool = _gather(
        mock_tmdb,
        search,
        _Curator(_pick("Shared", "Z")),
        [seed(1, "R1")],
        favourite_seeds=[seed(10, "F1")],
        favourite_count=1,
    )
    assert pool["Shared"].web_position == 0.0
    assert pool["Z"].web_position == 1.0
    assert pool["Shared"].web_coherence == 1.0


def test_a_title_credited_by_because_has_no_position(mock_tmdb):
    reply = json.dumps([{"title": "N", "year": 2020, "media": "movie", "because": "r1"}])
    pool = _gather(mock_tmdb, _snippets(), _Curator(reply), [seed(1, "R1")], mode="searxng")
    assert pool["N"].web_seeds and pool["N"].web_position is None


def test_gather_in_off_mode_ranks_like_credit_off(mock_tmdb):
    search = _BySeedSearch({"R1": ["Shared", "Only R"], "F1": ["Shared"]})

    def gathered(**kwargs):
        pool = gather_candidates(
            _tmdb(mock_tmdb),
            [seed(1, "R1")],
            sources=["llm_web"],
            curator=_Curator(_pick("Shared", "Only R")),
            profile=type("P", (), {"history": []})(),
            search=search,
            web_search_mode="exa",
            web_search_cache=_Cache(),
            favourite_seeds=[seed(10, "F1")],
            favourite_count=1,
            **kwargs,
        )
        return {c.title: (c.seeds, c.affinity) for c in pool}

    assert gathered(credit_web_titles=True, web_credit_mode="off") == gathered(credit_web_titles=False)


def test_scaled_mode_scales_only_titles_the_search_found_alone():
    alone = web_only(position=0.0)
    shared = replace(web_only(position=0.0), tmdb_id=11, pre_web_affinity=0.6, affinity=0.6)
    out = apply_web_credit_mode([alone, shared], "scaled:0.5")
    assert out[0].affinity == pytest.approx(0.4)
    assert out[1].affinity == pytest.approx(0.6)


@pytest.mark.parametrize("mode", ["scaled:0", "scaled:1.5"])
def test_a_scale_outside_zero_to_one_is_refused(mode):
    with pytest.raises(ValueError):
        apply_web_credit_mode([web_only(position=0.0)], mode)


def test_production_scales_search_only_titles_to_seven_tenths():
    """Measured 2026-10-11, 230 held-out discoveries: full credit cost 2-4 hits (Exa without AI: 17 → 13);
    0.7 kept them (16-17 vs 16-17 uncredited) while the AI search's share of row titles roughly doubled."""
    from shortlist.engine.models import EngineConfig

    assert EngineConfig().web_credit_mode == "scaled:0.7"
