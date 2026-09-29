from datetime import datetime, timedelta
from types import SimpleNamespace

from app import similarity


def make_incident(title, description, service, error_signature, severity, days_ago, root_causes=None):
    return SimpleNamespace(
        title=title,
        description=description,
        service=service,
        error_signature=error_signature,
        severity=SimpleNamespace(value=severity),
        started_at=datetime.utcnow() - timedelta(days=days_ago),
        root_causes=[SimpleNamespace(summary=s) for s in (root_causes or [])],
    )


CANDIDATES = [
    make_incident(
        "Checkout API 502s during flash sale",
        "Payment worker pool exhausted its connection limit during a spike.",
        "payments-api", "502-upstream-timeout", "SEV1", 30,
    ),
    make_incident(
        "Auth service login failures",
        "Replica CPU saturated under a regional traffic surge.",
        "auth-service", "auth-5xx-load", "SEV2", 10,
    ),
    make_incident(
        "Stale product images on CDN",
        "Cache-Control TTL was longer than the publish workflow assumed.",
        "cdn-edge", "cdn-stale-asset", "SEV4", 5,
    ),
]


def test_best_match_is_the_same_service_and_signature():
    matches = similarity.find_similar_incidents(
        query_text="payments-api is returning 502 upstream timeouts, connection pool looks saturated",
        query_service="payments-api",
        query_severity="SEV1",
        query_error_sig="502-upstream-timeout",
        candidates=CANDIDATES,
        top_k=3,
    )
    assert matches, "expected at least one match"
    top_incident, top_score, fingerprint = matches[0]
    assert top_incident.service == "payments-api"
    assert fingerprint["service_match"] == 1.0
    assert fingerprint["error_signature_match"] == 1.0
    assert top_score == max(m[1] for m in matches)


def test_results_are_sorted_descending_by_score():
    matches = similarity.find_similar_incidents(
        query_text="login errors, replicas at high cpu during a traffic surge",
        query_service="auth-service",
        query_severity="SEV2",
        query_error_sig="auth-5xx-load",
        candidates=CANDIDATES,
        top_k=5,
    )
    scores = [m[1] for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_no_candidates_returns_empty_list():
    assert similarity.find_similar_incidents("anything", "svc", "SEV3", "sig", [], top_k=5) == []


def test_fingerprint_has_all_five_dimensions():
    matches = similarity.find_similar_incidents(
        query_text="stale images not updating on the storefront",
        query_service="cdn-edge",
        query_severity="SEV4",
        query_error_sig="cdn-stale-asset",
        candidates=CANDIDATES,
        top_k=1,
    )
    _, _, fingerprint = matches[0]
    assert set(fingerprint) == {
        "text_similarity", "service_match", "error_signature_match",
        "severity_match", "recency",
    }
