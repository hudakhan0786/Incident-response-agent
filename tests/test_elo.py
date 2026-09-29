from app import elo


def test_starting_rating_is_neutral():
    assert elo.STARTING_RATING == 1200.0


def test_win_against_hard_incident_gains_more_than_easy_incident():
    _, delta_hard = elo.update_elo(1200.0, "SEV1", "worked")
    _, delta_easy = elo.update_elo(1200.0, "SEV4", "worked")
    assert delta_hard > delta_easy > 0


def test_failure_against_easy_incident_costs_more_than_hard_incident():
    _, delta_hard = elo.update_elo(1200.0, "SEV1", "failed")
    _, delta_easy = elo.update_elo(1200.0, "SEV4", "failed")
    assert delta_easy < delta_hard < 0


def test_partial_outcome_is_between_worked_and_failed():
    _, d_work = elo.update_elo(1200.0, "SEV2", "worked")
    _, d_partial = elo.update_elo(1200.0, "SEV2", "partial")
    _, d_fail = elo.update_elo(1200.0, "SEV2", "failed")
    assert d_fail < d_partial < d_work


def test_rating_is_clamped():
    low, _ = elo.update_elo(elo.MIN_RATING, "SEV4", "failed")
    high, _ = elo.update_elo(elo.MAX_RATING, "SEV1", "worked")
    assert low >= elo.MIN_RATING
    assert high <= elo.MAX_RATING


def test_decay_pulls_toward_baseline_over_time():
    fresh = elo.decayed_rating(1800.0, 0)
    stale = elo.decayed_rating(1800.0, elo.DECAY_HALF_LIFE_DAYS * 3)
    assert fresh == 1800.0
    assert elo.STARTING_RATING < stale < fresh


def test_trust_labels_are_monotonic_with_rating():
    ratings = [500, 1000, 1250, 1500, 1800]
    labels = [elo.trust_label(r) for r in ratings]
    order = ["Deprecated", "Shaky", "Unproven", "Reliable", "Battle-tested"]
    assert labels == order
