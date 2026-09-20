# ADR 002 — Users apply on the official company site; the platform never submits applications on their behalf

## Status: Accepted

## Context

A job platform can position itself anywhere on a spectrum from "discovery and
tracking" to "one-click auto-apply". Auto-apply features are attractive in
marketing but require the platform to fill and submit third-party application
forms, upload the user's resume to systems the platform does not control, and
answer employer-specific screening questions. This decision determines what
the **Apply** stage of the pipeline actually does, and what data and
credentials the platform must handle.

## Decision

The **Apply** action in NextStep.ai redirects the user to the posting's
official application URL (the `absolute_url` / `applyUrl` provided by the ATS)
in a new tab and, in the same transaction, creates an `applications` row with
status `applied_pending_confirmation` plus the first `application_events` row.
The user completes the application on the company's own site. NextStep.ai
never fills forms, never submits applications, and never stores employer
login credentials.

## Rationale

- **Avoids fragile per-company form automation.** Every ATS and every company
  customizes its application form: required fields, custom screening questions,
  EEO surveys, CAPTCHAs, file-type restrictions. Automating this reliably at
  scale is a product in itself and breaks continuously.
- **Avoids legal and Terms-of-Service risk.** ATS vendors and employers
  prohibit automated submissions. Auto-apply also raises questions about consent
  (who actually "applied"?), accuracy of submitted answers, and liability if
  the bot misrepresents the candidate.
- **Keeps scope achievable.** The core value is discovery, honest resume-fit
  scoring, and a reliable tracker. Auto-apply would consume the majority of
  engineering effort while adding risk to the pieces that already work.
- **Preserves user agency and application quality.** Users can tailor answers
  and cover letters per role, which measurably improves outcomes compared with
  bulk auto-submission.
- **Minimizes sensitive data handling.** The platform never needs employer
  credentials, and never needs to answer questions about work authorization,
  salary expectations, or demographics on the user's behalf.

## Alternatives Rejected

- **Full auto-apply via headless browser (Playwright / Selenium).** Rejected:
  extremely high maintenance, high breakage rate, ToS violations, CAPTCHA
  blocking, and reputational risk when a bot submits incorrect answers.
- **ATS-specific apply APIs (e.g. Greenhouse Job Board API
  `POST /applications`).** Rejected for v1: requires per-company API keys
  issued by the employer (not the candidate), so it does not generalize; many
  boards disable it; still leaves Lever and Ashby uncovered.
- **Pre-filling forms via a browser extension.** Rejected for v1: separate
  distribution channel, review process, and security surface. Documented as a
  possible v2+ enhancement that still keeps the human as the submitter.
- **"Easy Apply"-style in-platform forms forwarded to the employer by email.**
  Rejected: employers do not accept applications outside their ATS, and it
  would give users a false sense that they had applied.

## Consequences

**Positive**

- Zero form-automation code to maintain; the Apply stage is a redirect plus a
  transactional insert.
- No employer credentials or screening answers stored, shrinking the security
  and privacy surface.
- Clear legal posture: the user, not the platform, submits every application.
- Engineering effort stays focused on ingestion, matching, and tracking.

**Negative**

- The platform cannot confirm that a user actually completed the external
  application; the tracker relies on the user confirming (see ADR 004) — hence
  the `applied_pending_confirmation` status.
- "Apply" is less differentiated than competitors advertising one-click apply.
- Users must re-enter profile information on each company site; the platform
  can mitigate with a copy-to-clipboard profile summary but cannot eliminate it.
- Conversion analytics (viewed → applied) will be noisier because the handoff
  crosses a domain boundary we do not control.
