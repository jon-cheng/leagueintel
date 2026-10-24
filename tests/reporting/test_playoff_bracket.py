# tests/reporting/test_playoff_bracket.py
import re

import pandas as pd

from leagueintel.reporting import playoff_bracket


def _game(week, home_owner, away_owner, home_score, away_score):
    return {
        "week": week,
        "home_owner": home_owner,
        "away_owner": away_owner,
        "home_score": home_score,
        "away_score": away_score,
    }


def _render_with(monkeypatch, games):
    monkeypatch.setattr(playoff_bracket, "get_playoff_matchups", lambda season: pd.DataFrame(games))
    return playoff_bracket.render_playoff_bracket(2026)


def _champion(html):
    return re.search(r'<div class="champ-name">(.*?)</div>', html).group(1)


def test_unplayed_championship_shows_no_scores_and_no_champion(monkeypatch):
    """
    Protects the bracket during a live playoff week. The championship has
    NULL scores (NaN after read_sql) until played: NaN used to render as
    the literal text "nan", and the champion check fell through to the
    away team, naming a champion before the game happened.
    """
    html = _render_with(
        monkeypatch,
        [
            _game(15, "Manager A", "Manager D", 120.0, 100.0),
            _game(15, "Manager B", "Manager C", 110.0, 105.0),
            _game(16, "Manager A", "Manager B", None, None),  # not played yet
        ],
    )

    assert ">nan<" not in html
    assert _champion(html) == "TBD"


def test_played_championship_names_the_winner(monkeypatch):
    """Protects the normal case: once the final is played, the higher score wins."""
    html = _render_with(
        monkeypatch,
        [
            _game(15, "Manager A", "Manager D", 120.0, 100.0),
            _game(15, "Manager B", "Manager C", 110.0, 105.0),
            _game(16, "Manager A", "Manager B", 90.0, 130.0),
        ],
    )

    assert _champion(html) == "Manager B"
