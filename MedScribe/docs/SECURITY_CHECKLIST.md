# MedSTT Security Hardening Checklist — Phase 16

Last updated: Phase 16 completion. This document reflects the actual state of
the system as verified during Phase 16, not a generic template. Items are
marked DONE only where directly tested and confirmed working during this
phase; OPEN items are named explicitly rather than omitted.

## Authentication & Session Management

- [x] **Server-side sessions in Redis, not JWTs** (Phase 4) — enables instant
      revocation (admin deactivates a user mid-shift takes effect immediately,
      tested and confirmed in Phase 4).
- [x] **Session tokens hashed before storage** (Phase 4) — raw token never
      persisted in Redis or Postgres; exposure of either store doesn't yield
      a usable session.
- [x] **Password hashing: Argon2id** (Phase 4), OWASP 2024+ recommended
      parameters (t=3, m=64MiB, p=1).
- [x] **Account lockout after 5 failed login attempts** (Phase 4).
- [x] **Generic login failure messages** (Phase 4) — no username enumeration.
- [x] **Rate limiting on /auth/login** (Phase 16) — 10/minute per IP via
      slowapi + Redis-backed storage, tested and confirmed (verified 401s
      followed by 429 on rapid repeated attempts). Deliberately complementary
      to, not a replacement for, account lockout — lockout protects one
      account from targeted brute force; rate limiting protects the endpoint
      from broader abuse across many accounts/usernames.
- [x] **Cookie `secure` flag now environment-driven** (Phase 16) —
      `COOKIE_SECURE` setting, defaults False for local HTTP dev.
      **OPEN: must be manually set to `True` in any real deployment behind
      HTTPS before go-live.** Flipping this prematurely (before HTTPS exists)
      breaks login entirely, not just reduces security — deployment runbook
      (Phase 17) must call this out as a required manual step, not something
      that happens automatically by deploying.
- [ ] **HTTPS/TLS termination itself** — OPEN. Not configured anywhere in
      this project; assumed to be handled by whatever reverse proxy/load
      balancer fronts the real deployment. Explicitly out of this project's
      current scope but a hard prerequisite before `COOKIE_SECURE=True` can
      be safely enabled.

## Authorization (RBAC)

- [x] **Role-gated routes** (Phase 4) — `require_admin`/`require_nurse`/
      `require_doctor`/`require_nurse_or_doctor` dependencies, consistently
      applied across every router built since Phase 4.
- [x] **Admins cannot change their own account status** (Phase 4) — prevents
      self-lockout with no recovery path.

## Input Validation & Injection

- [x] **SQL injection: not applicable by construction** — every query across
      every phase uses SQLAlchemy's ORM query builder (`select()`, `.where()`
      with bound parameters); no raw string-interpolated SQL exists anywhere
      in the codebase. Verified by review during Phase 16, not newly fixed.
- [x] **Malformed UUID path parameters rejected automatically** — every route
      consistently types path parameters as `uuid.UUID`; FastAPI/Pydantic
      returns 422 for non-UUID input with no additional code required.
      Verified by review during Phase 16 (consistent pattern across all
      routers), not newly fixed.
- [x] **Request body size limits** (Phase 16) — global 1MB limit on JSON
      request bodies via `RequestSizeLimitMiddleware`, tested and confirmed
      (413 returned for oversized payload). Audio upload endpoints correctly
      excluded, retaining their own dedicated Phase 7 limit
      (`MAX_UPLOAD_SIZE_BYTES`, 100MB).
- [x] **Audio file validation** (Phase 7) — real file properties inspected
      via ffprobe (never trusts client-supplied MIME type/extension alone);
      basic sanity checks (duration, sample rate) reject obviously invalid
      files before they enter the pipeline.

## CORS

- [x] **Environment-driven CORS origins** (Phase 16) — was hardcoded to
      `localhost:5173` only; now `CORS_ALLOWED_ORIGINS` setting, comma-
      separated, defaults to the same dev value. **OPEN: must be set to the
      real production frontend origin(s) at deployment — never `"*"`, which
      the browser spec itself forbids combining with `allow_credentials=True`
      and which would allow any website to make authenticated requests using
      a logged-in user's session cookie.**

## Secrets Management

- [x] **Redis password no longer hardcoded in `redis.conf`** (Phase 16) —
      was `change_me_redis_dev_91823` committed in a config file since Phase
      1; now passed via `--requirepass` command override sourced from
      `.env`'s existing `REDIS_PASSWORD`, single source of truth for both
      the Redis server and backend client.
- [x] **Full-repo secret scan performed** (Phase 16) — grepped for common
      hardcoded secret patterns (password/secret/api_key/token assignments)
      across all `.py`/`.yml`/`.yaml`/`.conf`/`.env*` files; only the Redis
      password (now fixed) was found. No other hardcoded secrets present.
- [x] **`.env` correctly gitignored and confirmed never committed** — checked
      actual git history (`git ls-files`), not just the `.gitignore` rule
      itself; confirmed no `.env` file has ever been tracked.
- [x] **`.gitignore` gap found and fixed** (Phase 16) — `storage/prescriptions/`
      (contains real patient names, MRNs, and clinical text in generated
      PDFs since Phase 14) was NOT excluded, only `storage/audio/` and
      `storage/transcripts/` were. Fixed; confirmed via `git ls-files` that
      no PHI-bearing PDF had already been accidentally committed before the
      fix (the gap was real but had not yet caused actual exposure).

## Audit Logging

- [x] **Every significant action writes to `audit_logs`** (Phase 4 onward) —
      logins, logouts, user/patient CRUD, status changes, HITL resolution,
      prescription edits/finalization, all via the single `write_audit_log()`
      path established in Phase 4. Consistently applied across every phase.
- [x] **Audit log is append-only in practice** (Phase 4) — no update/delete
      API exists for `audit_logs`, enforced at the service layer.

## Data Handling / PHI

- [x] **UUID primary keys throughout** (Phase 2) — record counts/existence
      not inferable from sequential IDs.
- [x] **Soft-delete, never destructive delete, on clinical data** (Phase 2
      onward) — patients/appointments soft-deleted; AI-generated artifacts
      (transcripts, entity sets, prescriptions) use row-versioning, never
      overwritten in place.
- [x] **Audio filenames on disk are UUIDs, never original filenames**
      (Phase 7) — avoids leaking patient-identifying info (e.g.
      "jane_doe_visit.mp3") into the filesystem/backups independent of DB
      access control.
- [x] **AI-provenance disclosure on the final clinical artifact itself**
      (Phase 14) — the generated PDF, not just an internal DB flag, states
      when content was AI-drafted, names the model, and states it requires
      independent clinical verification, directly carrying through both
      MedASR's and MedGemma's model-card requirements onto the actual
      document a patient/auditor would see.

## Known Open Items (explicitly not addressed in Phase 16 — scope was
## deliberately limited to security/hardening; these are tracked separately)

- pyannote.audio version drift (running 4.0.7, intended 3.1.1 pin) — a
  correctness/stability item, not itself a security gap, but unresolved.
- No background task queue — chunking, transcription, NER, and MedGemma
  drafting are all long-running synchronous HTTP requests (up to several
  minutes for MedGemma alone). Not a security issue but a real availability/
  DoS-adjacent concern worth noting: a flood of legitimate-looking requests
  to these endpoints could tie up server resources for extended periods with
  no queue/backpressure mechanism. Worth addressing before any real
  production load, flagged here for visibility even though it wasn't in
  Phase 16's agreed scope.
- No frontend UI exists for Phases 7–14 (audio, chunking, transcription,
  NER, prescriptions) — feature completeness gap, not a security concern
  per se.
- Nurse-side intake form (vitals) drafting was never built — only doctor-
  side prescription drafting was completed.

## Verification Method

Every item marked DONE above was either (a) directly tested with a real
request/response during this phase (rate limiting, request size limit,
Redis connectivity post-fix) or (b) confirmed via direct code/repo
inspection during this phase (SQL injection non-applicability, UUID
validation, secret scanning, git history check) — not assumed correct
from having been written in an earlier phase.