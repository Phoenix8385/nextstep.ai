# ADR 004 — Manual application status updates (v1) over automatic Gmail/Outlook parsing

## Status: Accepted

## Context

The **Tracker** stage records each application's progress (applied →
screening → interview → offer / rejected / withdrawn) and every transition is
written to `application_events` in the same transaction as the status change.
The question is *how* transitions are captured. Employers communicate status
almost exclusively by email, so the tempting approach is to connect the
user's Gmail or Outlook inbox, classify incoming messages, and update statuses
automatically. This decision determines the OAuth scopes the platform
requests, the compliance work required before launch, and how much of the
roadmap is spent on inbox parsing versus the core product.

## Decision

In v1, application status is updated **manually by the user** through the
tracker UI (and the corresponding `PATCH /applications/{id}/status` endpoint).
The platform does not request inbox access, does not read email, and does not
attempt to infer status from any external source. Automatic inbox parsing is
recorded as a **v2 roadmap item** with the prerequisites noted below.

## Rationale

- **Avoids OAuth app verification before the core product works.** Reading
  Gmail requires the `gmail.readonly` restricted scope, which triggers Google's
  OAuth verification process and, for restricted scopes, an annual third-party
  security assessment (CASA). Microsoft Graph `Mail.Read` has a comparable
  publisher-verification path. Neither is reasonable to undertake before the
  product has validated users.
- **Avoids scope and privacy complexity.** Inbox access is the most sensitive
  permission a consumer app can request. Users are rightly hesitant, and the
  platform would inherit obligations around retention, encryption at rest,
  breach notification, and data-deletion requests for email content that is
  unrelated to job applications.
- **Keeps v1 scope achievable.** Email classification (is this a rejection?
  an interview invite? a newsletter from the same company?) is an ML problem
  with meaningful error rates. False positives corrupt the tracker, which is
  worse than a stale status.
- **Manual updates already satisfy the transactional invariant.** Every status
  change — regardless of origin — goes through one service function that
  writes the `applications` update and the `application_events` row together.
  Automating the *source* later does not change this contract.
- **Lightweight assist without inbox access.** The UI can prompt users to
  update stale applications (e.g. "No update in 14 days — still waiting?"),
  which captures most of the value with none of the compliance cost.

## Alternatives Rejected

- **Gmail API / Microsoft Graph inbox polling with classification.** Rejected
  for v1: OAuth verification and security assessment lead time, restricted-scope
  privacy burden, classification error rate, and significant engineering
  effort. **Deferred to v2**, contingent on: (a) verified OAuth apps for Google
  and Microsoft, (b) a labeled email dataset for classifier evaluation,
  (c) an explicit per-application opt-in, and (d) suggested-not-applied
  updates that the user confirms.
- **Email forwarding to a platform-owned address (e.g.
  `track+{user_id}@nextstep.ai`).** Rejected for v1: requires inbound mail
  infrastructure, spam handling, and still needs a classifier; user friction
  of forwarding every email is comparable to clicking a status button.
- **Browser extension observing ATS confirmation pages.** Rejected: separate
  distribution and review process, only captures the initial "applied" event,
  and fragile across ATS layouts.
- **ATS webhooks / candidate-portal scraping.** Rejected: ATS webhooks are
  employer-side and unavailable to candidates; scraping candidate portals
  violates ToS and ADR 001's no-scraping principle.

## Consequences

**Positive**

- No restricted OAuth scopes; sign-in uses only basic profile scopes through
  NextAuth.js.
- Smallest possible sensitive-data footprint: the platform stores resumes and
  application metadata, never email.
- The tracker's data quality is bounded by user input, which is at least
  intentional and auditable via `application_events`.
- Engineering time stays on ingestion, matching, and tracker UX.

**Negative**

- Tracker accuracy depends on user diligence; stale statuses are likely for
  less engaged users.
- Analytics (response rate, time-to-interview) reflect self-reported data and
  will under-count rejections that users never log.
- Competitors offering inbox sync will appear more "automatic"; this must be
  positioned as a privacy feature until v2 lands.
- v2 inbox parsing must be designed so that machine-suggested transitions are
  distinguishable from user-confirmed ones in `application_events`
  (e.g. an `actor` / `source` column), which should be anticipated in the
  v1 schema.
