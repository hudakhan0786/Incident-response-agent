"""
Similarity engine.

Finds past incidents that resemble a new one, and - this is the part that
matters for trust - scores the resemblance across several independent
dimensions (the "incident fingerprint") instead of collapsing everything
into one opaque percentage. A responder deciding whether to trust a
suggestion at 3am needs to see *why* two incidents were judged alike:
same service, same error signature, same severity class, how stale the
precedent is - not just a black-box "87% match".

Text similarity uses TF-IDF + cosine similarity over incident titles,
descriptions, error signatures and root-cause summaries. This is
deliberately not a neural embedding model: it needs no download, no GPU,
and no network access, so the tool works the moment it's cloned - which
matters when you might be running it during an actual outage.
"""
from __future__ import annotations

from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

WEIGHTS = {
    "text_similarity": 0.40,
    "service_match": 0.20,
    "error_signature_match": 0.20,
    "severity_match": 0.10,
    "recency": 0.10,
}


def _corpus_text(incident) -> str:
    root_cause_text = " ".join((rc.summary or "") for rc in incident.root_causes)
    return " ".join(filter(None, [
        incident.title, incident.description, incident.error_signature,
        incident.service, root_cause_text,
    ]))


def find_similar_incidents(
    query_text: str,
    query_service: str,
    query_severity: str,
    query_error_sig: str,
    candidates: list,
    top_k: int = 5,
):
    """Returns a list of (incident, overall_score, fingerprint_dict), sorted desc."""
    if not candidates:
        return []

    corpus = [_corpus_text(c) for c in candidates]
    corpus.append(f"{query_text} {query_error_sig or ''} {query_service or ''}")

    vectorizer = TfidfVectorizer(stop_words="english", max_features=2000)
    try:
        tfidf = vectorizer.fit_transform(corpus)
    except ValueError:
        # corpus was entirely empty strings / stopwords - nothing to compare
        return []

    query_vec = tfidf[-1]
    doc_vecs = tfidf[:-1]
    text_sims = cosine_similarity(query_vec, doc_vecs).flatten()

    now = datetime.utcnow()
    scored = []
    for candidate, text_sim in zip(candidates, text_sims):
        service_match = 1.0 if candidate.service and query_service and \
            candidate.service.lower() == query_service.lower() else 0.0

        if candidate.error_signature and query_error_sig and \
                candidate.error_signature.lower() == query_error_sig.lower():
            error_match = 1.0
        elif text_sim > 0.2:
            error_match = 0.5
        else:
            error_match = 0.0

        cand_severity = getattr(candidate.severity, "value", candidate.severity)
        severity_match = 1.0 if cand_severity == query_severity else 0.5

        age_days = max((now - candidate.started_at).days, 0) if candidate.started_at else 999
        recency = max(0.0, 1 - age_days / 365)

        fingerprint = {
            "text_similarity": round(float(text_sim), 3),
            "service_match": service_match,
            "error_signature_match": error_match,
            "severity_match": severity_match,
            "recency": round(recency, 3),
        }
        overall = sum(fingerprint[k] * WEIGHTS[k] for k in WEIGHTS)

        if overall > 0.05:
            scored.append((candidate, round(overall, 3), fingerprint))

    scored.sort(key=lambda r: r[1], reverse=True)
    return scored[:top_k]
