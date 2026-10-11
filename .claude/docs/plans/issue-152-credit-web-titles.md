# #152 phase 3: AI-search titles get credit for the watch that found them

## Root cause (measured 2026-10-11)

`candidates.gather_candidates` adds every AI-web-search title with `add(found, media_type, "llm_web")`: no seed,
affinity 1.0. So in `ranking.score` it gets `(1+0) * rating * (1+0) * 1.0` against a TMDB-similar title's
`(1+n) * rating * (1+w) * affinity`, and in `ranking.diversify_by_seed` every seedless title shares ONE queue
(`None`) that is visited in the order of its best candidate — after 15+ seeded queues, so it gets no slot.
Run 15 (46 people): 65 of 92 "Picked for You" rows held 0 AI-search titles, 17 held 1; 6% of that row's picks
vs 27% on single-seed "Because you watched" rows. Live dry run 17 (MooHouse, 4 mix variants): 0 of 120 final
titles from the AI search although the AI picked 27–32 titles per row, including the new favourite/older ones.

## Fix

### 1. Credit (engine, `candidates.py`)

Each web rec carries the seeds it is credited to — `rec["for"]: list[Seed]`, internal, never serialised:

- **Structured path (Exa, with or without AI):** `found_by[title_key] = [seeds whose search extraction held it]`,
  in search order, built from `per_seed_titles` and the `searched` list (recent, favourite and older seeds alike).
  A rec gets `found_by.get(key, [])`; if empty, fall back to a valid `because` (below).
- **RAG path (SearXNG + AI):** `found_by` from per-seed snippets: seeds whose snippet title or text contains the
  title (normalised, word-boundary match). Then `because`.
- **Native path (the AI's own web search):** `because` only.
- **`because`:** the native and RAG prompts ask for an optional `"because": "<one of the watched titles listed
  above>"` per title. `try_parse_web_titles` keeps it when it is a string. Accepted only when it normalises to
  exactly one of the seeds the prompt listed (recent searched seeds + favourite + older seeds); anything else is
  ignored, never invented. The structured pick prompt does NOT ask (credit is already known; saves tokens).
- In `gather_candidates`, for a resolved rec: `cand = add(found, media_type, "llm_web", affinity)` then append each
  credited seed not already on `cand.seeds` (dedupe by `(tmdb_id, media_type)`), and record them on a new
  `Candidate.web_seeds` list (what the web path added — the replay strips these for its "credit off" ranking).
  `affinity` for a credited title = `genre_coherence(_seed_genre_ids(tmdb, top credited seed), found genre_ids)` —
  the same coherence check a TMDB-similar title gets; an uncredited title keeps 1.0 exactly as today.
- `EngineConfig.credit_web_titles: bool = True` (internal, not a setting). False = exact old behaviour (no credit,
  no `because` in prompts). Threaded to `gather_candidates`.

### 2. History seeds weigh like a typical recent watch (`rows.py` / `taste.py`)

Favourite and older `Seed`s are built with the default `weight=1.0`, which would out-rank every recent seed once
they carry credit. Give them `weight = median(weight of the row's searched recent seeds)` (1.0 if none) so
"Balanced" means history titles compete as equals with an average recent watch. Done where `taste_for` has the
searched seeds; `history_mix` takes an optional `seed_weight: float`.

### 3. Reasons

A credited AI title's reason must read like a TMDB one ("Because you watched X"). Check `picker`'s reason /
attribution path for llm_web-only picks today and make the credited case use the seed. Uncredited stays as today.

### 4. Run page: AI share

`RunDetailOut` gains `web_share: {"picked": float | None, "all": float | None}` = fraction of this run's picks whose
`sources` include `llm_web`, for the default "picked" row and for all rows (None when no picks). Run detail page
shows one line: "AI-search titles in rows: N% (Picked for You: M%)". Only when llm_web was enabled in that run
(None otherwise → line hidden).

### 5. Replay (`engine/eval/replay.py`, `scripts/replay_eval.py`)

- Configurable setup: `SEARCH` = exa | searxng | native; `SEARXNG_URL`; `CURATOR` = server (as configured) |
  ollama (`OLLAMA_URL`, `OLLAMA_MODEL`) | none. Arms = list of (favourites, older).
- Per case and arm, gather ONCE, then rank twice: credit on (as gathered) and credit off (each candidate's
  `web_seeds` removed from `seeds`, affinity back to 1.0 for web-only titles). Report both `in_row`.
- Also per arm over ALL cases: share of final row titles whose sources include llm_web (credit on / off), and
  how many of those came from favourite/older seeds.
- `CASES_PER_USER`/`MAX_CASES` knobs; print tokens and new searches per arm.

## Tests (first)

- structured: a rec found by two seeds' searches carries both; favourite/older seeds credited; affinity uses
  coherence; uncredited rec unchanged (1.0, no seeds).
- RAG: snippet match credits; `because` credits; invalid `because` ignored.
- native: `because` matched → credited; unknown title → none.
- ranking: a credited web title gets its own seed queue in `diversify_by_seed` (row of 20 TMDB seeds + credited
  web titles now holds web titles; with `credit_web_titles=False`, byte-identical to today).
- history seeds' weight = median recent weight.
- picker reason for credited web title.
- run detail web_share.
- replay: credit off ranking equals today's ranking for the same pool.
