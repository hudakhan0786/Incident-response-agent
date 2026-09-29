def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_dashboard_reports_seeded_data(client):
    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["resolved_incidents"] >= 10
    assert data["open_incidents"] >= 1
    assert len(data["top_runbooks"]) > 0


def test_suggest_finds_the_recurring_payments_incident(client):
    res = client.post("/api/search/suggest", json={
        "description": "payments-api throwing upstream 502 errors, connection pool looks saturated",
        "service": "payments-api",
        "severity": "SEV1",
        "error_signature": "502-upstream-timeout",
        "top_k": 3,
    })
    assert res.status_code == 200
    matches = res.json()["matches"]
    assert matches, "expected at least one historical match"
    assert matches[0]["fingerprint"]["service_match"] == 1.0
    assert matches[0]["recommended_runbooks"], "expected a linked runbook suggestion"


def test_full_incident_lifecycle(client):
    created = client.post("/api/incidents", json={
        "title": "Integration test incident",
        "description": "Something broke during a test run.",
        "service": "payments-api",
        "severity": "SEV3",
        "error_signature": "test-signature",
    }).json()
    incident_id = created["id"]
    assert created["status"] == "open"

    runbooks = client.get("/api/runbooks").json()
    rb_id = runbooks[0]["id"]

    step = client.post(f"/api/incidents/{incident_id}/steps", json={
        "minute_offset": 3,
        "actor": "tester",
        "step_type": "mitigation",
        "action_text": "Applied the fix",
        "runbook_id": rb_id,
    }).json()
    assert step["runbook_id"] == rb_id

    resolved = client.post(f"/api/incidents/{incident_id}/resolve").json()
    assert resolved["status"] == "resolved"
    assert resolved["mttr_minutes"] is not None

    pm = client.post(f"/api/incidents/{incident_id}/postmortem/generate").json()
    assert "Integration test incident" in pm["summary"]
    assert len(pm["action_items"]) > 0

    before = next(r for r in runbooks if r["id"] == rb_id)["elo_rating"]
    feedback = client.post(f"/api/runbooks/{rb_id}/feedback", json={
        "incident_id": incident_id,
        "outcome": "worked",
    }).json()
    assert feedback["elo_before"] == before
    assert feedback["elo_after"] > feedback["elo_before"]
    assert feedback["delta"] > 0

    listed = client.get("/api/postmortems").json()
    assert any(p["incident_id"] == incident_id for p in listed)


def test_feedback_rejects_unknown_outcome(client):
    runbooks = client.get("/api/runbooks").json()
    incidents = client.get("/api/incidents").json()
    res = client.post(f"/api/runbooks/{runbooks[0]['id']}/feedback", json={
        "incident_id": incidents[0]["id"],
        "outcome": "sort-of-worked-i-guess",
    })
    assert res.status_code == 400


def test_404_for_missing_incident(client):
    res = client.get("/api/incidents/999999")
    assert res.status_code == 404
