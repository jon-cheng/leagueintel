# scripts/setup.py
#
# Interactive first-run setup: collects ESPN credentials, writes .env,
# validates the credentials against the live ESPN API, and runs an
# initial data pull so there's something in the local DB to look at.
#
# Run after `poetry install`:
#   poetry run python scripts/setup.py

import subprocess
import sys
from pathlib import Path

from espn_api.football import League
from espn_api.requests.espn_requests import (
    ESPNAccessDenied,
    ESPNInvalidLeague,
    ESPNUnknownError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

DEMO_LEAGUE_ID = "899513"
DEMO_YEAR = 2024


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def ask_yes_no(prompt: str) -> bool:
    return ask(f"{prompt} (y/n)", "y").lower().startswith("y")


def collect_credentials() -> dict:
    """Walks the demo/own-league and public/private decision tree."""
    print("\nDo you want to try a public demo league, or connect your own?")
    print(f"  1) Demo league (public, no ESPN account needed — league {DEMO_LEAGUE_ID}, {DEMO_YEAR} season)")
    print("  2) My own league")
    choice = ask("Choose 1 or 2", "1")

    if choice != "2":
        return {"league_id": DEMO_LEAGUE_ID, "year": DEMO_YEAR, "espn_s2": "", "swid": ""}

    league_id = ask("Your league ID (from the URL, e.g. ...leagueId=123456)")
    year = ask("Season year to pull first", "2025")

    is_public = ask_yes_no("Is your league public?")
    if is_public:
        return {"league_id": league_id, "year": int(year), "espn_s2": "", "swid": ""}

    print(
        "\nPrivate leagues need two cookies from a logged-in browser session:\n"
        "  1. Log into fantasy.espn.com in your browser\n"
        "  2. Open DevTools > Application (Chrome) or Storage (Firefox) > Cookies\n"
        "     > https://fantasy.espn.com\n"
        "  3. Copy the values of 'espn_s2' and 'SWID'\n"
    )
    espn_s2 = ask("espn_s2")
    swid = ask("SWID")
    return {"league_id": league_id, "year": int(year), "espn_s2": espn_s2, "swid": swid}


def validate(creds: dict) -> bool:
    print(f"\nValidating league {creds['league_id']} for {creds['year']}...")
    try:
        league = League(
            league_id=creds["league_id"],
            year=creds["year"],
            espn_s2=creds["espn_s2"] or None,
            swid=creds["swid"] or None,
        )
        print(f"OK — found {len(league.teams)} teams.")
        return True
    except ESPNAccessDenied:
        if creds["espn_s2"]:
            print("ESPN rejected these cookies. Double-check espn_s2/SWID and try again.")
        else:
            print("This league needs auth — it isn't public. Re-run and choose 'private' with your cookies.")
        return False
    except ESPNInvalidLeague:
        print(f"League {creds['league_id']} doesn't exist for {creds['year']}. Check the league ID and year.")
        return False
    except ESPNUnknownError as e:
        print(f"ESPN returned an unexpected error: {e}")
        return False


def write_env(creds: dict, anthropic_key: str) -> None:
    lines = [
        f"LEAGUE_ID={creds['league_id']}",
        f"ESPN_S2={creds['espn_s2']}",
        f"SWID={creds['swid']}",
        f"ANTHROPIC_API_KEY={anthropic_key}",
    ]
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {ENV_PATH}")


def run_initial_sync(year: int) -> None:
    print(f"\nPulling {year} season data into a local SQLite DB (this can take a minute)...")
    result = subprocess.run(
        [sys.executable, "-m", "leagueintel.cli", "sync", "--seasons", str(year)],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("Data pull failed — see the error above. You can retry with:")
        print(f"  poetry run leagueintel sync --seasons {year}")


def main():
    print("leagueintel setup\n" + "=" * 17)

    creds = collect_credentials()
    if not validate(creds):
        print("\nSetup stopped — fix the issue above and re-run scripts/setup.py.")
        sys.exit(1)

    anthropic_key = ask("\nAnthropic API key (optional, enables the chatbot — leave blank to skip)")

    write_env(creds, anthropic_key)
    run_initial_sync(creds["year"])

    print(
        "\nDone. Start the app with:\n"
        "  poetry run streamlit run src/leagueintel/reporting/home.py\n"
    )


if __name__ == "__main__":
    main()
