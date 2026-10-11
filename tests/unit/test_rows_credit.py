"""What a row hands the AI web-search credit (#152): the config switch and the weight of history seeds."""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median
from unittest.mock import patch

import pytest

from shortlist.engine.models import EngineConfig
from shortlist.engine.taste import history_mix
from tests.unit.test_rows_taste import _history, _policy, _row

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _gather_kwargs(policy) -> dict:
    policy.specs = [spec := _row()]
    with patch("shortlist.engine.rows.candidates_mod.gather_candidates", side_effect=RuntimeError("stop")) as gather:
        policy.pools_for(spec)
    return gather.call_args.kwargs


def test_credit_is_on_by_default():
    assert EngineConfig().credit_web_titles is True


@pytest.mark.parametrize("on", [True, False])
def test_the_config_switch_reaches_the_gather(on):
    kwargs = _gather_kwargs(_policy(web_search_provider="exa", credit_web_titles=on))
    assert kwargs["credit_web_titles"] is on


def _mix(**kw):
    return history_mix(
        _history(), blocked=set(), ratings=None, resolve=lambda item: item.tmdb_id, favourites=3, older=2, now=NOW, **kw
    )


def test_history_seeds_weigh_what_the_caller_says():
    mix = _mix(seed_weight=2.5)
    seeds = [*mix.favourite_seeds, *mix.older_seeds]
    assert mix.favourite_seeds and mix.older_seeds and {s.weight for s in seeds} == {2.5}


def test_history_seeds_weigh_one_without_a_weight():
    mix = _mix()
    seeds = [*mix.favourite_seeds, *mix.older_seeds]
    assert mix.favourite_seeds and mix.older_seeds and {s.weight for s in seeds} == {1.0}


def test_a_rows_history_seeds_weigh_the_median_of_its_recent_seeds():
    policy = _policy(favourite_count=4, older_count=4)
    row = _row()
    recent = policy.seeds_for(row)[: policy.effective_recent_count(row)]
    expected = median(s.weight for s in recent)
    mix = policy.taste_for(row)
    seeds = [*mix.favourite_seeds, *mix.older_seeds]
    assert seeds and {s.weight for s in seeds} == {expected}


def _named_row():
    from shortlist.engine.models import RowSpec

    return RowSpec(slug="r", name_template="Because you watched {top_seed}", size=5)


def _candidate(tmdb_id, seeds, web_seeds=()):
    from shortlist.engine.models import Candidate, MediaType

    return Candidate(
        tmdb_id=tmdb_id, title=f"T{tmdb_id}", media_type=MediaType.MOVIE, seeds=list(seeds), web_seeds=list(web_seeds)
    )


def test_a_web_credited_seed_is_not_a_candidates_naming_seed():
    from shortlist.engine.models import MediaType, Seed

    own = Seed(1, "Own", MediaType.MOVIE, weight=0.2)
    credited = Seed(2, "Credited", MediaType.MOVIE, weight=0.9)
    candidate = _candidate(10, [own, credited], [credited])
    assert candidate.top_seed is credited
    assert candidate.naming_seed is own
    assert _candidate(11, [credited], [credited]).naming_seed is None


def test_a_row_whose_only_seeded_candidate_ahead_is_web_credited_does_not_report_a_seed_move():
    from shortlist.engine.delivery import top_seed_of
    from shortlist.engine.models import MediaType, Pick, Seed
    from shortlist.engine.rows import _seed_moved

    policy = _policy()
    named = Seed(1, "Named", MediaType.MOVIE, weight=0.5)
    credited = Seed(2, "Favourite", MediaType.MOVIE, weight=0.9)
    prior = [
        Pick(
            tmdb_id=10,
            rating_key=1,
            title="T10",
            rank=1,
            reason="r",
            media_type=MediaType.MOVIE,
            seed_tmdb_id=1,
            seed_title="Named",
        )
    ]
    sub = [_candidate(20, [credited], [credited]), _candidate(10, [named])]
    assert _seed_moved(_named_row(), prior, sub, policy.user, policy.cfg, 1) is False
    assert top_seed_of(prior) == "Named"


def test_a_pick_built_from_a_web_credited_candidate_names_no_seed():
    from shortlist.engine.models import MediaType, Seed
    from shortlist.engine.picker import build_picks

    credited = Seed(2, "Favourite", MediaType.MOVIE, weight=0.9)
    (pick,) = build_picks([_candidate(20, [credited], [credited])], 5)
    assert (pick.seed_tmdb_id, pick.seed_title) == (None, None)


def test_a_carried_pick_seeded_by_a_favourite_is_reattributed_like_any_dropped_seed():
    """A row name only ever comes from a row seed (``naming_seed`` skips web credit), so a favourite outside
    tonight's seed set is a stale name: keeping it would rename the row after a watch it was not built from."""
    from shortlist.engine.models import MediaType, Pick, Seed
    from shortlist.engine.rows import _reseed_survivors

    favourite = Seed(7, "Favourite", MediaType.MOVIE)
    kept = [
        Pick(
            tmdb_id=10,
            rating_key=1,
            title="T10",
            rank=1,
            reason="r",
            media_type=MediaType.MOVIE,
            seed_tmdb_id=7,
            seed_title="Favourite",
        )
    ]
    recent = Seed(1, "Recent", MediaType.MOVIE)
    out = _reseed_survivors(kept, [_candidate(10, [recent, favourite], [favourite])], [recent])
    assert (out[0].seed_tmdb_id, out[0].seed_title) == (1, "Recent")
