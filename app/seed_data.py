"""
Populates a fresh database with a believable incident history so the tool
is immediately useful to click through, instead of opening to an empty
dashboard. Elo ratings below are *not* hand-typed - they are produced by
replaying each runbook's real usage history through the same elo.update_elo()
function the live API uses, in chronological order. What you see in the
Runbook Library is exactly what the engine would have produced organically.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import elo, models
from app.postmortem_gen import generate_postmortem

NOW = datetime.utcnow()

RUNBOOK_DEFS = {
    "restart_pool": dict(
        title="Restart payment worker pool with drained connections",
        service="payments-api",
        tags="restart,connection-pool,payments",
        content=(
            "1. Confirm connection-pool utilization is at/near 100% on the payments-api dashboard.\n"
            "2. Drain in-flight connections on one worker at a time (do not hard-kill).\n"
            "3. Restart the drained worker; wait for health check to pass before moving to the next.\n"
            "4. Repeat across the pool; watch error rate fall between each restart.\n"
            "5. If pool saturates again within the hour, escalate to capacity review."
        ),
    ),
    "rollback_deploy": dict(
        title="Roll back last deploy via canary controller",
        service="payments-api",
        tags="deploy,rollback,canary",
        content=(
            "1. Open the canary controller and identify the last completed rollout.\n"
            "2. Trigger `rollback` for the affected service; confirm target revision.\n"
            "3. Watch p50/p99 latency return to the pre-deploy baseline (~5-10 min).\n"
            "4. Freeze further deploys to this service until root cause is confirmed."
        ),
    ),
    "rotate_jwt_key": dict(
        title="Rotate expired JWT signing key",
        service="auth-service",
        tags="auth,jwt,key-rotation",
        content=(
            "1. Confirm the failure signature is invalid-signature, not expired-token.\n"
            "2. Re-publish the previous signing key alongside the new one (dual-key window).\n"
            "3. Force downstream services to refresh their JWKS cache.\n"
            "4. Once error rate clears, retire the old key on its normal schedule, staggered."
        ),
    ),
    "scale_auth": dict(
        title="Scale auth-service replicas +50%",
        service="auth-service",
        tags="capacity,scaling,auth",
        content=(
            "1. Check CPU/connection saturation across auth-service replicas.\n"
            "2. Increase replica count by 50% via the scaling console.\n"
            "3. Confirm new replicas pass health checks and join the load balancer.\n"
            "4. Monitor 5xx rate for 10 minutes before standing down."
        ),
    ),
    "redis_failover": dict(
        title="Failover Redis primary to replica",
        service="redis-cache",
        tags="redis,failover,cache",
        content=(
            "1. Confirm primary is refusing connections or has failed health checks.\n"
            "2. Promote the most caught-up replica to primary.\n"
            "3. Repoint client connection strings / service discovery to the new primary.\n"
            "4. Pull the old primary out of rotation for investigation, don't reuse yet."
        ),
    ),
    "flush_redis": dict(
        title="Flush and warm Redis cache cluster",
        service="redis-cache",
        tags="redis,cache,consistency",
        content=(
            "1. Confirm stale/incorrect reads rather than an outage (check replication lag).\n"
            "2. Flush the affected keyspace, not the entire cluster if avoidable.\n"
            "3. Run the cache-warm job for high-traffic keys.\n"
            "4. Spot-check a sample of previously-stale keys against source of truth."
        ),
    ),
    "purge_cdn": dict(
        title="Purge CDN edge cache for affected paths",
        service="cdn-edge",
        tags="cdn,cache,invalidation",
        content=(
            "1. Identify the affected path prefix (images, pricing fragments, etc).\n"
            "2. Submit a targeted purge for that prefix - avoid a full-cache purge under load.\n"
            "3. Verify fresh content from three edge PoPs, not just your local one.\n"
            "4. If this is a recurring path, propose a shorter TTL instead of purging by hand."
        ),
    ),
    "repoint_broker": dict(
        title="Re-point checkout-worker queue consumer to backup broker",
        service="checkout-worker",
        tags="queue,broker,failover",
        content=(
            "1. Confirm primary broker cluster is degraded (missing node / rebalancing stalled).\n"
            "2. Point the checkout-worker consumer group at the backup broker endpoint.\n"
            "3. Confirm queue depth is draining, not just holding steady.\n"
            "4. Reconcile any in-flight messages once primary broker recovers."
        ),
    ),
    "scale_checkout_concurrency": dict(
        title="Increase checkout-worker concurrency limit",
        service="checkout-worker",
        tags="capacity,concurrency,queue",
        content=(
            "1. Confirm queue lag is throughput-bound, not caused by a broker issue.\n"
            "2. Raise the consumer concurrency limit one step at a time.\n"
            "3. Watch downstream dependency error rates - concurrency bumps can shift load elsewhere.\n"
            "4. Record the new limit as the working baseline if stable for 30+ minutes."
        ),
    ),
    "rate_limit_abuse": dict(
        title="Apply emergency rate-limit to abusive client",
        service="payments-api",
        tags="rate-limit,abuse,partner",
        content=(
            "1. Identify the offending client/API key from the failed-request breakdown.\n"
            "2. Apply a temporary per-client rate limit well below their burst rate.\n"
            "3. Notify the partner/team owning that client with the observed pattern.\n"
            "4. Lift the limit once they confirm a fix, not on a timer."
        ),
    ),
}

INCIDENTS = [
    dict(key="inc1", title="Checkout API 502s during flash sale", service="payments-api",
         severity="SEV1", error_signature="502-upstream-timeout", days_ago=340, mttr=47,
         description=("Payment worker pool exhausted its connection limit during a flash-sale "
                       "traffic spike, causing upstream 502s for roughly 9% of checkout requests."),
         root_causes=[("capacity", "Connection pool sized for average traffic, not promotional spikes")],
         steps=[
             (0, "PagerDuty", "detection", "Error-rate alert fired: 502 rate crossed 5% on payments-api.", None, None),
             (4, "Priya", "diagnosis", "Confirmed connection pool at 100% utilization; no recent deploys.", None, None),
             (9, "Priya", "mitigation", "Restarted payment worker pool with drained connections.", "restart_pool", "worked"),
             (18, "Priya", "communication", "Posted status update; error rate dropping.", None, None),
             (47, "Priya", "resolution", "Error rate back to baseline; incident closed.", None, None),
         ], postmortem=True),

    dict(key="inc2", title="Checkout API 502s again during Black Friday ramp", service="payments-api",
         severity="SEV1", error_signature="502-upstream-timeout", days_ago=180, mttr=22,
         description="Same 502 signature recurring under load, this time during Black Friday ramp-up.",
         root_causes=[("capacity", "Pool limit was still static despite the prior incident's action item")],
         steps=[
             (0, "Datadog", "detection", "502 rate alert fired again on payments-api.", None, None),
             (3, "Marco", "diagnosis", "Pattern matched an earlier flash-sale 502 incident immediately via fingerprint search.", None, None),
             (6, "Marco", "mitigation", "Restarted payment worker pool with drained connections.", "restart_pool", "worked"),
             (22, "Marco", "resolution", "Error rate normal; escalated pool auto-scaling as a hard requirement.", None, None),
         ], postmortem=False),

    dict(key="inc3", title="Payments latency spike after v2.14 deploy", service="payments-api",
         severity="SEV2", error_signature="latency-p99-deploy", days_ago=95, mttr=35,
         description="p99 latency roughly tripled within ten minutes of the v2.14 deploy completing.",
         root_causes=[("deploy", "A new serialization path in v2.14 added a blocking call on the request path")],
         steps=[
             (0, "Prometheus", "detection", "p99 latency alert fired.", None, None),
             (5, "Priya", "diagnosis", "Correlated spike start with the v2.14 deploy timestamp.", None, None),
             (10, "Priya", "mitigation", "Rolled back last deploy via canary controller.", "rollback_deploy", "worked"),
             (35, "Priya", "resolution", "Latency restored to baseline; deploy blocked pending a fix.", None, None),
         ], postmortem=False),

    dict(key="inc4", title="Payments latency regression, second deploy attempt", service="payments-api",
         severity="SEV2", error_signature="latency-p99-deploy", days_ago=90, mttr=15,
         description="Re-deploy of v2.14.1 with a partial fix still showed a smaller latency bump.",
         root_causes=[("deploy", "The fix reduced but did not eliminate the blocking call")],
         steps=[
             (0, "Marco", "detection", "Latency dashboard flagged a smaller but real regression.", None, None),
             (4, "Marco", "mitigation", "Rolled back last deploy via canary controller.", "rollback_deploy", "partial"),
             (15, "Marco", "resolution", "Rolled back fully; latency normal; fix reopened.", None, None),
         ], postmortem=False),

    dict(key="inc5", title="Auth service 500s after signing key rotation", service="auth-service",
         severity="SEV1", error_signature="jwt-invalid-signature", days_ago=210, mttr=28,
         description=("Tokens issued before a scheduled signing-key rotation were rejected by services "
                       "that were still caching the old public key."),
         root_causes=[("config", "Key rotation was not staggered across dependent services")],
         steps=[
             (0, "PagerDuty", "detection", "Spike in 401/500 responses across services validating JWTs.", None, None),
             (5, "Dana", "diagnosis", "Traced to the signing-key rotation twelve minutes earlier.", None, None),
             (11, "Dana", "mitigation", "Rotated expired JWT signing key.", "rotate_jwt_key", "worked"),
             (28, "Dana", "resolution", "Error rate back to normal; added staggered rotation to action items.", None, None),
         ], postmortem=True),

    dict(key="inc6", title="Auth service login failures under regional traffic surge", service="auth-service",
         severity="SEV2", error_signature="auth-5xx-load", days_ago=60, mttr=19,
         description="A regional marketing push drove roughly 4x normal login volume, saturating replicas.",
         root_causes=[("capacity", "Replica count was set for steady-state traffic, not campaign traffic")],
         steps=[
             (0, "Datadog", "detection", "5xx rate alert on auth-service.", None, None),
             (4, "Dana", "diagnosis", "CPU on all replicas pegged above 95%.", None, None),
             (8, "Dana", "mitigation", "Scaled auth-service replicas +50%.", "scale_auth", "worked"),
             (19, "Dana", "resolution", "Latency and error rate normalized.", None, None),
         ], postmortem=False),

    dict(key="inc7", title="Login errors during app-store feature spotlight", service="auth-service",
         severity="SEV3", error_signature="auth-5xx-load", days_ago=12, mttr=14,
         description="An app-store editorial placement drove a short but sharp signup surge.",
         root_causes=[("capacity", "Same headroom gap as the earlier regional-surge incident - auto-scaling still wasn't in place")],
         steps=[
             (0, "Marco", "detection", "5xx alert on auth-service, smaller magnitude than the regional-surge incident.", None, None),
             (5, "Marco", "mitigation", "Scaled auth-service replicas +50%.", "scale_auth", "worked"),
             (14, "Marco", "resolution", "Normal within minutes; flagged auto-scaling as overdue.", None, None),
         ], postmortem=False),

    dict(key="inc8", title="Checkout stuck: Redis cache cluster unresponsive", service="redis-cache",
         severity="SEV1", error_signature="redis-connection-refused", days_ago=150, mttr=41,
         description=("The primary Redis node stopped accepting connections, stalling every service "
                       "that reads session or cart state through it."),
         root_causes=[("dependency", "Primary node hit max memory and began refusing writes, then reads")],
         steps=[
             (0, "PagerDuty", "detection", "connection-refused errors spiking across payments-api and checkout-worker.", None, None),
             (6, "Priya", "diagnosis", "Redis primary at 100% memory, evictions failing.", None, None),
             (12, "Priya", "mitigation", "Failed over Redis primary to replica.", "redis_failover", "worked"),
             (41, "Priya", "resolution", "Traffic recovered on the new primary; old node pulled from rotation.", None, None),
         ], postmortem=True),

    dict(key="inc9", title="Stale cart data served from Redis after failover", service="redis-cache",
         severity="SEV3", error_signature="redis-stale-read", days_ago=148, mttr=25,
         description="Two days after the Redis failover incident, some users saw stale cart contents from replication lag.",
         root_causes=[("dependency", "The promoted replica had fallen behind and wasn't fully caught up")],
         steps=[
             (0, "Support ticket", "detection", "Customer reports of vanished cart items.", None, None),
             (10, "Dana", "diagnosis", "Confirmed stale reads from the recently-promoted replica.", None, None),
             (15, "Dana", "mitigation", "Flushed and warmed Redis cache cluster.", "flush_redis", "worked"),
             (25, "Dana", "resolution", "Carts repopulated from source of truth and verified.", None, None),
         ], postmortem=False),

    dict(key="inc10", title="Product images not updating on CDN", service="cdn-edge",
         severity="SEV4", error_signature="cdn-stale-asset", days_ago=70, mttr=9,
         description="Updated product photography wasn't reflected on the storefront for about 40 minutes.",
         root_causes=[("config", "Cache-Control headers set a longer TTL than the publish workflow assumed")],
         steps=[
             (0, "Support ticket", "detection", "Merchandising team reported stale images.", None, None),
             (3, "Marco", "mitigation", "Purged CDN edge cache for affected paths.", "purge_cdn", "worked"),
             (9, "Marco", "resolution", "Fresh assets confirmed live from three PoPs.", None, None),
         ], postmortem=False),

    dict(key="inc11", title="Storefront serving stale pricing after promo update", service="cdn-edge",
         severity="SEV3", error_signature="cdn-stale-asset", days_ago=8, mttr=11,
         description="The same stale-cache signature surfaced again, this time on promo pricing fragments.",
         root_causes=[("config", "The TTL fix from the earlier stale-image incident was applied to images only, not pricing")],
         steps=[
             (0, "Dana", "detection", "Pricing team flagged mismatched promo prices.", None, None),
             (4, "Dana", "mitigation", "Purged CDN edge cache for affected paths.", "purge_cdn", "worked"),
             (11, "Dana", "resolution", "Correct pricing confirmed; TTL fix broadened to all fragment types.", None, None),
         ], postmortem=False),

    dict(key="inc12", title="Checkout queue backing up, orders delayed", service="checkout-worker",
         severity="SEV2", error_signature="queue-consumer-lag", days_ago=40, mttr=33,
         description="The primary message broker had a partial outage and the consumer fell far behind.",
         root_causes=[("dependency", "Primary broker cluster lost a node and rebalancing stalled consumers")],
         steps=[
             (0, "Datadog", "detection", "Queue-depth alert fired for checkout-worker.", None, None),
             (7, "Priya", "diagnosis", "Broker cluster status page showed a missing node.", None, None),
             (14, "Priya", "mitigation", "Re-pointed checkout-worker queue consumer to backup broker.", "repoint_broker", "worked"),
             (33, "Priya", "resolution", "Queue drained; orders processing normally again.", None, None),
         ], postmortem=True),

    dict(key="inc13", title="Checkout queue lag during routine peak hour", service="checkout-worker",
         severity="SEV3", error_signature="queue-consumer-lag", days_ago=5, mttr=17,
         description="Ordinary peak-hour volume outpaced consumer throughput; no broker issue this time.",
         root_causes=[("capacity", "Consumer concurrency was left at its launch-day default")],
         steps=[
             (0, "Marco", "detection", "Queue depth climbing steadily, no broker anomalies.", None, None),
             (6, "Marco", "diagnosis", "Ruled out broker failure - a different fingerprint than the broker-outage incident.", None, None),
             (9, "Marco", "mitigation", "Increased checkout-worker concurrency limit.", "scale_checkout_concurrency", "worked"),
             (17, "Marco", "resolution", "Queue depth back to normal.", None, None),
         ], postmortem=False),

    dict(key="inc14", title="Suspicious burst of failed payments from one client", service="payments-api",
         severity="SEV3", error_signature="payments-abuse-burst", days_ago=260, mttr=54,
         description=("A single API client sent an abnormal burst of failing payment attempts, "
                       "consuming capacity and triggering false alarms."),
         root_causes=[("human-error", "A partner's retry loop had no backoff after their own deploy")],
         steps=[
             (0, "Datadog", "detection", "Failed-payment rate alert, isolated to one client ID.", None, None),
             (10, "Dana", "diagnosis", "Confirmed a single client responsible for 90% of failures.", None, None),
             (20, "Dana", "mitigation", "Applied emergency rate-limit to abusive client.", "rate_limit_abuse", "worked"),
             (54, "Dana", "resolution", "Partner notified and fixed their retry logic; limit lifted.", None, None),
         ], postmortem=False),

    # --- currently open, for the War Room view ---
    dict(key="inc15", title="Elevated 5xx rate on checkout-worker", service="checkout-worker",
         severity="SEV2", error_signature="queue-consumer-lag", days_ago=0, minutes_ago=35, mttr=None,
         description="Queue depth climbing again; still confirming whether this matches #12 or #13's pattern.",
         root_causes=[], open=True,
         steps=[
             (0, "PagerDuty", "detection", "Queue-depth alert fired for checkout-worker.", None, None),
             (6, "Priya", "diagnosis", "Checking broker status and consumer concurrency; not yet conclusive.", None, None),
         ], postmortem=False),

    dict(key="inc16", title="Payments API returning 502s", service="payments-api",
         severity="SEV1", error_signature="502-upstream-timeout", days_ago=0, minutes_ago=8, mttr=None,
         description="502 rate alert just fired on payments-api, magnitude still being assessed.",
         root_causes=[], open=True,
         steps=[
             (0, "PagerDuty", "detection", "502 rate alert fired on payments-api.", None, None),
         ], postmortem=False),
]


def _apply_usage(db: Session, rb: models.Runbook, incident: models.Incident, outcome: str, used_at: datetime):
    severity = getattr(incident.severity, "value", incident.severity)
    new_rating, _ = elo.update_elo(rb.elo_rating, severity, outcome)
    usage = models.RunbookUsage(
        runbook_id=rb.id, incident_id=incident.id, outcome=outcome,
        elo_before=rb.elo_rating, elo_after=new_rating, used_at=used_at,
    )
    db.add(usage)
    rb.elo_rating = new_rating
    rb.times_used += 1
    if outcome == "worked":
        rb.times_worked += 1
    rb.last_used_at = used_at
    rb.last_validated_at = used_at


def seed(db: Session):
    if db.query(models.Incident).count() > 0:
        return  # already seeded

    runbooks = {}
    for key, defn in RUNBOOK_DEFS.items():
        rb = models.Runbook(elo_rating=1200.0, created_at=NOW - timedelta(days=400), **defn)
        db.add(rb)
        runbooks[key] = rb
    db.flush()

    # oldest first, so Elo history accumulates in real chronological order
    ordered = sorted(INCIDENTS, key=lambda d: d["days_ago"], reverse=True)

    for spec in ordered:
        if spec.get("open"):
            started = NOW - timedelta(minutes=spec.get("minutes_ago", 30))
        else:
            started = NOW - timedelta(days=spec["days_ago"])

        incident = models.Incident(
            title=spec["title"],
            description=spec["description"],
            service=spec["service"],
            error_signature=spec["error_signature"],
            severity=spec["severity"],
            status=models.Status.OPEN if spec.get("open") else models.Status.RESOLVED,
            started_at=started,
            created_by="on-call",
        )
        if not spec.get("open"):
            incident.resolved_at = started + timedelta(minutes=spec["mttr"])
            incident.mttr_minutes = spec["mttr"]

        for category, summary in spec["root_causes"]:
            incident.root_causes.append(models.RootCause(category=category, summary=summary))

        db.add(incident)
        db.flush()

        for minute_offset, actor, step_type, text, runbook_key, outcome in spec["steps"]:
            rb = runbooks.get(runbook_key) if runbook_key else None
            step = models.ResolutionStep(
                incident_id=incident.id, minute_offset=minute_offset, actor=actor,
                step_type=step_type, action_text=text,
                runbook_id=rb.id if rb else None,
            )
            db.add(step)
            if rb and outcome:
                _apply_usage(db, rb, incident, outcome, started + timedelta(minutes=minute_offset))

        db.flush()

        if spec.get("postmortem"):
            draft = generate_postmortem(incident)
            db.add(models.Postmortem(incident_id=incident.id, **draft))

    db.commit()
