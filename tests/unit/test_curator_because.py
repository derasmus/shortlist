"""The optional "because" field a native or snippet web search may return (#152)."""

from shortlist.engine.curator.base import parse_web_titles


def test_a_string_because_is_kept_and_anything_else_is_dropped():
    reply = (
        '[{"title": "A", "year": 2020, "media": "movie", "because": "Silo"},'
        ' {"title": "B", "year": 2020, "media": "movie", "because": 7},'
        ' {"title": "C", "year": 2020, "media": "movie", "because": null},'
        ' {"title": "D", "year": 2020, "media": "movie"}]'
    )
    parsed = parse_web_titles(reply, 10)
    assert parsed[0]["because"] == "Silo"
    assert all("because" not in rec for rec in parsed[1:])
