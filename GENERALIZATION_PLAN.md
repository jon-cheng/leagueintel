# leagueintel generalization — step plan & Claude Code prompts

This is the sequence we worked out across this conversation, broken into steps small enough to land as separate, reviewable diffs. Regression-testing steps (1–3) come first and are meant to be fully merged *before* any of the generalization logic (4–7) is touched — they're the safety net, not an afterthought.

Each step below has a ready-to-paste Claude Code prompt. See the note at the bottom on how to actually feed these in.

---

## The sequence at a glance

0. Create the feature branch (you do this yourself — `git checkout -b generalize-league-rules` or similar)
1. Capture a real-data regression baseline (characterization test) for every analytics entry point, against your actual league's real history
2. Wire `tests/golden_questions.py` into pytest as an explicit, separately-runnable marker
3. Add Streamlit `AppTest`-based smoke tests per page, run against both the real baseline DB and synthetic rule-shape fixtures
4. Build the settings-driven `LeagueRules` object and wire it into `standings.py` / `consolation.py`'s tiebreak logic
5. Split draft-value into an auction-price metric and a snake-draft positional-rank-gap metric, dispatched by `draftSettings.type`
6. Clean up the chatbot's own prompt text (hardcoded `week = 17`, the league-specific "6 of 7 seasons" claim, "toilet bowl" naming baked into schema description, the wrong-by-default fallback strings)
7. Move Arby's/Toilet Bowl-style prize naming into per-league structured config, per the deterministic-check approach (no LLM reconciliation)

Steps 1–3 are fully scoped from what we discussed and the prompts below are ready to use as-is. Steps 4–7 are scoped in *design*, but a couple (5 especially) still have open questions we flagged — those prompts say so explicitly, and Claude Code should stop and confirm the approach before writing code, same as we did here.

---

## Step 1 — Real-data regression baseline

**Why first:** nothing today protects "does a refactor change the actual output for my real league's real history." This has to exist before step 4 touches any logic, or the refactor has no safety net.

```
I'm about to refactor leagueintel's analytics layer (standings.py, consolation.py,
draft.py, waiver.py) to make behavior driven by ESPN league settings instead of
hardcoded assumptions, ahead of generalizing this app to work with any ESPN
fantasy football league. Before I touch any of that logic, I need a regression
safety net that proves the refactor doesn't change output for MY real league's
real historical data.

Please:
1. Write a script (e.g. scripts/capture_regression_baseline.py) that connects to
   the real leagueintel.db and, for every season in ALL_SEASONS, calls:
   get_standings, get_medal_standings, get_arbys_winner, get_toilet_bowl_loser,
   get_draft_roi, get_waiver_scores
   and serializes the results to a JSON file (e.g. tests/fixtures/regression_baseline.json).
2. Scrub or hash owner_name / team_name in that output rather than storing real
   names verbatim — I may eventually make this repo public, and I don't want
   real people's names sitting in a committed fixture file. Use a stable
   pseudonym per manager (e.g. manager_1, manager_2) consistent across seasons.
3. Add a pytest test (mark it distinctly, e.g. @pytest.mark.regression, excluded
   from the default `pytest -m "not integration"` CI run the same way
   integration tests are) that re-runs those same calls against the real DB and
   diffs the result against the committed baseline file, failing with a clear
   message showing exactly which season/metric changed.
4. Run the capture script now, against the current unmodified code, and commit
   the resulting baseline file as the very first commit on this branch — before
   any other change.

Before writing code: tell me your plan for exactly how the diff/comparison will
work (float tolerance, how you handle NaN/missing seasons, etc.) and confirm
with me before implementing.
```

---

## Step 2 — Wire golden_questions.py into pytest

**Why:** the ground-truth data already exists in `tests/golden_questions.py`; the docstring literally says it's not wired into pytest yet, and it's specifically meant for exactly the kind of prompt change coming in step 6.

```
tests/golden_questions.py already contains real question/ground-truth pairs for
the leagueintel chatbot, documented as "not wired into pytest yet — intended for
manual verification when SCHEMA_DESCRIPTION or SQL-generation prompting
changes." I'm about to change that prompting as part of a larger generalization
effort, so I want this automated first.

Please:
1. Read tests/golden_questions.py and leagueintel/reporting/chatbot.py to
   understand how a question currently gets answered (query_db vs
   run_analysis tool routing).
2. Add a pytest test file (e.g. tests/reporting/test_golden_questions.py) that,
   for each case in GOLDEN_QUESTIONS, invokes the chatbot's actual
   question-answering path and asserts the returned facts match ground_truth
   (exact match where ground_truth gives a specific ID/value; a looser check
   only where genuinely necessary).
3. Mark these tests distinctly (e.g. @pytest.mark.llm) and exclude them from
   the default CI `pytest -m "not integration"` run, since they cost real
   Anthropic API tokens per run — CI can run them in a separate, explicitly
   invoked job instead.
4. Do NOT modify chatbot.py's prompt text yet — this step is only about making
   the existing golden questions runnable and passing against today's code.

Before writing code: tell me how you plan to invoke the chatbot's
question-answering path from a test (which function/entry point), and confirm
before implementing.
```

---

## Step 3 — Streamlit AppTest smoke tests

**Why:** protects against the thing manual Streamlit spot-checking can't scale to — pages crashing for league shapes you don't personally have (no consolation ladder, different playoff_team_count, etc.).

```
I want automated smoke tests for leagueintel's Streamlit pages using
streamlit.testing.v1.AppTest, to catch pages that crash for a league shape
different from mine (e.g. consolationLadderDisabled=True, a different
playoff_team_count, single vs multi-division).

Please:
1. Read src/leagueintel/reporting/pages/*.py and home.py to understand the
   st.session_state["authenticated"] gate pattern and how each page loads data.
2. Add tests/reporting/test_page_smoke.py with one AppTest-based test per page
   (Podium, Season_Overview, Draft_ROI, Best_Waiver, Head_to_Head, Chat) that:
   - pre-sets at.session_state["authenticated"] = True before at.run()
   - asserts at.exception == [] (no crash)
   - runs first against the real regression-baseline DB from step 1
3. Add a second parametrized run of the same smoke tests against small
   synthetic SQLite DBs seeded with different rule-shape fixtures — reuse the
   same tiny-synthetic-team style already used in tests/analytics/test_consolation.py
   (Manager A/B/C, not real names). At minimum cover: no consolation ladder,
   a 4-team playoff, and a single-division vs multi-division league.
4. For the Chat page specifically: chatbot.py makes a real network call to ESPN
   at module import time (LEAGUE_CONTEXT = _load_league_context()). Tell me how
   you plan to handle that in a test running with no network access (patch the
   loader function vs. relying on its exception fallback) before implementing.

Before writing code: confirm the plan for the synthetic rule-shape fixtures and
the Chat-page network call handling with me first.
```

---

## Step 4 — `LeagueRules` object + settings-driven standings

```
Now that the regression baseline (step 1), golden questions (step 2), and page
smoke tests (step 3) are in place and passing, I want to make standings.py and
consolation.py's get_regular_season_standings driven by the league's actual
ESPN settings instead of a hardcoded sort by wins/points_for.

[Context: we verified real settings JSON for my league already — matchupTieRule
and playoffMatchupTieRule = 'NONE', playoffSeedingRule = 'TOTAL_POINTS_SCORED',
scoringEnhancementType absent (median_scoring = False). standings.py currently
hardcodes sort_values(["wins", "points_for"]), which happens to match my
league's playoffSeedingRule by coincidence, not by design.]

Please propose a design for a LeagueRules-style object built from
league.settings (or a plain settings dict, for testability without a live
League instance) that exposes at minimum: the standings sort/tiebreak order,
and whether median-bonus wins apply. Do not write the standings-changing code
yet — first explain the design, how compute_standings' signature would change,
and how you'd test it with fixture settings dicts (following the existing
Manager A/B/C fixture convention). Wait for my go-ahead before implementing.
```

---

## Step 5 — Draft-value dispatch (auction vs. snake) — open question flagged

```
I want to split leagueintel's draft ROI analysis into two metrics: the existing
auction-price-based one (draft.py's compute_draft_roi, price efficiency via
bid_amount), and a new one for snake-draft leagues based on positional pick-rank
vs. positional finish-rank (not raw overall_pick_number, since positional
scarcity makes that incomparable across positions), dispatched on
draftSettings.type.

[Context: draftSettings.type = 'AUCTION' is confirmed for my real league via a
direct request with view=mSettings — espn_api's BaseSettings does NOT store
draftSettings' raw dict the way it does scoringSettings/scheduleSettings, so
this needs to come from a raw request or a library patch, not league.settings
directly. I have NOT yet confirmed what value ESPN uses for a snake draft, or
seen a real snake-draft league's settings JSON.]

Before writing any code: given that open unknown, propose how you'd design and
test this without guessing the exact snake-draft enum string — e.g. branching
on "== 'AUCTION'" vs. else, rather than checking for an exact snake value I
haven't verified. Also propose how draft_box_scores' SQL view would need to
change to carry overall_pick_number (it currently doesn't). Wait for my
go-ahead before implementing.
```

---

## Step 6 — Chatbot prompt-layer cleanup

```
leagueintel's chatbot (src/leagueintel/reporting/chatbot.py) has several
hardcoded, league-specific assumptions baked into its own system prompt text
(not just the Python around it), found during a generalization audit:
- "Championship games: matchup_type = 'WINNERS_BRACKET' AND week = 17" —
  hardcoded to my league's specific final week
- A claim that "6 of 7 seasons had a different regular-season leader vs.
  champion" stated as general reasoning — true for my league, not generalizable
- "LOSERS_CONSOLATION_LADDER=toilet bowl" baked into the schema description
- _load_league_context/_load_scoring_description fall back to hardcoded
  "private 12-team league" / "Half PPR" strings on API failure, which would be
  actively wrong for any other league

Please propose (don't implement yet) how each of these should be generalized:
computing the championship week dynamically instead of hardcoding 17, whether
the "6 of 7 seasons" claim should be computed live per-league or removed,
whether prize naming should be pulled from the per-league config we discussed
(step 7) or genericized, and what an honest (not silently-wrong) fallback
should say when the ESPN API call fails. Confirm the plan with me, and note
this depends on tests/golden_questions.py already being wired into pytest
(step 2) so we can verify these prompt changes didn't break real Q&A behavior.
```

---

## Step 7 — Per-league prize-naming config

```
Arby's/Toilet Bowl-style prize names are hardcoded throughout Podium.py,
Season_Overview.py, and consolation_card.py, and none of that is derivable
from ESPN's API — it's pure league culture. Per our earlier design decision
(deterministic structured config, no LLM reconciliation), propose a small
per-league config addition that lets these be named per-instance, and how
Podium.py etc. would read from it instead of hardcoding the names. Note: the
underlying detection logic (get_arbys_winner/get_toilet_bowl_loser) already
derives WHO wins dynamically from win/loss counts — this step is about the
LABEL only, not re-deriving the winner. Also flag the known edge cases we found
(tied win counts picked arbitrarily by max(), and a crash if
consolationLadderDisabled=True) as things this step should probably fix
alongside the relabeling, since you'll be in that code anyway — but confirm
with me before deciding to bundle those fixes in vs. splitting them out.
```

---

## Should you feed the whole thing in as one giant prompt?

No — run these one at a time, in order, committing (or at least reviewing and stopping) between each. A few concrete reasons, not just general caution:

- **Sequencing is load-bearing, not cosmetic.** Step 1's baseline has to be captured against *unmodified* code. If it's bundled into a single mega-prompt with step 4's refactor, there's a real risk the baseline gets captured *after* the refactor already touched something, which quietly defeats the entire point of having it.
- **Each step should land as its own reviewable diff.** That's the same discipline we've been using in this conversation the whole way through — small, focused changes you can actually read and reason about, rather than one large diff where a mistake in step 2 is tangled up with step 5 and hard to isolate.
- **A couple of these genuinely aren't ready to just execute.** Step 5 has a real open question (the unverified snake-draft enum value) that needs a design decision from you, not a guess from Claude Code plowing through a giant prompt. The prompts above are written to make Claude Code stop and confirm before writing code, for exactly that reason — a single giant prompt makes it much easier for that pause to get skipped over.
- **Context quality degrades with unrelated concerns mixed together.** A prompt covering regression tests, settings parsing, draft economics, and prompt engineering all at once makes it harder for Claude Code to reason precisely about any one of them.

What's fine to do as one shot: pasting this whole outline at the *start* of a Claude Code session as shared context (e.g., save this file into the repo as `NOTES.md` or similar and tell Claude Code to read it first) so it has the full roadmap and knows step 4 is coming — but the actual "go implement this" instruction should still be issued one step at a time.
