# Taking anonymized screenshots

leagueintel supports taking anonymized screenshots/demos via a
disposable, one-time-anonymized copy of the database — not a schema
migration, not a runtime flag, not anything the real app or real
`leagueintel.db` ever knows about.

1. The real `leagueintel.db` (used by the deployed app and
   `leagueintel sync`) is never touched — no schema change, no new
   table, no new view, no code changes anywhere.
2. Copy the real database to a new, separate file:
   ```
   cp leagueintel.db leagueintel_demo.db
   ```
   From this point on it's a completely independent file — no link, no
   shared storage, no relationship to the original.
3. Run the anonymize script ONCE against that copy:
   ```
   poetry run python scripts/anonymize_demo_db.py --db ./leagueintel_demo.db
   ```
   It prints the resolved path, a sample of current names, and requires
   typed `yes` confirmation before permanently overwriting
   `teams.owner_name`/`teams.team_name` in place with generated aliases
   (Manager A/Team A, Manager B/Team B, ...) — the same `team_id` always
   gets the same alias across every season.
4. Because the overwrite happens directly in the `teams` table (not a
   view layered on top), every existing query — dashboard pages,
   `run_analysis` functions, and the chatbot's ad-hoc LLM-generated SQL
   — automatically returns aliases when run against the demo copy, with
   zero code changes anywhere. There's no real name left in that file
   for any query to return.
5. Point the app at the demo copy and take your screenshots:
   ```
   DB_PATH=./leagueintel_demo.db poetry run streamlit run src/leagueintel/reporting/home.py
   ```
   Verify every page and a few chatbot questions show aliases before
   recording/screenshotting.
6. `leagueintel_demo.db` is local-only — never committed to git, never
   uploaded to S3. Discard it when done, or keep it; regenerate a fresh
   anonymized copy anytime by repeating steps 2–3 from the current real
   data.
