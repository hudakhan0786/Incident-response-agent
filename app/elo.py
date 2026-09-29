"""
Elo-style trust rating for runbooks.

The problem this solves: a runbook that has been run twice and worked twice
looks identical to one that has been run twice and worked twice *on trivial
SEV4 blips* if all you track is a success percentage. That's misleading -
teams end up trusting a runbook that has never actually been proven under
fire.

So instead of a raw success rate, every runbook carries a chess-style Elo
rating. Each time it is used, it "plays a match" against the incident it was
used on, where the incident's severity stands in for the strength of the
opponent (a SEV1 is a strong opponent; a SEV4 is a weak one). Beating a
strong opponent (successfully resolving a high-severity incident) gains far
more rating than beating a weak one, and losing to a weak opponent (failing
on a routine incident) costs far more than losing to a strong one. This is
the same math chess federations use to rank players from a stream of
one-off, unevenly-matched games - which is exactly the shape of incident
history: sparse, noisy, and never a controlled experiment.

Ratings start at 1200 (an untested runbook). They drift up with proven
successes on real incidents and drift down with failures, converging toward
a number that reflects "how much should I trust this under pressure" rather
than "how many times has someone clicked yes."
"""
from __future__ import annotations

SEVERITY_DIFFICULTY = {
    "SEV1": 1600,  # full outage - a strong "opponent"
    "SEV2": 1400,
    "SEV3": 1200,
    "SEV4": 1000,  # minor / cosmetic - a weak "opponent"
}

OUTCOME_SCORE = {
    "worked": 1.0,
    "partial": 0.5,
    "failed": 0.0,
}

STARTING_RATING = 1200.0
K_FACTOR = 28.0  # lower than standard chess (32) - incident samples are scarce,
                 # so we damp swing a bit to avoid one fluke dominating the score
MIN_RATING = 600.0
MAX_RATING = 2400.0

# Rating decays toward the 1200 baseline the longer a runbook goes unused,
# modelling the very real fact that infra drifts and a runbook that hasn't
# been exercised in months is a weaker bet than its historical score alone
# suggests. See decayed_rating().
DECAY_HALF_LIFE_DAYS = 120


def expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expectation: P(a beats b)."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo(runbook_rating: float, severity: str, outcome: str) -> tuple[float, float]:
    """Apply one match result. Returns (new_rating, delta)."""
    opponent = SEVERITY_DIFFICULTY.get(severity, 1200)
    actual = OUTCOME_SCORE.get(outcome, 0.0)
    expected = expected_score(runbook_rating, opponent)
    new_rating = runbook_rating + K_FACTOR * (actual - expected)
    new_rating = max(MIN_RATING, min(MAX_RATING, new_rating))
    return round(new_rating, 1), round(new_rating - runbook_rating, 1)


def decayed_rating(rating: float, days_since_last_use: float | None) -> float:
    """Pull a stale rating back toward the 1200 baseline over time."""
    if days_since_last_use is None:
        return rating
    if days_since_last_use <= 0:
        return rating
    decay_factor = 0.5 ** (days_since_last_use / DECAY_HALF_LIFE_DAYS)
    return round(STARTING_RATING + (rating - STARTING_RATING) * decay_factor, 1)


def trust_label(rating: float) -> str:
    if rating >= 1700:
        return "Battle-tested"
    if rating >= 1400:
        return "Reliable"
    if rating >= 1200:
        return "Unproven"
    if rating >= 900:
        return "Shaky"
    return "Deprecated"


def freshness(days_since_last_use: float | None) -> float:
    """0-1 score of how recently-validated a runbook is, for the decay meter."""
    if days_since_last_use is None:
        return 0.0
    return round(0.5 ** (days_since_last_use / DECAY_HALF_LIFE_DAYS), 3)
