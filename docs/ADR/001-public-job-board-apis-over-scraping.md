# ADR 001 — Use public job-board APIs (Greenhouse / Lever / Ashby) instead of general web scraping

## Status: Accepted

## Context

NextStep.ai needs a continuous feed of job postings to populate the `jobs`
table that every downstream feature (dashboard, resume matching, application
tracking) depends on. There are two broad ways to obtain postings:

1. Scrape company career pages and job aggregators with an HTML crawler.
2. Consume the public, unauthenticated JSON endpoints exposed by applicant
   tracking systems (ATS) that companies embed on their career sites —
   specifically Greenhouse (`boards-api.greenhouse.io`), Lever
   (`api.lever.co/v0/postings`) and Ashby (`api.ashbyhq.com/posting-api`).

The decision affects ingestion reliability, legal exposure, build effort, and
how cleanly postings can be normalized and deduplicated by `content_hash`.

## Decision

Ingest postings exclusively from public ATS job-board APIs. Greenhouse is
implemented first, then Lever, then Ashby, with room for two more sources
later (target: 3–5 total). Each source has a dedicated fetcher that maps its
JSON schema into the single normalized `jobs` table. No HTML scraping is
performed anywhere in the platform.

## Rationale

- **Stable, structured JSON.** Each ATS publishes a documented schema with
  consistent fields (title, location, department, description, absolute URL,
  updated timestamp). Normalizers are simple, typed mappings rather than
  brittle CSS/XPath selectors.
- **No scraping or Terms-of-Service risk.** These endpoints exist so that
  companies can render their own job boards. They are unauthenticated, rate
  tolerant, and intended for public consumption. We never bypass `robots.txt`,
  CAPTCHAs, or anti-bot measures.
- **Faster to build.** A source integration is a few hundred lines: an HTTP
  client, a Pydantic model for the response, a normalizer, and a Celery task.
  There is no headless browser, no proxy rotation, no layout-change firefighting.
- **Reliable deduplication.** Because fields arrive structured, the
  `content_hash` (over normalized title + company + location + description)
  is deterministic and stable across polling runs.
- **Coverage is sufficient for v1.** Greenhouse, Lever and Ashby together power
  the career pages of a large share of tech companies, which is the initial
  target user segment.

## Alternatives Rejected

- **General HTML scraping of career pages.** Rejected: layout drift breaks
  parsers constantly, many sites render jobs client-side (requiring headless
  browsers), aggressive anti-bot tooling causes silent data loss, and most
  sites' ToS prohibit automated access. Maintenance cost would dominate the
  roadmap.
- **Scraping aggregators (LinkedIn, Indeed, Glassdoor).** Rejected: explicit
  ToS prohibitions, active legal enforcement history, and heavy anti-scraping
  infrastructure. Unacceptable legal and reliability risk.
- **Paid job-data aggregators / commercial APIs.** Rejected for v1: recurring
  cost before product-market fit, licensing restrictions on storing and
  re-displaying data, and less control over freshness. May be revisited as an
  additional source once the normalization layer is proven.
- **User-submitted job URLs only.** Rejected as the *sole* source: no discovery
  value, which is the core promise of the product. (Manual URL entry may still
  be supported as a supplementary feature.)

## Consequences

**Positive**

- Ingestion is deterministic, testable with recorded fixtures, and cheap to run
  on a Celery beat schedule.
- No legal or ethical ambiguity about how postings are obtained.
- Adding a new ATS source is an isolated, well-understood task.
- Clean structured data makes v1 keyword matching and future embedding-based
  matching straightforward.

**Negative**

- Coverage is limited to companies that use a supported ATS; postings on custom
  career sites or unsupported ATSs (e.g. Workday, iCIMS, SmartRecruiters) are
  invisible until a source is added.
- We must maintain a list of company board tokens/slugs per source; discovering
  new companies is a manual or semi-manual process.
- ATS vendors may change or deprecate endpoints without notice; each fetcher
  needs schema validation and alerting on parse failures.
- Posting freshness is bounded by our polling interval, not real time.
