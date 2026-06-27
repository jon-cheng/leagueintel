# leagueintel working agreement

## My learning goals
This is a deliberate learning project. I want to improve at:
- Python OOP and single responsibility principle
- pytest and test-driven thinking
- Python packaging
- CI/CD with GitHub Actions
- LLM tool use and agentic patterns

Prioritize my understanding over speed. I want to rebuild strong habits.

## How to work with me
- Before writing any code, explain the approach and tradeoffs in
  plain language. Wait for my go-ahead before implementing.
- Propose changes as small, focused diffs — one concern at a time.
- When introducing a pattern for the first time (dataclass, fixture,
  context manager, etc.), explain WHY this pattern over alternatives.
- Never refactor unrelated code in the same change.
- Write tests alongside new logic. Explain what each test is protecting
  against, not just what it does.
- Flag when I'm about to do something that violates single responsibility
  or will be hard to test later.
- When I ask "why", give reasoning first, code second.

## What I don't want
- Large sweeping changes I can't review in one sitting
- Boilerplate I don't understand
- Skipping tests to move faster

## Stack
- Python 3.10, conda (miniforge at /opt/homebrew/Caskroom/miniforge)
- pytest for testing
- SQLite for persistent storage
- GitHub Actions for CI/CD
- espn_api, nflreadpy for data ingestion
- click for CLI
- loguru for logging
- Claude API for LLM features