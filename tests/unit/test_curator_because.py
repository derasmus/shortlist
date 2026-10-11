"""The optional "because" field a native or snippet web search may return (#152)."""

from shortlist.engine.curator.base import parse_web_titles
from shortlist.engine.curator.google import _TITLES_SCHEMA, _titles_schema
from shortlist.engine.curator.openai import _TITLES_FORMAT, _titles_format


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


def test_the_openai_schema_is_untouched_without_because():
    assert _titles_format(False) is _TITLES_FORMAT
    assert "because" not in str(_TITLES_FORMAT)


def test_the_openai_schema_lists_because_as_required_and_nullable_when_asked_for():
    item = _titles_format(True)["format"]["schema"]["properties"]["titles"]["items"]
    assert item["properties"]["because"] == {"type": ["string", "null"]}
    assert item["required"] == ["title", "year", "media", "because"]
    assert item["additionalProperties"] is False
    assert "because" not in str(_TITLES_FORMAT), "the shared schema is copied, not edited"


def test_the_google_schema_is_untouched_without_because():
    assert _titles_schema(False) is _TITLES_SCHEMA
    assert "because" not in str(_TITLES_SCHEMA)


def test_the_google_schema_carries_an_optional_nullable_because_when_asked_for():
    item = _titles_schema(True)["properties"]["titles"]["items"]
    assert item["properties"]["because"] == {"type": "string", "nullable": True}
    assert item["required"] == ["title", "media"]
