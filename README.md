# Incident Response Agent

**Institutional memory for on-call.** It remembers every past incident, the
runbooks used to fix them, and — this is the part most tools skip — whether
those runbooks actually worked. When a new incident comes in, it matches it
against history and tells you not just *what* worked before, but *how much
you should trust that answer under this specific kind of pressure.*

No external LLM, no API key, no internet connection required. Everything —
matching, ranking, drafting — runs locally and deterministically, on purpose:
the one moment you can't afford a flaky third-party call is during an outage.

---

## Why this is different from "a CRUD app with a search bar"

Most "incident memory" tools store history and let you full-text search it.
Two ideas here go further:

### 1. Runbook trust is an Elo rating, not a star rating

A runbook that's been run twice and "worked" twice looks identical to a
5-star-rated one — whether those two wins were against a full outage or
against a cosmetic non-issue. That's misleading.

So every runbook carries a **chess-style Elo rating**, starting at 1200. Each
time it's used, it "plays a match" against the incident's severity (a SEV1
is a strong opponent, a SEV4 is a weak one). Beating a strong opponent earns
real trust; beating a weak one barely moves the needle. The math is exactly
what chess federations use to rank players from a stream of sparse,
unevenly-matched games — which is precisely the shape of incident history.
See `app/elo.py` for the full rationale and the implementation.

Ratings also **decay toward baseline** the longer a runbook goes unused
(`elo.decayed_rating`), so the dashboard can flag things like *"this fixed a
SEV1 eight months ago and hasn't been touched since — validate it before you
trust it blindly."*

Try it yourself: open **Runbook Library** in the app, pick a severity next
to any runbook, and click **Worked**. Watch the gauge move live.

### 2. Matches come with an explainable fingerprint, not a black-box score

Instead of one opaque "87% match," every suggestion breaks similarity into
five independent axes — text similarity, service match, error-signature
match, severity match, and recency — rendered as a small radar chart. A
responder deciding whether to trust a 3am suggestion can see *why* it was
judged similar, not just that it was. See `app/similarity.py`.

---

## What it does end to end

1. **Log a new incident** → the fingerprint engine (TF-IDF + cosine
   similarity, no ML download required) checks it against every resolved
   incident on record and ranks the closest precedents, each with its
   Elo-ranked, explained runbook suggestions.
2. **Open the incident** → log response steps as they happen (the
   "black-box replay" timeline, with a play button that scrubs through
   what happened minute by minute).
3. **Mark it resolved** → MTTR is computed automatically.
4. **Generate a postmortem** → drafted deterministically from the incident's
   own timeline and root causes (a starting point, not a final write-up).
5. **Give feedback** on whichever runbook you used → its Elo rating updates
   in real time, so the next person who hits this fingerprint inherits a
   slightly better answer than you got.

The database ships pre-seeded with 16 realistic incidents across five
services (`payments-api`, `auth-service`, `redis-cache`, `cdn-edge`,
`checkout-worker`) so the app is immediately useful to click through — the
War Room isn't empty on first run.

---

## Architecture

```
incident-response-agent/
├── app/
│   ├── main.py           FastAPI app, static file serving, startup seeding
│   ├── models.py         SQLAlchemy ORM: Incident, RootCause, ResolutionStep,
│   │                     Runbook, RunbookUsage, Postmortem
│   ├── schemas.py        Pydantic request/response contracts
│   ├── database.py       SQLite engine/session (swap the URL for Postgres later)
│   ├── elo.py            The trust-rating engine (see above)
│   ├── similarity.py     TF-IDF fingerprint matching engine
│   ├── postmortem_gen.py Deterministic postmortem drafting from timeline data
│   ├── seed_data.py      Realistic demo dataset, replayed through elo.py itself
│   ├── routers/          incidents, runbooks, search, dashboard, postmortems
│   └── static/           Vanilla HTML/CSS/JS frontend (no build step)
├── tests/                 pytest: elo math, similarity ranking, full API flows
├── requirements.txt
└── run.py                 convenience entrypoint
```

**Backend:** FastAPI + SQLAlchemy + SQLite + scikit-learn (TF-IDF only — no
GPU, no network, no large model download).

**Frontend:** vanilla HTML/CSS/JS, hash-routed, served directly by FastAPI
as static files. No `npm install`, no build step — the whole app runs from
one `uvicorn` command. Design language deliberately avoids generic
dashboard chrome: ratings are drawn as instrument-panel gauges, matches as
a literal radar sweep, and incident timelines as a flight-recorder tape.

---

## Running it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python run.py
# or: uvicorn app.main:app --reload
```

Then open **http://localhost:8000**. The database is created and seeded
automatically on first run (`data/incidents.db`). Delete that file to reset
to a fresh seeded state.

### Hindsight memory (optional)

The app can use a running [Hindsight](https://hindsight.vectorize.io/) server
as its persistent incident-memory layer. Set these environment variables
before starting the app:

```powershell
$env:HINDSIGHT_API_URL = "http://localhost:8888"
$env:HINDSIGHT_BANK_ID = "incident-response-agent"
# For a hosted Hindsight instance, also set its API key:
$env:HINDSIGHT_API_KEY = "your-api-key"
python run.py
```

When configured, resolving an incident retains its symptoms, root causes,
and response timeline in the configured bank. New incident suggestions
recall relevant memories alongside the app's local fingerprint matches. The
health endpoint reports whether Hindsight is configured at `/api/health`.
Without `HINDSIGHT_API_URL`, the app runs as before with local SQLite and
TF-IDF matching. Hindsight performs memory extraction and reflection through
an LLM on its server; the incident app keeps Elo scoring and similarity
matching deterministic and local.

### Running the tests

```bash
pytest
```

17 tests cover the Elo math (does beating a stronger "opponent" really earn
more trust, does a rating decay correctly, are labels monotonic), the
similarity engine (does the same-service/same-signature incident actually
rank first), and full API lifecycles (create → suggest → step → resolve →
postmortem → feedback).

---

## A suggested demo script

1. **War Room** — point out the two live open incidents and the "needs
   re-validation" panel; explain that number is driven by real Elo decay,
   not a hardcoded flag.
2. **New Incident** — paste in a payments-api 502 description. Watch the
   radar-chart fingerprints render and the Elo-ranked runbook come back
   with a plain-English "why."
3. Open the new incident, log a step, **mark it resolved**, click
   **Generate postmortem** — show that it's built entirely from the
   timeline you just typed, not an LLM guess.
4. **Runbook Library** — pick a runbook, simulate a **Worked** outcome
   against a SEV1, and watch the gauge animate live. Then simulate a
   **Failed** outcome against a SEV4 and point out it costs *more* trust
   than failing against a SEV1 would — that's the whole idea in one click.

---

## Honest limitations

- TF-IDF similarity is lexical, not semantic — a incident described in
  very different words won't match well even if the root cause is
  identical. A future version could add a pluggable embedding backend
  behind the same `similarity.find_similar_incidents` interface.
- Postmortem drafts are template-based on purpose (deterministic, offline,
  no hallucination risk) — they're a first draft, not a substitute for a
  human blameless review.
- Single SQLite file: fine for a team or a demo; swap `DATABASE_URL` for
  Postgres before this holds a whole org's incident history.
