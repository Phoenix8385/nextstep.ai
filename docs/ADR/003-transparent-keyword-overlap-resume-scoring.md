# ADR 003 — Transparent keyword/skill-overlap resume scoring (v1) over an opaque LLM black-box score

## Status: Accepted

## Context

The **Resume Match** stage must produce a fit score between a user's resume
and each ingested posting so the dashboard can rank and filter jobs. Scoring
runs against every new posting for every active resume, so it executes at
ingestion volume (thousands of pairs per polling cycle), not just on user
request. The approach chosen determines cost, latency, explainability, and —
critically — whether the system might ever suggest skills the user does not
actually have.

## Decision

v1 scoring is a **transparent keyword/skill-overlap model**:

1. Extract a skill/keyword set from the resume using spaCy (tokenization,
   lemmatization, noun-chunk and named-entity extraction) matched against a
   curated skills taxonomy.
2. Extract the same from the job description.
3. Compute overlap metrics (weighted Jaccard over required vs. nice-to-have
   terms) and produce a 0–100 score.
4. Persist the score **together with its evidence**: matched skills, missing
   required skills, and missing nice-to-have skills.

The UI shows the score alongside "What matched" and "What's missing". The
system **never fabricates or suggests skills** that do not appear in the
user's resume; "missing" is displayed as information, not as text to add.

## Rationale

- **Explainable to the user.** Every score decomposes into concrete terms the
  user can verify against their own resume. This builds trust and lets users
  make an informed decision about whether a gap is real or a phrasing issue.
- **Cheap and deterministic.** spaCy runs locally in the Celery worker; scoring
  a resume/job pair costs milliseconds and zero external API spend. Results are
  reproducible, which makes tests and regression checks trivial.
- **No per-request LLM cost during ingestion.** At ingestion volume, calling
  an LLM per pair would be the dominant infrastructure cost and would couple
  ingestion throughput to a third-party rate limit.
- **No hallucination risk.** A keyword model cannot invent experience. This is
  a hard product principle ("no fabricated skills ever suggested") and is
  simplest to guarantee when the scorer is purely extractive.
- **Upgradeable.** The `match_scores` table stores `scorer_version` and the
  evidence payload. A v2 embedding-based scorer (or hybrid) can be introduced
  behind the same interface and A/B compared without changing the schema or
  the UI contract.

## Alternatives Rejected

- **LLM-generated fit score (prompt: "rate this resume against this job
  0–100").** Rejected: opaque, non-deterministic across runs, expensive at
  ingestion volume, subject to rate limits and outages, and prone to inventing
  justifications — including skills the user does not have.
- **Embedding cosine similarity (e.g. sentence-transformers) as the sole v1
  scorer.** Rejected for v1: a single similarity number is not explainable
  ("why 0.71?"), and dense similarity rewards topical overlap rather than
  actual skill possession. Planned as a v2 *supplement* to the overlap model,
  not a replacement.
- **Third-party resume-parsing / matching SaaS.** Rejected: recurring cost per
  parse, sends user resume content to an external vendor (privacy surface),
  and still yields a black-box score.
- **Pure TF-IDF cosine over raw text.** Rejected: cheap and deterministic but
  dominated by generic terms, hard to present as a skills list, and no notion
  of required vs. nice-to-have.

## Consequences

**Positive**

- Scoring is fast, free at the margin, and fully offline in the worker.
- Users see exactly why a job scored the way it did and can act on it honestly.
- The "no fabricated skills" guarantee is structurally enforced rather than
  prompt-enforced.
- Unit tests can assert exact scores for fixture resume/job pairs.

**Negative**

- Vocabulary sensitivity: "Postgres" vs. "PostgreSQL" vs. "SQL" require a
  maintained synonym/taxonomy layer, and gaps in it produce false "missing"
  skills.
- Cannot infer transferable or implied skills (e.g. a Django expert clearly
  knows Python even if "Python" is not listed). Scores will be conservative.
- Job descriptions written in unusual ways (heavy prose, few explicit skill
  terms) will score noisily.
- The curated skills taxonomy becomes a maintained asset with its own release
  cadence.
- Users may over-index on the numeric score; UI copy must frame it as a
  keyword-overlap indicator, not a hiring prediction.
