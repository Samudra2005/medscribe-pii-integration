# MedSTT Project Status — End of Phase 4

## Environment
- WSL2 Ubuntu, project root: ~/medstt
- Python 3.12 (venv at backend/.venv), Node 22, Docker Desktop w/ WSL integration
- GPU: RTX 4060 8GB VRAM, confirmed working in WSL and in Docker
- VSCode via Remote-WSL, all terminal commands run inside Ubuntu

## Model/resource plan (locked)
- MedASR: GPU, loaded on demand, unloaded after use
- MedGemma-4B-it (GGUF, Q4_K_M): GPU, swapped with MedASR, never both resident
- BioClinicalBERT/BiomedBERT (NER): CPU always
- Cloud fallback: Azure AI Speech + Azure OpenAI / HF Inference Endpoint, used on low confidence/backlog/OOM

## Docker infra (Phase 1) — container/network names use `medstt_v1_` prefix (renamed from plain `medstt_` due to collisions with other local projects)
- Postgres: container `medstt_v1_postgres`, host port **5433**, db `medstt_db`, user `medstt_admin`
- Redis: container `medstt_v1_redis`, host port **6380**, password in .env
- pgAdmin: container `medstt_v1_pgadmin`, host port **5051**, login admin@medstt.com
- Network: `medstt_v1_network`; volumes: `medstt_v1_postgres_data`, `medstt_v1_redis_data`, `medstt_v1_pgadmin_data`
- docker-compose.yml at project root; .env and .env.example at project root (gitignored except .env.example)

## Database schema (Phase 2) — 12 tables, Alembic-managed
users, sessions, patients, appointments, audio_recordings, audio_chunks, transcripts,
extracted_entity_sets, hitl_queue, intake_forms, prescriptions, audit_logs

Key patterns:
- UUID PKs via pgcrypto gen_random_uuid(), server-side default
- Soft delete (deleted_at) on patients/appointments only; users use UserStatus enum instead
- Row-versioning via supersedes_id (self-referential FK) on transcripts, extracted_entity_sets,
  intake_forms, prescriptions — preserves AI-original vs human-corrected as separate rows
- All enums centralized: app/models/enums.py has `pg_enum(enum_cls, name, create_type=True)`
  helper using values_callable=lambda: member.value — CRITICAL, ensures lowercase enum values
  stored in Postgres (e.g. 'admin' not 'ADMIN'). Always import and use pg_enum for any new
  enum column, never raw PgEnum().
- input_source enum type is SHARED across audio_recordings/intake_forms/prescriptions
  (create_type=False on the reuses)
- Current migration: single clean file, revision fedf0444a7e8, matches live DB exactly

Current admin account exists: username admin123 (password known to user only).
Nurse test account exists: username nurse_jane.

## Backend structure (Phases 2-4)
~/medstt/backend/
  .venv/
  app/
    core/         config.py (pydantic-settings, reads ../.env), logging_config.py (structlog,
                   JSON logs to stdout + rotating file at ~/medstt/logs/medstt_backend.log),
                   lifespan.py (verifies PG+Redis on startup, fails fast), security.py
                   (argon2id hashing, session token gen/hash)
    db/           session.py (async engine/session, DATABASE_URL_ASYNC uses localhost since
                   backend runs outside Docker for now), redis_client.py
    models/       base.py, mixins.py, enums.py (+ pg_enum helper), user.py, session.py,
                   patient.py, appointment.py, audio.py, transcript.py, extracted_entity.py,
                   intake_form.py, prescription.py, hitl.py, audit_log.py, __init__.py
                   (imports all — this is what Alembic autogenerate reads)
    schemas/      auth.py, user.py (Pydantic request/response, deliberately separate from ORM)
    services/     session_service.py (Redis+Postgres dual-write sessions, 8hr TTL),
                   auth_service.py (login/lockout after 5 fails, opportunistic rehash),
                   audit_service.py (write_audit_log — single write path for audit_logs table)
    api/          health.py (/health, /health/ready), auth.py (/auth/login, /logout, /me,
                   /change-password), admin_users.py (/admin/users CRUD + status),
                   patients.py (/patients CRUD, admin+nurse allowed on create/list/get,
                   admin-only soft-delete, ?search= param on list), hitl.py (/admin/hitl
                   list+claim+resolve, admin-only, empty until Phase 10+/12 populate it),
                   audit_logs.py (/admin/audit-logs, admin-only, filterable by action/
                   actor_user_id/target_entity_type/target_entity_id/success/date range,
                   paginated limit<=500), deps.py (get_current_user via cookie+Redis,
                   require_role/require_admin/require_nurse/require_doctor/require_nurse_or_doctor)
    middleware/   request_logging.py (request_id via structlog contextvars, X-Request-ID header)
    scripts/      create_first_admin.py (one-time CLI bootstrap, NOT an API endpoint)
    main.py       FastAPI app, CORS allow_origins currently ["http://localhost:5173"] only
  alembic/        env.py (imports Settings + Base, uses DATABASE_URL_SYNC/psycopg2,
                   compare_type=True, compare_server_default=True), versions/
  requirements.txt

Run backend: cd ~/medstt/backend && source .venv/bin/activate &&
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Docs at http://localhost:8000/docs

## Auth design decisions (Phase 4)
- Server-side sessions in Redis (not JWT) — needed for instant revocation (admin deactivates
  user mid-shift must take effect immediately, not wait for token expiry)
- Session cookie name: medstt_session, httponly, samesite=lax, secure=False (MUST become True
  before any real deployment — behind HTTPS only)
- Password hashing: Argon2id, time_cost=3, memory_cost=64MiB, parallelism=1 (OWASP 2026 guidance)
- Admin-created users get random temp password + must_change_password=True forced flag —
  admin never learns the user's real ongoing password
- Changing password revokes ALL sessions for that user
- Suspending/deactivating a user immediately revokes all their active sessions (tested working)
- Admins cannot change their own status (prevents self-lockout)
- Login failure messages are deliberately generic (no username enumeration)
- Account lockout after 5 failed attempts (is_locked flag)
- Every significant action writes to audit_logs via write_audit_log() — pattern: call it
  explicitly after the business operation commits, don't try to infer audit-worthy actions
  from generic middleware

## Known deferred items (intentional, not forgotten)
- CORS is permissive only for localhost:5173 — fine for now, must be tightened for prod
- Redis config password is hardcoded in infra/redis/redis.conf rather than templated from
  .env (Redis config files don't support env var substitution) — revisit in hardening phase
- DATABASE_URL_ASYNC/SYNC in config.py hardcode "localhost" rather than using
  settings.POSTGRES_HOST — correct for now since backend runs outside Docker; MUST switch
  to using POSTGRES_HOST/REDIS_HOST once backend itself is containerized
- ground_truth_corrections was folded into existing transcript/entity versioning rather than
  a 13th table (query HUMAN_CORRECTED status instead) — revisit if training/eval needs
  denormalized storage later
- FIPS 140-2/3 compliance not addressed — if required later, Argon2id would need to be
  replaced with PBKDF2-SHA256 for password hashing specifically

## Frontend (Phase 6, in progress)
Stack: React + Vite + TypeScript, plain CSS Modules (no Tailwind, no UI kit).
One extra dependency beyond the Vite template: react-router-dom.

~/medstt/frontend/
  .env, .env.example    VITE_API_BASE_URL=http://localhost:8000 (frontend's own env,
                         separate from backend's -- Vite only reads VITE_-prefixed vars
                         from its own project root)
  src/
    types/     user.ts (UserRole, UserStatus, CurrentUser, UserSummary,
               CreateUserResponse -- mirrors schemas/auth.py + schemas/user.py exactly,
               snake_case field names kept identical to JSON keys on purpose),
               patient.ts (minimal Patient interface, intentionally incomplete --
               full patient CRUD schema not yet re-verified in detail, will extend
               when that page is actually built)
    api/       client.ts (apiRequest<T> wrapper: credentials:"include" hardwired on
               every call so the httponly medstt_session cookie is sent/received;
               normalizes FastAPI's {"detail": "..."} error shape into a thrown
               ApiError class with .status/.detail), auth.ts (login/logout/
               fetchCurrentUser/changePassword, 1:1 mapped to the four /auth/* endpoints)
    context/   AuthContext.tsx (AuthProvider + useAuth hook; calls /auth/me on mount
               to restore session state from the cookie -- no token ever stored in JS;
               isLoading flag prevents login-page flash during that initial check;
               refreshUser exposed for re-checking state after password change)
    components/
               ProtectedRoute.tsx (auth-gates + role-gates route children; also
               enforces must_change_password redirect at the guard level, not just
               post-login, so a direct URL visit can't bypass it)
               AppShell.tsx + AppShell.module.css (persistent sidebar + topbar shell
               used by all three role dashboards; sidebar has a role-colored accent
               bar -- admin blue #1E3A5F, nurse green #2E7D6B, doctor purple #6B4E9E --
               consistent visual identifier of which role's view is active)
               RootRedirect.tsx (used for "/" and catch-all "*" routes; sends an
               already-authenticated user to their role home instead of bouncing
               everyone to /login unconditionally)
    pages/     LoginPage.tsx + LoginPage.module.css (centered card layout, not the
               original inline-styled corner-pushed version), ChangePasswordPage.tsx
               (reuses LoginPage.module.css for visual consistency; explicitly logs
               out + redirects to /login after a successful change, since the backend
               revokes ALL sessions including the current one on password change --
               frontend can't just refreshUser() and continue), AdminDashboard.tsx,
               NursePage.tsx, DoctorPage.tsx (all three use AppShell now; still
               overview-only placeholders, no real CRUD UI yet), UnauthorizedPage.tsx
    App.tsx    Router shell: /login, /change-password (any authenticated role),
               /admin/* /nurse/* /doctor/* (role-gated via ProtectedRoute), /unauthorized,
               "/" and "*" both use RootRedirect

Design tokens (index.css): institutional blue-slate palette (--color-primary #1E3A5F),
off-white background (#F7F8FA), muted teal success / amber warning / red error, system-ui
font stack (no web font loading -- deliberate, keeps dev server light on the 6GB RAM
constraint). Chosen deliberately over generic SaaS-bright colors to read as an
institutional/clinical tool rather than a startup product.

Sidebar nav items reference future routes (/admin/patients, /admin/users, /admin/hitl,
/admin/audit-logs, etc.) that don't have real pages yet -- these currently 404 into
RootRedirect's catch-all. Intentional: the shell/nav structure is built once, pages get
filled in as their corresponding phase-5-backed features are built out next.

Tested end-to-end and confirmed working: login (admin + nurse accounts), logout,
session restore on page refresh via /auth/me, role-based post-login routing, role-gating
(nurse blocked from /admin -> /unauthorized), forced password-change interception at the
route-guard level, direct-URL-while-logged-out redirect to /login, already-authenticated
visits to "/" and unknown paths correctly landing on role home instead of /login.

Not yet built in Phase 6: real patient/user/HITL/audit-log list pages (APIs already exist
from Phase 5, UI pending), any form validation beyond HTML5 required/minLength, loading
skeletons, toasts/notifications, mobile-specific layout tuning beyond "doesn't visibly break."

## Frontend data pages (Phase 6 continuation, complete)
Built against the real Phase 5 API contracts (routers/schemas re-verified directly from
source before writing frontend code, not assumed from the status doc's earlier summary).

  src/types/patient.ts   CORRECTED from the original Step 6.3 placeholder -- real
                          Patient shape has mrn, phone_number, address, known_allergies,
                          created_by_id (matches schemas/patient.py PatientSummary exactly).
                          Also added CreatePatientPayload / UpdatePatientPayload.
  src/types/hitl.ts       HitlReason (7 values), HitlStatus (4 values), HitlItem,
                          ResolveHitlPayload, HITL_REASON_LABELS lookup for display text.
  src/types/audit.ts      AuditAction (13 values), AuditLogEntry -- mirrors
                          schemas/audit.py + enums.py exactly.
  src/api/patients.ts     list (with ?search=), get, create, update, delete (soft).
  src/api/hitl.ts         list (with ?status_filter=), claim, resolve.
  src/api/auditLogs.ts    list with full filter set (action/actor_user_id/
                          target_entity_type/target_entity_id/success/start_date/
                          end_date/limit/offset). Filter interface uses an explicit
                          string-keyed index signature ([key: string]: string | number
                          | boolean | undefined) alongside the named optional props --
                          required to satisfy apiRequest's params type, TS doesn't
                          structurally allow an all-optional named-props object where
                          an index signature is expected without it. Apply this same
                          pattern to any future filter-object types passed as `params`.
  src/api/users.ts        list, get, create, updateStatus.

  src/pages/PatientsPage.tsx   List (debounced 350ms search by name/MRN) + modal create
                          form. Available to both admin and nurse (matches backend:
                          create/list/get patients require only get_current_user, not
                          admin). Optional empty-string fields converted to undefined
                          before POST so Pydantic sees omission, not empty string.
  src/pages/UsersPage.tsx      Admin-only. List with role/status badges, Activate/
                          Suspend/Deactivate action buttons (flat status enum, no
                          formal state machine backend-side, so buttons not a dropdown).
                          Create-user modal shows the one-time temp password returned
                          by POST /admin/users -- backend never exposes it again after
                          this response, dialog copy is explicit about that.
                          KNOWN GAP (flagged, not fixed): an admin CAN click Suspend/
                          Deactivate on their own row in the UI; the backend correctly
                          rejects it (400, "Admins cannot change their own account
                          status") and the message surfaces in the error banner, but
                          the button isn't proactively hidden/disabled for the self
                          row. Low priority, revisit if it becomes annoying.
  src/pages/HitlPage.tsx        Admin-only. Filter tabs: "Pending review" (frontend-only
                          concept = omit status_filter, matches backend's own default
                          of pending+in_review), plus explicit pending/in_review/
                          resolved/dismissed. Claim button only shown on pending items,
                          Resolve form (required notes, resolve-or-dismiss) only on
                          in_review items -- UI can't attempt an invalid state
                          transition the backend would 409 on.
                          NOT YET LIVE-TESTED with real data: hitl_queue is empty until
                          Phase 10 (quality engine) / Phase 12 (NER validation) actually
                          write rows to it. Request/response wiring verified correct
                          against schemas/hitl.py; empty states confirmed working;
                          claim/resolve interaction itself unverified against live data.
  src/pages/AuditLogPage.tsx    Admin-only. Filters: action (dropdown, all 13 enum
                          values), target_entity_type (free-text -- backend doesn't
                          constrain this to an enum, populated ad hoc per-router),
                          success (all/success/failures). Offset-based pagination,
                          50/page, Next disabled when a page returns <50 rows (no
                          separate count endpoint needed). Any filter change resets
                          offset to 0 to avoid landing on an empty out-of-range page.
                          metadata_json collapsed by default, expandable per row.
                          Tested live against real logged data (logins, patient/user
                          creates, status changes) -- this page had real data to
                          verify against, unlike HITL.

Router (App.tsx) now has explicit flat routes (not wildcard nesting) for:
  /admin, /admin/patients, /admin/users, /admin/hitl, /admin/audit-logs (all role-gated
  to admin), /nurse, /nurse/patients (role-gated to nurse), /doctor (role-gated to
  doctor, no sub-pages yet -- doctor review workflow is Phase 14).

## Phase 7 — Audio ingestion pipeline (backend complete)

### Prerequisite gap found and fixed: minimal appointments API
audio_recordings.appointment_id is a required FK, but no appointments router existed
yet (only the DB model, since Phase 2) -- added as a deliberately narrow prerequisite,
NOT full appointment workflow logic:
  app/schemas/appointment.py   CreateAppointmentRequest, AppointmentSummary
  app/api/appointments.py      POST /appointments (nurse or doctor only, validates
                                patient exists first), GET /appointments (optional
                                ?patient_id= filter), GET /appointments/{id}
Deliberately NOT built: status-transition endpoints (intake complete, doctor pickup,
prescription complete, etc.) -- those transition rules aren't defined yet and belong
to the phases that actually implement those workflows. Appointments currently only
ever sit at status=created via the API.

### Audio storage & config
~/medstt/storage/audio/originals/    raw uploaded bytes, named <recording_uuid>.<ext>
~/medstt/storage/audio/normalized/   ffmpeg-normalized 16kHz mono WAV, <recording_uuid>.wav
Filenames are UUIDs, never original filenames -- avoids leaking patient-identifying
info (e.g. "jane_doe_visit.mp3") into the filesystem/backups independent of DB access
control. original_filename preserved as a DB column for display only.

config.py additions: AUDIO_STORAGE_ROOT (relative to backend/ working dir, same
"local dev now, containerize later" pattern already flagged for POSTGRES_HOST),
MAX_UPLOAD_SIZE_BYTES (100MB default -- chosen, not specified, flagged as adjustable),
ALLOWED_AUDIO_MIME_TYPES (comma-separated setting: wav, mp3, mp4/m4a, webm, ogg, flac --
covers both direct file uploads AND browser MediaRecorder output for live recording).

### Audio service layer (app/services/audio_service.py)
ffprobe/ffmpeg invoked via asyncio.create_subprocess_exec (NOT subprocess.run --
blocking subprocess calls would freeze the entire async event loop, not just one
request, for however long ffmpeg takes on a long recording).
- compute_sha256 -- content hash, used for duplicate-upload detection
- probe_audio_file -- ffprobe inspection of REAL file properties (duration, sample
  rate, channels, codec), never trusts client-supplied MIME type/extension alone
- validate_probed_audio -- basic sanity checks only (reject <0.5s, >4hr, <8000Hz
  sample rate) -- deliberately NOT the full quality engine (SNR/clipping/hallucination
  detection), that's Phase 10 per roadmap boundary
- normalize_to_wav -- ffmpeg to 16kHz mono PCM WAV (MedASR's expected input, per
  Phase 9 model plan)
4hr max duration / 8kHz min sample rate / 0.5s min duration are chosen defaults, not
user-specified -- flagged as easy to adjust if real recording lengths differ.

### API endpoints (app/api/audio.py)
POST /audio/upload   multipart form (appointment_id + file), input_source=uploaded_audio
POST /audio/record    same shape, input_source=live_recording -- kept as a SEPARATE
                      endpoint rather than a client-supplied field, so a client can't
                      mislabel how audio was captured; this distinction is expected to
                      matter for Phase 10's quality/trust weighting later
GET  /audio/{id}      single recording
GET  /audio?appointment_id=...   list recordings for an appointment

Pipeline per upload: size/mime check -> confirm appointment exists -> sha256 dedup
check (per-appointment scope, not global) -> save original to disk -> ffprobe validate
-> ffmpeg normalize -> processing_status updated at each stage (uploaded -> validating
-> normalizing -> uploaded, or -> validation_failed with validation_failure_reason set).

IMPORTANT DESIGN CHOICE: validation failure does NOT reject the HTTP request (still
201) -- the row persists with processing_status=validation_failed and a reason, rather
than the attempt vanishing entirely. Chosen for operator visibility (clinician/admin
can see WHAT was uploaded and WHY it failed) over strict reject-on-invalid semantics.
Flagged as a real design choice, not the only valid one -- revisit if it causes
confusion in practice.

Tested end-to-end with real audio: upload -> normalize -> files confirmed on disk in
both originals/ and normalized/, duplicate upload correctly deduplicated (same
sha256 + appointment_id returns existing row, no second ffmpeg pass), non-audio file
correctly rejected.

### Frontend audio UI: explicitly deferred by user decision
User confirmed (after Phase 7 backend was fully tested) to proceed backend-only and
NOT build the frontend upload/live-recording UI as part of Phase 7. This is a
deliberate scope decision, not a forgotten item -- when picked up later, it needs:
  - Upload UI: file picker + progress state, POST /audio/upload, likely surfaced from
    an appointment-detail view that doesn't exist yet either (current frontend only
    has patient list/create -- there's no appointment or per-appointment UI at all yet)
  - Live-recording UI: browser MediaRecorder API -> POST /audio/record
  - Both need a way to show processing_status (uploaded/validating/normalizing/
    validation_failed) and validation_failure_reason to the user, ideally with polling
    or a refresh action since normalization happens synchronously within the request
    right now (no background job queue yet) -- for short recordings this is fine, but
    worth flagging: a very long recording's upload request will stay open for the
    full ffmpeg normalization duration. Not a problem yet, worth revisiting if typical
    recording length grows.

## Phase 8 — Chunking (VAD + speaker diarization) — backend complete

### Libraries & install decisions
pyannote.audio PINNED to 3.1.1 (not latest) -- avoids a documented VRAM/RAM regression
in 4.0.3 (some reports of 6x higher VRAM usage during the reconstruction step).
silero-vad installed as its own pip package, using its native API (load_silero_vad,
get_speech_timestamps, read_audio) -- NOT torch.hub.load, which is the older pattern;
the pip package's own API is simpler and avoids a hub-cache dependency.
Both HF model gates accepted (pyannote/segmentation-3.0, pyannote/speaker-diarization-3.1).
HUGGINGFACE_TOKEN added to config.py as a REQUIRED (no default) setting -- fails fast
at startup if missing, rather than failing deep into a diarization request.

### Known CPU performance issue (documented in pyannote's own GitHub issues, not unique
to this project) and the fix applied
pyannote 3.1's CPU pipeline is widely reported as 2x+ slower than 3.0, with the
embeddings step as the main bottleneck (public reports of 13-35+ min on modest cloud
CPUs for ~1hr audio). Initial test run: diarization alone took ~26 minutes for a 7.5
minute recording -- unacceptable as-is. FIX APPLIED: torch.set_num_threads() pinned
explicitly in diarization_service.py, since uncontrolled thread spawning/contention
(especially inside WSL2's virtualized CPU topology) is a commonly-reported cause of
exactly this kind of slowdown. Confirmed working after fix, but EXACT post-fix timing
number was not captured in conversation -- worth re-measuring and logging a real
number here next time this is touched, and revisiting GPU-based diarization as a
fallback if CPU timing is still not acceptable for real (up to 30-min) recordings.

### Real bug found and fixed: unbounded chunk duration
Original merge logic (chunking_service.py) had no ceiling on chunk length -- a long
run of same-speaker VAD regions with short gaps between them could merge into one
arbitrarily long chunk. Caught in first real test: one chunk spanned 121 seconds
(2 minutes) when it should have been capped. FIX: added MAX_CHUNK_DURATION_SECONDS
(25.0s, chosen as a reasonable ASR context-window default, not derived from MedASR
specifics yet since Phase 9 doesn't exist) -- forces a split even mid-speaker-turn if
a chunk would exceed this. Re-tested and confirmed holding (no more runaway chunks).

### Real schema gap found and fixed: no "chunking done" terminal status
AudioProcessingStatus jumped CHUNKING -> TRANSCRIBING directly, with no status
representing "chunking finished, waiting for Phase 9 ASR" (which doesn't exist yet).
Added CHUNKING_COMPLETE = "chunking_complete" to the enum (app/models/enums.py),
inserted between CHUNKING and TRANSCRIBING for readability. Required a real Alembic
migration (ALTER TYPE ... ADD VALUE) -- generated via autogenerate, reviewed before
applying (Postgres enum ADD VALUE is a case where autogenerate can behave unexpectedly,
worth checking the generated file by hand), applied successfully.

### Services built
app/services/vad_service.py            Silero VAD, returns list[SpeechRegion]. Model
                                        loaded once and kept resident (module-level
                                        global) -- deliberate exception to the GPU
                                        load/unload orchestrator pattern, since Silero
                                        never touches GPU and its footprint is tiny.
app/services/diarization_service.py    pyannote pipeline wrapper, num_speakers=2
                                        hardcoded (always nurse/doctor + patient, never
                                        more), CPU-only (never .to(cuda)), torch thread
                                        count pinned explicitly (see perf note above).
                                        Pipeline also kept resident once loaded, same
                                        reasoning as VAD.
app/services/chunking_service.py       Pure merge logic, no I/O: combines VAD speech
                                        regions + diarization speaker turns into
                                        ChunkBoundary objects. Splits on speaker change,
                                        silence gap > MAX_SILENCE_GAP_SECONDS (2.0s), OR
                                        max duration > MAX_CHUNK_DURATION_SECONDS (25.0s).
                                        Merges runs shorter than MIN_CHUNK_DURATION_SECONDS
                                        (1.0s) into neighbors. Speaker assignment per
                                        chunk uses OVERLAP-weighted matching against
                                        diarized segments, not start-time matching --
                                        more robust to the two models' independent
                                        boundary disagreement. All three thresholds are
                                        chosen defaults, explicitly flagged as the first
                                        things to tune once more real recordings are
                                        processed and reviewed.
app/services/chunk_extraction_service.py  ffmpeg -ss/-to slicing of the normalized WAV
                                        into one physical file per chunk (-c copy, no
                                        re-encode needed since source is already the
                                        target format). Chunks stored under
                                        storage/audio/chunks/<recording_id>/chunk_NNNN.wav
app/services/chunking_orchestrator.py  Single entry point: loads recording -> checks
                                        it didn't fail Phase 7 validation -> locates
                                        normalized WAV (derived by convention, same as
                                        Phase 7) -> clears any existing chunks for this
                                        recording (idempotent re-run, not append) -> runs
                                        VAD -> diarize -> merge -> extract -> persist to
                                        audio_chunks -> sets processing_status to
                                        CHUNKING_COMPLETE (or VALIDATION_FAILED with a
                                        reason on any failure).

### API endpoints added (app/api/audio.py)
POST /audio/{recording_id}/chunk    Triggers the full chunking pipeline. DELIBERATELY
                                    NOT automatic after upload -- diarization alone
                                    takes multiple minutes even on short recordings, so
                                    upload stays fast and chunking is a separate,
                                    explicitly-triggered step. No background task queue
                                    exists yet (not in the stack) -- this is a real,
                                    long-running synchronous request today. Flagged as
                                    a future need (Celery/RQ or similar) once frontend
                                    UX for this needs to not block a browser tab for
                                    minutes -- not decided/built yet.
GET  /audio/{recording_id}/chunks   Lists persisted chunks for a recording, ordered by
                                    chunk_index.
app/schemas/audio_chunk.py          AudioChunkSummary schema.

Tested end-to-end on a real ~7.5min recording: chunks correctly created, physical
files confirmed on disk, re-running chunking on the same recording confirmed
idempotent (replaces, doesn't duplicate), no chunk exceeding the duration cap.

### NOT yet built (explicitly deferred)
- Frontend "process this recording" trigger UI -- not started (mirrors Phase 7's
  deferred upload/record UI; there is currently NO frontend surface for audio at all)
- Background task queue for long-running pipeline steps (chunking, and later ASR) --
  not in the stack, will need a real decision (Celery+Redis is the natural fit since
  Redis already exists in the stack, but not evaluated/decided yet)
- Re-measuring and logging actual post-fix diarization timing (see perf note above)
- Tuning the three chunking thresholds (silence gap, min/max duration) against more
  real recordings once available

## Phase 9 — Model orchestrator + local MedASR integration — backend complete

### Model identification (real finding, not assumed)
"MedASR" in the original resource plan refers to a specific, real, publicly released
model: google/medasr on Hugging Face (Google Health AI Developer Foundations program,
released Dec 18 2025 -- after Claude's training cutoff, confirmed via live web search
rather than assumed from memory). 105M param Conformer architecture, CTC-style
interface, accepts mono 16kHz int16 audio (exact match for Phase 7's normalized
output), outputs text only. Gated on HF (same accept-terms pattern as pyannote) --
accepted. License: health-ai-developer-foundations (Google's own terms, not a
standard OSS license -- worth keeping in mind for government review later).
Model card explicitly states outputs "are not intended to directly inform clinical
diagnosis... all outputs should be considered preliminary and require independent
verification" -- directly validates the HITL/doctor-review architecture already built.
Known documented weaknesses (from the model's own card): non-standard medication
names, and date/time formats -- both directly relevant to Phase 10/12 design.

### Real environment issue found: pyannote.audio had silently drifted
Checked before installing MedASR deps and found pyannote-audio was actually running
4.0.7, NOT the 3.1.1 we deliberately pinned back in Phase 8 (likely pulled in
transitively by a later pip install, exact cause not fully traced). The VRAM
regression that pin was meant to avoid is GPU-specific and diarization has been
CPU-only throughout, so this likely hasn't caused a problem YET. USER DECISION:
left at 4.0.7 for now rather than re-pinning, to be revisited later -- OPEN ITEM,
worth addressing before diarization and MedASR/MedGemma ever need to share GPU
resources concurrently, since the regression report was specifically about VRAM
spikes during GPU inference.

### transformers version -- resolved cleanly, no risk taken
MedASR's model card (as originally published) called for installing transformers
from a specific unreleased GitHub commit (5.0.0+ requirement, pre-stable-release
workaround). Checked current environment first (transformers wasn't installed at
all yet -- neither Phase 7 nor 8 needed it). Tried stable PyPI `transformers>=5.0.0`
first rather than the git-commit route: got 5.16.1, AutoModelForCTC/AutoProcessor
imports worked cleanly. The ecosystem had caught up since the model's Dec 2025
release (now Aug 2026) -- no bleeding-edge/unstable install was needed.

### Model orchestrator (app/services/model_orchestrator.py)
Singleton enforcing the resource plan's hard rule: MedASR and MedGemma (Phase 13)
must never both be resident in GPU VRAM simultaneously on the 8GB card. Generic --
takes a loader_fn per model, doesn't know model-specifics itself. asyncio.Lock wraps
the full load-or-reuse decision (not just unload) to prevent a race where two
concurrent requests could both trigger a load and briefly double VRAM usage.
Explicit torch.cuda.empty_cache() + gc.collect() after unload -- setting Python refs
to None alone doesn't reliably release CUDA VRAM back to the driver immediately.
Phase 9 only registers GPUModelSlot.MEDASR; MEDGEMMA slot defined but unused until
Phase 13, which will plug into this SAME orchestrator, not a separate mechanism.

### MedASR service (app/services/medasr_service.py)
Loads via AutoProcessor + AutoModelForCTC (direct control, not the high-level
pipeline() wrapper) -- matches the model card's own reference code closely since
this model is entirely outside Claude's training knowledge (post-cutoff release).
librosa.load(sr=16000) for audio loading, model.generate() + batch_decode() for
inference, matching the model card's documented usage exactly rather than assuming
generic CTC decoding mechanics. Confirmed running on cuda:0 in testing (GPU
correctly engaged, not silently falling back to CPU).
BUG FOUND AND FIXED: batch_decode() defaults to skip_special_tokens=False -- first
test run leaked a literal "</s>" token into transcript output. Fixed by passing
skip_special_tokens=True explicitly and .strip()-ing the result.

### Real quality finding from live testing (not assumed)
First test used a short (~5s) chunk cut mid-sentence at a chunk boundary -- produced
fragmented, partially-wrong output. Retested against a longer (~20s), complete-
utterance chunk from the same recording: transcription was accurate and clean
(correct grammar, correct clinical terms like "conservative management"), with
exactly ONE error -- a specific medication brand name transcribed as a
similar-sounding word. This matches the model card's own documented limitation
around non-standard medication names precisely. CONCLUSION: the short-chunk result
was a chunk-boundary artifact, not a real model quality problem -- MedASR performs
well on complete utterances. Medication-name errors are expected and exactly what
Phase 10's quality engine / ground-truth correction loop / HITL flagging exist to
catch, per user's own framing of this during testing.

### Transcription orchestrator (app/services/transcription_orchestrator.py)
Requires recording.processing_status == CHUNKING_COMPLETE before running (won't
transcribe an un-chunked or already-processing recording). Loads all AudioChunks
for the recording, runs MedASR per chunk (one Transcript row per chunk, NOT one
merged transcript per recording -- matches the schema's own design intent, since
audio_chunk_id being nullable specifically anticipates both chunk-level and
full-recording-consensus transcripts as different concepts). Idempotent re-run
(clears existing source=local_asr drafts for this recording's chunks before
regenerating). confidence_score explicitly left NULL -- real confidence assignment
is Phase 10's job, not invented here as a placeholder number.
processing_status transitions: CHUNKING_COMPLETE -> TRANSCRIBING -> 
TRANSCRIPTION_COMPLETE (or TRANSCRIPTION_FAILED on any exception).

### API endpoints added (app/api/audio.py)
POST /audio/{recording_id}/transcribe   Runs MedASR over every chunk. Separate,
                                        explicitly-triggered call (not automatic
                                        after chunking) -- same reasoning as
                                        chunking being separate from upload: real,
                                        non-trivial GPU inference time, no
                                        background task queue exists yet.
GET  /audio/{recording_id}/transcripts  Lists persisted transcripts in chunk order.
app/schemas/transcript.py               TranscriptSummary schema.

Tested end-to-end on the real Phase 7/8 test recording: all chunks transcribed,
persisted correctly, spot-checked against known real content -- accurate aside
from the one documented medication-name weakness noted above.

### NOT yet built / open items (explicitly tracked)
- pyannote.audio version drift (4.0.7 vs intended 3.1.1) -- unresolved, see above
- Frontend trigger UI for transcription (mirrors chunking/upload -- still no frontend
  audio surface at all across Phases 7-9)
- Background task queue -- still not decided/built, now needed for THREE long-running
  steps (normalize, chunk, transcribe), pressure increasing each phase
- Confidence scoring, quality assessment, hallucination/omission detection -- Phase 10
- Any handling of the medication-name-error class of mistake -- Phase 10/11/12 territory
  (ground truth corrections, HITL, NER validation) per user's own correct framing

## Full phase roadmap (from original plan)
Phase 0: WSL/env setup — DONE
Phase 1: Docker Compose (Postgres+Redis+pgAdmin) — DONE
Phase 2: DB schema + Alembic — DONE
Phase 3: FastAPI skeleton, structured logging, health checks — DONE
Phase 4: Auth & RBAC, sessions, audit logging, admin user mgmt — DONE
Phase 5: Remaining admin APIs (patient CRUD, HITL queue viewer, audit log viewer w/ filtering) — DONE
Phase 6: Frontend (React+Vite+TS) — DONE
  Auth flow, role-based routing/gating, forced password-change interception, styled
  AppShell with role-accent sidebar, and working UI for every Phase 5 API (patients,
  users, HITL queue, audit log). Doctor-role pages are overview-only placeholders --
  intentional, since doctor review functionality depends on Phase 14 (doctor review
  workflow), not missing/forgotten.
Phase 7: Audio ingestion pipeline — DONE (backend scope)
  Full pipeline tested end-to-end on real audio: upload/record endpoints, ffprobe
  validation, ffmpeg normalization to 16kHz mono WAV, duplicate detection, storage.
  Also added minimal appointments API as a discovered prerequisite. Frontend
  upload/recording UI explicitly deferred by user decision -- see note above.
Phase 8: Chunking (VAD + speaker diarization) — DONE (backend scope)
  Silero VAD + pyannote diarization (CPU, 2-speaker hardcoded), merged into chunk
  boundaries with speaker labels, physically extracted via ffmpeg, persisted to
  audio_chunks. Two real bugs found and fixed during testing (unbounded chunk
  duration, missing terminal enum status). pyannote version drifted from intended
  pin (see Phase 9 notes) -- open item.
Phase 9: Model orchestrator + local MedASR integration — DONE (backend scope)
  Identified and integrated the real google/medasr model (105M param Conformer,
  released Dec 2025, after Claude's training cutoff -- verified via web search, not
  assumed). Input format (16kHz mono int16) matches Phase 7's normalization output
  exactly. Built the GPU model orchestrator singleton (app/services/
  model_orchestrator.py) enforcing MedASR/MedGemma mutual exclusion on 8GB VRAM via
  an asyncio.Lock wrapping the full load-or-reuse decision, with explicit
  gc.collect()+torch.cuda.empty_cache() on unload -- generic (loader_fn pattern) and
  ready for Phase 13's MedGemma to plug into the same mechanism without rework.
  transformers>=5.0.0 requirement resolved cleanly from stable PyPI (5.16.1) --
  the model card's git-commit install workaround was a release-day-only requirement,
  already superseded, so no unstable dependency was introduced.
  OPEN ITEM discovered: pyannote.audio had silently drifted to 4.0.7 from the 3.1.1
  pinned in Phase 8 (root cause not fully determined, likely a transitive dependency
  pull). User decided to leave as-is since CPU-only usage has been unaffected by the
  known VRAM regression (which is GPU-specific) -- but flagged as worth revisiting
  now that Phase 9 introduces real concurrent GPU workloads into the same system.
  Real bug found and fixed: batch_decode() defaulting to skip_special_tokens=False,
  leaking a stray </s> token into transcript text -- confirmed via docs, fixed with
  skip_special_tokens=True + .strip().
  Quality validated carefully, not assumed: first test (short ~5s chunk) produced
  fragmented output; rather than concluding poor model quality, retested against a
  longer complete-utterance chunk, which produced clean, medically coherent text with
  exactly one error (a medication brand name mis-transcribed) -- matching the model
  card's own documented limitation around non-standard medication names exactly.
  Confirmed the short-chunk issue was a boundary-truncation artifact, not a model
  problem.
  Transcription orchestrator (app/services/transcription_orchestrator.py) persists
  ONE Transcript row per chunk (source=local_asr, status=draft,
  confidence_score=None -- explicitly not a placeholder, real scoring is Phase 10's
  job), matching the schema's own nullable audio_chunk_id design intent. Idempotent
  re-run, same pattern as chunking. API: POST /audio/{id}/transcribe,
  GET /audio/{id}/transcripts -- both separate/explicit calls, not automatic, same
  reasoning as chunking (real GPU inference time, no task queue yet).
  Full pipeline (upload->normalize->chunk->transcribe) tested end-to-end on a real
  ~7.5min/29-chunk recording and confirmed working.
  Frontend UI and background task queue remain explicitly deferred, same pattern as
  Phases 7-8 -- queue pressure is now real across THREE separate long-running
  pipeline steps (normalize for long files, chunk, transcribe), not just one.
Phase 10: Transcript quality engine — DONE (backend scope)
  Real per-token confidence scoring achieved (not a heuristic proxy) -- confirmed by
  direct inspection that MedASR's generate(output_scores=True, return_dict_in_generate
  =True) returns a `logits` tensor [1, seq_len, 512] perfectly aligned with `sequences`
  [1, seq_len] (verified via test script before building anything around the
  assumption). Mean + min per-token confidence both computed (app/services/
  medasr_service.py _transcribe_sync), validated against two known real examples
  before trusting the signal: known-fragmented chunk scored meaningfully lower mean
  confidence (0.69) than known-good chunk (0.80) -- confirms the signal tracks real
  quality, not noise.
  Heuristic checks added (app/services/quality_engine.py): repetition detection
  (N-gram repeat counting, a documented general ASR failure mode), words-per-second
  sanity (too sparse -> omission_suspected, too dense -> hallucination_suspected),
  plus a deliberate "combined weak signals" escalation tier (borderline min-confidence
  + dense speech rate together, even if neither alone crosses its hard threshold) --
  chosen over just lowering a single threshold, to avoid overfitting to one example.
  HONEST OPEN GAP, not hidden: the real known medication-name error (chunk_0028,
  "Dirid") still passes as accept=true with current thresholds -- documented and
  deliberately NOT threshold-tuned away using only two real data points, since that
  would be overfitting rather than real calibration. True medical-term validation is
  correctly deferred to Phase 12 (BioClinicalBERT NER), per user's own scoping
  decision.
  Full pipeline tested end-to-end for the first time with real multi-chunk data (31
  chunks from the same test recording): quality_report persisted per transcript,
  transcript.status correctly split between draft (accepted) and flagged_for_review,
  HITL queue populated for real for the first time (previously only tested against an
  empty queue in Phase 6) -- confirmed via both /docs and the actual frontend HITL
  page built in Phase 6, INCLUDING the claim workflow (one item successfully claimed
  by an admin, showing status=in_review with assigned_admin_id set) -- this was the
  first live-data test of that page's full interaction loop.
  Real observations from live data worth carrying forward: (1) one HITL item is
  created per flag, so a chunk tripping two flags (e.g. low_asr_confidence +
  omission_suspected, seen on 2 real chunks) produces two separate queue cards for
  one underlying problem -- functionally correct but a possible future UX
  consideration (grouping by transcript_id) for the admin HITL page, not fixed now.
  (2) Some accepted (draft-status) transcripts still contain visible minor
  transcription errors that don't trip any current flag -- expected and consistent
  with treating Phase 14's doctor review as the real final safety net, not this
  engine as a complete solution.
  Frontend UI for triggering transcription/viewing quality reports directly on a
  transcript remains deferred (same pattern as Phases 7-9) -- the ONLY frontend
  surface exercised so far is the pre-existing HITL admin page, which happened to
  already exist from Phase 6.
Phase 11: Cloud ASR fallback + consensus + HITL trigger — DONE (backend scope)
  DESIGN NOTE: diverged from the original "fallback-only" framing in the resource plan
  doc, per explicit user decision after discussion. Azure AI Speech now runs on EVERY
  chunk, concurrently with MedASR (asyncio.gather), regardless of MedASR's quality or
  speed -- not a conditional fallback. Deliberate robustness-over-cost trade-off, made
  with the real cost implication flagged clearly at the time (usage-billed, every
  transcription run now costs money proportional to total audio duration, including
  every dev/test re-run); user accepted this knowingly ("regardless of cost").
  Graceful-degradation requirement (explicit user request): Azure must never break or
  block the pipeline. Two layers: (1) is_azure_configured() skips attempting Azure
  entirely (zero cost/risk) when credentials are unset -- AZURE_SPEECH_KEY/REGION
  changed to optional (empty-string default), unlike the required HUGGINGFACE_TOKEN;
  (2) a deliberately broad try/except in azure_asr_service.py catches any failure
  (auth, network, quota, SDK-internal) and returns a clean "unavailable" result rather
  than raising -- one of the rare correct uses of a broad except, explained inline.
  Real Azure integration (app/services/azure_asr_service.py): Speech SDK,
  recognize_once() (short pre-segmented chunks, not the streaming API),
  OutputFormat.Detailed requested specifically for a real per-chunk confidence score
  (NBest[0].Confidence) -- needed for genuine quality comparison, not text-similarity-
  only comparison.
  Consensus logic (app/services/consensus_service.py) -- NOT algorithmic/ROVER-style
  merging, deliberately: fabricating a third "best guess" transcript was explicitly
  rejected as worse than presenting two real candidates to a human when automated
  resolution isn't confident. Text similarity (difflib SequenceMatcher, chosen over
  embedding similarity specifically because semantic similarity could mask real
  word-level ASR errors) determines agreement; on disagreement, only auto-resolves to
  the clearly-better source if BOTH confidences are known AND the gap exceeds
  CLEAR_QUALITY_GAP_THRESHOLD (0.15, conservative chosen default, not yet calibrated
  against a large real dataset) -- otherwise creates a CONSENSUS_MISMATCH HITL entry
  with both transcripts preserved in quality_report, never guesses.
  Integrated into transcription_orchestrator.py: consensus outcome can flag a
  transcript for review even when Phase 10's quality engine alone found no issue with
  MedASR's output -- new coverage Phase 10 couldn't provide by itself. Chosen source's
  text/model_name persisted on the Transcript row; the non-chosen source's full result
  preserved inside quality_report["consensus"] for audit traceability (not using the
  formal supersedes_id versioning mechanism -- reserved for human corrections, this is
  an automated same-generation source choice).
  Tested end-to-end on the full real 31-chunk recording (not just isolated single-
  chunk tests): confirmed a real mix of consensus outcomes across chunks, and
  confirmed CONSENSUS_MISMATCH entries appearing in the HITL queue alongside the
  existing Phase 10 quality-flag entries.
Phase 12: NER pipeline — DONE (backend core: extraction + validation, tested on real data)
  ExtractedEntitySet schema re-confirmed: appointment_id, transcript_id, target_role
  (nurse vs doctor schema split), raw_entities, validated_entities, ner_model_name/
  version, validation_passed, validation_report, confidence_score, supersedes_id.
  MODEL RESEARCH (significant real investigation, not a quick pick):
  1. Base Bio_ClinicalBERT (emilyalsentzer/Bio_ClinicalBERT) confirmed to be a raw
     Fill-Mask/embeddings model, NOT ready-to-use NER -- would need a fine-tuned head
     or a fine-tuned community checkpoint. User chose to research NER options
     independently rather than pick under pressure.
  2. User's own scoping decision (delivered after independent research): use scispaCy
     as the initial production NER layer; keep Bio_ClinicalBERT available as a future
     option if a project-specific fine-tune on real annotated data is ever justified.
  3. scispaCy model selection: real published precision numbers checked before
     picking -- en_core_sci_* (general mention detector) scored as low as 8% precision
     on NCBI-disease in one cross-corpus study; en_ner_bc5cdr_md (disease+chemical,
     trained specifically on BC5CDR) scored a real, credible 84.28 F1 on its own
     target evaluation per scispaCy's own published benchmarks (allenai.github.io/
     scispacy) -- selected en_ner_bc5cdr_md on this basis.
  4. BLOCKER FOUND: en_ner_bc5cdr_md-0.5.4 (only available release) fails to load
     under the project's actual environment -- ConfigValidationError ('True' is not
     <class 'bool'>), a known class of scispaCy-vs-current-spaCy config-schema
     incompatibility (confirmed via allenai/scispacy's own GitHub issues #303, #400,
     a recurring pattern across scispaCy's history). COMPOUNDING ISSUE: scispaCy 0.6.2
     requires numpy<2.0, but the project's existing audio stack (librosa, pyannote
     4.0.7, torch) is on numpy 2.x -- downgrading numpy risks regressing the already-
     tested Phases 7-11 pipeline. No newer scispaCy model release exists to route
     around the spaCy config issue (v0.5.4 is the only release for every scispaCy
     model, confirmed directly from the official model list).
  5. USER DECISION: abandon scispaCy for this project given the real, compounding
     dependency conflict; find a transformers-native alternative instead (avoids
     numpy/spaCy conflict entirely, reuses the exact same install pattern already
     proven working for MedASR in Phase 9).
  6. FINAL MODEL DECISION: OpenMed (huggingface.co/OpenMed) -- verified HF org,
     published arXiv paper (2508.01630), Apache-2.0 license throughout, 2,000+ models,
     transformers-native (AutoModelForTokenClassification / pipeline("token-
     classification")), explicit on-device/privacy-by-design framing (relevant for a
     government medical system). IMPORTANT DIFFERENCE from en_ner_bc5cdr_md: OpenMed
     does not offer one combined disease+chemical model -- entity types are split into
     separate single-purpose models (PharmaDetect for chemicals/drugs, DiseaseDetect
     for diseases, plus many irrelevant types like Anatomy/Genome/Species not needed
     here). Selected TWO models to match original bc5cdr coverage:
       - OpenMed/OpenMed-NER-PharmaDetect-SuperClinical-434M (chemical/medication
         entities, B-CHEM/I-CHEM, real published F1 0.9614/precision 0.9520/
         recall 0.9710 on BC5CDR-Chem, #1 ranked among OpenMed's own BC5CDR-Chem
         model variants)
       - OpenMed/OpenMed-NER-DiseaseDetect-SuperClinical-434M (disease entities,
         same SuperClinical-434M base architecture/size class for consistency;
         confirmed to exist and actively maintained, exact F1 not yet pulled into
         this conversation -- verify on first real use)
     Both 434M params (deberta-v3-large based) -- meaningfully larger than MedASR
     (105M) or base BioClinicalBERT (~110M), still CPU-workable per resource plan but
     worth watching combined RAM footprint of TWO 434M models loaded together against
     the 6GB system RAM ceiling once real integration/testing begins.
  ### Integration built (app/services/ner_service.py, ner_validation.py, ner_orchestrator.py)
  ner_service.py: both models loaded via transformers pipeline("token-classification",
  aggregation_strategy="simple"), CPU-only (no device specified -- GPU reserved for
  MedASR/MedGemma per resource plan, not routed through model_orchestrator.py since
  these never touch VRAM, same reasoning as VAD/diarization staying outside it too).
  Both pipelines kept resident once loaded (module-level globals).

  REAL BUG FOUND AND FIXED THROUGH LIVE DATA TESTING (not caught by the earlier
  single-sentence test): aggregation_strategy="simple" merges sub-word pieces WITHIN
  one model's output, but does NOT merge separate adjacent entity spans that are two
  genuinely separate emitted entities with zero gap between them -- observed on real
  transcripts: "Dirid" was returned as "Di"+"rid" (two adjacent CHEM entities),
  "paracetamal" [sic -- reflects the actual garbled source transcript text, not a bug]
  as "pa"+"racetam"+"al" (three adjacent CHEM entities). FIX: added
  _merge_adjacent_fragments() in ner_service.py -- merges consecutive entities with
  the SAME label where entity B starts exactly where entity A ends (zero-gap
  adjacency, since real word boundaries always have a space/punctuation between
  them). Merged entity's confidence = mean of its pieces' scores. This fix happens
  BEFORE validation ever sees the entities -- raw_entities in the DB now contains
  correctly-reconstructed terms, not raw tokenizer fragments.

  ner_validation.py: confidence-based validation, thresholds chosen from REAL
  evidence (a full 49-transcript batch), not assumed:
    - CONFIDENCE_ACCEPT_THRESHOLD = 0.75 -- clean true-positive catches (diarrhea,
      vomiting, gastroenteritis, asthma, fever, weight loss, Dirid, paracetamal)
      clustered 0.87-0.96; clear false positives (bare "blood", "gas", low-context
      "pain") clustered 0.56-0.69; 0.75 sits with margin on both sides.
    - MIN_ENTITY_TEXT_LENGTH=4 + SHORT_ENTITY_CONFIDENCE_FLOOR=0.90 -- a NARROWER,
      two-part safeguard, not a standalone length rule. FIRST VERSION OF THIS RULE
      WAS TOO BROAD: a plain length-only cutoff (reject anything <4 chars) was
      initially built to catch "kay" (a 3-char CHEM false positive at 0.884
      confidence, from "okay"), but that same blanket rule then WRONGLY rejected the
      legitimate high-confidence "Di"/"rid" and "pa"/"al" fragments before the
      merge fix existed -- caught via live-data re-test, not assumed correct.
      NARROWED FIX (combined with the merge fix above, per explicit user
      instruction "both"): short entities are now only rejected if they ALSO fail
      a higher 0.90 confidence bar -- "kay" (0.884, below 0.90) still correctly
      rejected; "le" (0.806, below 0.90) still correctly rejected; merged "Dirid"
      (0.924, and no longer short at all post-merge) now correctly accepted.
  CRITICAL DESIGN REQUIREMENT (explicit user instruction, followed exactly):
  rejected entities are NEVER deleted from the database. raw_entities is set once,
  permanently, unfiltered, containing every entity either model produced regardless
  of validation outcome -- validated_entities is a SEPARATE view with per-entity
  status ("accepted"/"rejected") and a human-readable rejection_reason. Full
  auditability preserved; thresholds can be re-tuned later against the same
  permanently-stored raw data without re-running inference.

  ner_orchestrator.py: runs extraction+validation over every transcript for an
  appointment (not just one recording's chunks -- queries by appointment_id, so
  covers all transcripts regardless of which recording produced them), idempotent
  re-run (clears prior entity sets before regenerating, same pattern as chunking/
  transcription). target_role hardcoded to NURSE for all extractions in this phase
  -- the sensible default since intake happens first and the project has no logic
  yet to separate "nurse portion" vs "doctor portion" of a conversation; doctor-
  targeted extraction (medication orders, diagnoses) is a natural refinement for a
  later phase, not built now. BUG FIXED: ner_model_name was initially hardcoded to
  only the Pharma model's ID even though many persisted entities came from the
  separate Disease model -- fixed to a name reflecting both models were used.

  API endpoints (app/api/audio.py): POST /audio/{recording_id}/extract-entities,
  GET /audio/{recording_id}/entities.

  Tested end-to-end on the full real 31-transcript/49-entity-set dataset (some
  transcripts produced multiple entity sets across re-runs during bug fixes) used
  throughout Phases 7-11. Every entity manually spot-checked against source text
  across three full passes (before merge-fix, and after) -- this was a genuinely
  iterative, evidence-driven build: real data caught two real bugs
  (model-name misattribution, then the fragment/length-rule interaction) that no
  amount of single-sentence pre-testing would have surfaced.

  ### NOT YET DONE (explicitly deferred, tracked so not forgotten)
  - Assertion detection (present/absent/hypothetical) and temporal expression
    extraction -- confirmed not covered by either OpenMed model or the original
    scispaCy plan; needs separate rule-based or model-based logic, not designed yet.
  - Doctor-targeted extraction (target_role=DOCTOR) -- currently everything targets
    NURSE; doctor-specific extraction (medications prescribed, diagnoses given)
    needs a way to distinguish doctor vs nurse portions of a conversation, which
    doesn't exist yet.
  - Frontend UI for triggering NER / reviewing extracted entities -- not started,
    same deferred pattern as audio upload/chunking/transcription UI since Phase 7.
  - Threshold recalibration against a larger, more varied real dataset -- current
    thresholds (0.75 / 0.90) are evidence-based but drawn from ONE recording's
    worth of data; a second real recording with different speakers/audio quality
    would be a meaningful next validation step.
  - Combined RAM footprint of two 434M NER models alongside the rest of the pipeline
    under real concurrent load has not been stress-tested -- flagged in the prior
    entry, still genuinely unverified.
Phase 13: MedGemma integration — DONE (backend core: drafting + structured parsing, tested end-to-end)
  MODEL VERSION RESEARCH: original plan named "MedGemma-4B-it" -- confirmed via search
  that MedGemma 1.5 (google/medgemma-1.5-4b-it) exists, released Jan 2026 in the SAME
  announcement wave as MedASR, with notably better text/EHR reasoning (EHRQA 68%->90%)
  vs the original MedGemma 1 the plan doc predates. User chose 1.5 explicitly.
  Same HAI-DEF gated license/terms-acceptance pattern as MedASR. Model card's own
  explicit limitation respected: "not evaluated/optimized for multi-turn applications"
  -- service deliberately uses single-turn prompts only, never conversational.
  RUNTIME FORMAT DECISION: original plan assumed GGUF Q4_K_M (~3GB). Real model card
  examples use full transformers+bfloat16 (~8GB), not GGUF (which only exists as
  third-party community quantizations). User chose the officially-documented
  transformers+bfloat16 path over GGUF.
  REAL, MEASURED VRAM FINDING (not assumed): loading MedGemma ALONE (no MedASR
  resident) on the 8GB card produces "Some parameters are on the meta device because
  they were offloaded to the cpu" -- confirmed via nvidia-smi: 6167MiB/8188MiB used,
  ~2GB headroom, with partial CPU offload happening even in the best-case (nothing
  else loaded) scenario. This directly validates why model_orchestrator.py's strict
  mutual-exclusion design (built in Phase 9, unused until now) is a hard requirement,
  not just tidy architecture -- there was never going to be room for both models
  resident simultaneously.
  REAL, MEASURED PERFORMANCE: ~2.75-2.9 tokens/second, consistently reproduced across
  three separate real generations (isolated test, full-appointment test, final
  corrected-schema test). A ~230-token real draft took 83.6s. User explicitly decided
  to ACCEPT this speed rather than pursue 8-bit/4-bit quantization -- reasoned as
  "more of the same" given the background-task-queue problem was already open and
  unresolved since Phase 8, not a new category of blocker.
  REAL BUG FOUND AND FIXED AT ROOT CAUSE (via live data, not synthetic testing):
  investigating why a real MedGemma prompt was exactly 2x bloated with duplicate
  transcript/entity content revealed 34 ORPHANED Transcript rows with
  audio_chunk_id=NULL. Root cause: Transcript.audio_chunk_id has ondelete="SET NULL"
  (by design, from Phase 2/9). When Phase 8's chunking orchestrator re-ran (user had
  re-chunked+re-transcribed the same recording during testing), deleting old
  AudioChunk rows correctly triggered SET NULL on any Transcript pointing at them --
  but nothing ever cleaned up those now-orphaned Transcript rows, and Phase 9's own
  idempotency check only looked for transcripts tied to CURRENT chunk IDs, so orphans
  were invisible to it and silently accumulated across every re-chunk cycle.
  DOWNSTREAM CONTAMINATION: Phase 12's NER pipeline (queries by appointment_id, not
  recording_id) had also run extraction on every orphaned duplicate, doubling
  ExtractedEntitySet rows too. FIX: chunking_orchestrator.py now explicitly deletes
  any appointment's transcripts with audio_chunk_id IS NULL before deleting the
  chunks that would orphan new ones, closing the gap at its source. Existing bad data
  (34 orphaned transcripts + their duplicate entity sets) cleaned up via a one-off
  script. This bug would have compounded indefinitely with every future re-chunk
  cycle if left unfixed.
  SCHEMA CORRECTION (explicit user correction, caught before persistence was fully
  built): nurse IntakeForm and doctor Prescription schemas were INITIALLY BUILT
  BACKWARDS. First version put MedGemma's clinical-reasoning output (chief complaint,
  symptoms, suggested management) into IntakeFormData. User corrected: nurse intake
  is objective/procedural (vitals -- BP, height, weight, temperature, pulse; prior
  test orders and whether they were completed/results), NOT symptoms/diagnosis/
  treatment -- that belongs to the DOCTOR's Prescription schema (problem, symptoms,
  medications, advice, follow-ups, existing conditions). Both schemas rebuilt
  correctly:
    app/schemas/intake_form.py    VitalSigns (all optional numeric fields -- a
                                   conversation may only mention some vitals, not all),
                                   PriorTestResult (test_name, was_completed,
                                   result_summary), reason_for_visit + known_allergies
                                   as EXPLICITLY OPTIONAL fields per user's own scoping
                                   decision ("1 and 2 but keep it as optional fields").
                                   NOT YET POPULATED BY MEDGEMMA -- this phase only
                                   built and validated the DOCTOR-side (Prescription)
                                   drafting pipeline; nurse intake drafting from vitals
                                   mentioned in conversation is a real, separate future
                                   piece of work, not done.
    app/schemas/prescription.py   MedicationOrder (name/dosage/frequency/duration/
                                   instructions), PrescriptionData (problem_summary,
                                   symptoms, existing_conditions, medications, advice,
                                   follow_up) -- field names match MedGemma's own
                                   naturally-produced section headers, prompt updated
                                   to request this exact shape plus an explicit
                                   "Medication:" heading convention for structured
                                   drug extraction.
  Both schemas share an ai_generated/ai_model_name/ai_model_version/ai_raw_draft_text
  provenance block -- never silently presents AI output as human-authored; raw text
  ALWAYS preserved alongside parsed structured fields, same "never destructively
  lose the original" principle as every prior phase's versioning design.

  PARSER REBUILT after a real, live-data parsing failure (not caught by design review
  alone): first version used regex substring-search for section boundaries, which
  broke on real output -- the word "symptoms" appearing INSIDE the Problem Summary's
  own prose sentence was mistaken for the real Symptoms heading, truncating that
  section; a dedicated "**Medication:**" heading (items on separate bulleted lines
  below it) was completely missed because the original medication regex only checked
  for inline same-line format. REBUILT (app/services/prescription_draft_parser.py) as
  a single-pass line-by-line state machine: a line is only treated as a heading if
  the ENTIRE stripped line matches a known section name exactly (not a substring
  match anywhere in the text) -- fundamentally immune to the "heading word appears in
  prose" failure mode. Re-tested against the exact real raw output that broke the
  first version: all fields now parse correctly (full untruncated problem summary,
  clean 8-item symptom list, correct 2 medications with full dosage details, no stray
  markdown-fragment list items).

  app/services/prescription_orchestrator.py -- builds prompt, generates, parses,
  persists as Prescription(is_final=False) -- ALWAYS false on creation, doctor must
  explicitly review/finalize (Phase 14, not built yet). KNOWN SCHEMA LIMITATION,
  flagged not hidden: source_entity_set_id is a single FK but real drafts are built
  from MANY transcripts'/entity sets' worth of data (10 relevant transcripts fed one
  real test draft) -- first contributing entity set recorded as a representative
  reference; full traceability lives in ai_raw_draft_text (prose) plus prompt
  construction logic, not a clean queryable link. _any_live() input_source detection
  is a stub (always False) -- real provenance requires a join through AudioRecording
  not yet added, flagged as cosmetic-field approximation, not solved.

  API: POST /audio/appointments/{appointment_id}/draft-prescription (require_doctor).
  Tested end-to-end on real full-appointment data (10 relevant transcripts after
  duplication fix + entity-bearing filtering, 2960-char prompt): confirmed grounded,
  non-hallucinating output (correctly hedged incomplete info like "type not
  specified" rather than inventing details; correctly preserved a real negative
  finding -- "antibiotics not currently recommended" -- that no NER entity captured;
  correctly extracted real dosage details verbatim; correctly separated Dirid as an
  unverified pharmacy item rather than inventing a drug classification for it).

  NOT YET BUILT: nurse-side intake form drafting from vitals mentioned in
  conversation (this phase only validated doctor-side prescription drafting);
  frontend UI for triggering/reviewing drafts (same deferred pattern since Phase 7);
  Phase 14's actual doctor review/edit/approve workflow that turns is_final=False
  drafts into real finalized prescriptions.
Phase 14: Doctor review workflow — DONE (backend core: edit, finalize, PDF generation)
  Prescription model's existing versioning fields re-confirmed before building:
  supersedes_id, edited_by_id, is_final/finalized_at, pdf_storage_path (nullable
  until finalization) -- all already anticipated since Phase 2, none required schema
  changes this phase.
  EDIT WORKFLOW DECISION (explicit user choice, asked directly before building):
  in-place editing of a draft, NOT a new versioned row per edit. User's reasoning:
  a doctor iterating on a draft (fixing one dosage, adding a note) shouldn't spam the
  version history at keystroke granularity -- the meaningful version boundary is
  "AI draft as originally generated" vs "what was actually finalized," and the
  original AI output is never lost regardless of edits because it's separately
  preserved in ai_raw_draft_text (untouched by edits) rather than needing a full row
  version per change. supersedes_id is correctly reserved for a genuinely different,
  rarer case: correcting an ALREADY-FINALIZED record after the fact -- not built this
  phase, flagged as a real future addition if needed.
  app/services/prescription_service.py: update_prescription_draft() rejects edits to
  an already-finalized prescription (real error, not silent no-op) -- tested and
  confirmed working. Provenance fields (ai_generated/ai_model_name/ai_model_version/
  ai_raw_draft_text) are explicitly re-asserted from the existing row on every edit,
  not trusted from the edit payload -- prevents a frontend that only sends editable
  clinical fields from silently blanking out the true origin record.
  finalize_prescription() sets is_final=True + finalized_at, then triggers PDF
  generation. PDF failure does NOT roll back finalization (deliberate: finalization
  is the clinically meaningful action; a PDF rendering bug is a presentation-layer
  problem and shouldn't be able to undo a doctor's actual approval) -- failure is
  logged loudly, pdf_storage_path stays NULL, a future "regenerate PDF" endpoint
  would be the correct fix path, not built now.

  PDF generation (app/services/prescription_pdf_service.py): reportlab
  SimpleDocTemplate/Platypus, per the project's pdf skill guidance. Real
  patient/doctor/appointment fields joined and rendered (patient name/MRN/DOB/sex,
  doctor name, finalization timestamp), structured sections (Problem Summary,
  Symptoms, Existing Conditions, Medications as a real table with dosage/frequency/
  duration columns, Advice, Follow-up). EXPLICIT AI-PROVENANCE DISCLAIMER printed
  directly on the PDF itself (not just stored in the DB) whenever ai_generated=true --
  states the document was AI-drafted, names the model, and states it was reviewed/
  approved by the named doctor and requires independent clinical verification. This
  directly carries through MedASR's and MedGemma's own model-card requirements (both
  explicitly state outputs need independent verification and shouldn't be presented
  as authoritative) onto the actual clinical artifact a patient/auditor would see,
  not just an internal DB flag nobody outside the system would ever notice.
  Storage: storage/prescriptions/<prescription_id>.pdf, same relative-path convention
  as Phase 7's audio storage.

  API: GET/PATCH /prescriptions/{id}, POST /prescriptions/{id}/finalize (all
  doctor-only via require_doctor except GET). Every edit/finalize action writes to
  the existing Phase 4 audit log (write_audit_log) -- no new audit mechanism needed,
  reused the established pattern.

  Tested end-to-end on real data: draft -> edit (confirmed provenance fields survive
  editing intact) -> finalize (confirmed is_final/finalized_at set, PDF generated and
  confirmed readable with correct patient/doctor info, structured sections, and the
  AI disclaimer) -> re-edit attempt on finalized record correctly rejected.

  NOT YET BUILT: PDF regeneration endpoint (for the PDF-failure-but-finalized edge
  case); post-finalization correction workflow using supersedes_id (the rarer
  "correct an already-finalized record" case); frontend UI for the doctor review
  workflow (same deferred pattern since Phase 7 -- there is still no frontend
  surface for prescriptions/PDFs at all, only the pre-existing Phase 6 admin pages).
Phase 15: Observability — DONE (Prometheus metrics + cross-request tracing; Grafana
  explicitly skipped per user decision -- no ops workflow/dashboard consumer exists
  yet to justify the setup cost)
  PRE-EXISTING, CONFIRMED ADEQUATE: structured JSON logging (structlog), console +
  rotating file output, per-request request_id correlation -- all built in Phase 3,
  needed no rework this phase.
  Scope was explicitly narrowed in conversation with the user before building: the
  roadmap's "Prometheus metrics, optional Grafana, tracing" was reduced to metrics +
  tracing only, skipping Grafana, on the reasoning that a dashboard nobody is
  regularly looking at yet adds setup cost without real payoff at this project's
  current stage.

  app/core/metrics.py: metric selection deliberately targeted at THIS project's own
  documented pain points, not generic boilerplate --
    - medstt_pipeline_stage_duration_seconds (histogram, labeled by stage+outcome):
      directly answers the recurring "how slow is this really" question that, before
      this phase, only ever had anecdotal single-run answers scattered through this
      conversation (26min diarization pre-thread-fix, 83.6s MedGemma generation,
      etc.) -- now systematically captured for every real run of every stage.
    - medstt_gpu_vram_used_bytes / reserved_bytes / medstt_gpu_model_slot_loaded:
      directly motivated by Phase 13's finding that MedGemma alone nearly saturates
      the 8GB card (6167/8188MiB) -- makes that condition continuously observable
      rather than something only found by chance via a manual nvidia-smi check.
    - medstt_hitl_items_created_total, medstt_transcript_quality_outcome_total,
      medstt_consensus_outcome_total, medstt_ner_entity_validation_outcome_total:
      turn outcomes that were previously only visible by manually reading JSON API
      responses (as done extensively in Phases 10-12) into continuously queryable
      counters.
  app/core/metrics_helpers.py: track_pipeline_stage() context manager -- consistent
  timing/in-progress/success-failure labeling across all four instrumented
  orchestrators, avoiding hand-rolled inconsistent instrumentation per stage.
  Wired into: chunking_orchestrator.py (stage="chunk"), transcription_orchestrator.py
  (stage="transcribe", plus quality/consensus/HITL counters at their existing
  decision points), ner_orchestrator.py (stage="ner", plus entity validation
  counters), prescription_orchestrator.py (stage="draft_prescription"). Also wired
  into model_orchestrator.py for GPU VRAM gauges on every load/unload.
  GET /metrics (app/api/metrics.py) -- deliberately NOT behind auth, per standard
  Prometheus convention (scraper has no session concept) and because it exposes only
  aggregate counters/histograms, never patient data or PII; flagged that network-
  level restriction (e.g. IP allowlist at a reverse proxy) would be the correct place
  to further restrict this later if a stricter government network policy requires it,
  not application-level auth.
  Tested end-to-end: confirmed real pipeline stage duration values appearing in
  /metrics output after a real re-chunk run (previously only anecdotal timings).

  app/core/tracing.py: bind_appointment_trace() -- cross-REQUEST correlation via
  structlog.contextvars (same mechanism as Phase 3's request_id, deliberately reused
  rather than introducing a new tracing library/backend), since each pipeline stage
  is its own separate HTTP request with its own fresh request_id, unable on its own
  to correlate an appointment's FULL multi-stage journey. Chose appointment_id (not
  recording_id) as the binding key specifically because it's the one identifier
  consistent across every stage including NER/prescription drafting, which only
  naturally have appointment_id in scope, not recording_id. Deliberately did NOT
  reach for a full OpenTelemetry/Jaeger-style tracing stack -- no existing trace-
  collection infrastructure in the Docker Compose setup, and Grafana was already
  deferred in this same phase, so a full tracing backend would have been
  infrastructure for infrastructure's sake at this project's current stage.
  Tested end-to-end: confirmed appointment_id appears in log lines alongside the
  pre-existing request_id, and confirmed grepping the log file for one real
  appointment_id surfaces its full history across multiple different pipeline
  stages/separate requests -- the actual concrete proof this phase's goal was met,
  not just that the instrumentation code runs without error.

  NOT YET BUILT: Grafana dashboard (explicitly deferred); alerting on any metric
  threshold (e.g. VRAM approaching capacity, a stage's failure rate spiking) -- pure
  observability was built, automated response to what's observed was not, and
  wasn't in this phase's agreed scope.
Phase 16: Hardening — DONE (scope explicitly narrowed to security/hardening only,
  per user decision, before implementation began; feature/architecture gaps like the
  task queue, frontend UI, and nurse intake form were deliberately tracked separately
  rather than folded in, keeping this phase's focus clean)
  CORS: was hardcoded to localhost:5173 only since Phase 3 -- now CORS_ALLOWED_ORIGINS
  setting (comma-separated, environment-driven), same dev default preserved. OPEN:
  must be set to the real production origin(s) at deployment, never "*" (forbidden
  by browser spec when combined with allow_credentials=True anyway, but worth stating
  explicitly given this is a cookie-authenticated API over patient data).
  Cookie secure flag: was hardcoded False -- now COOKIE_SECURE setting. OPEN, flagged
  clearly: must be manually flipped to True behind real HTTPS at deployment; flipping
  prematurely breaks login entirely (browsers won't send a secure cookie over plain
  HTTP), not just "less secure" -- this needs to be a called-out manual step in
  Phase 17's deployment runbook, not something assumed to happen automatically.
  Redis password: was hardcoded in infra/redis/redis.conf since Phase 1 (flagged as
  a known deferred item in Phase 4's own status notes at the time) -- Redis config
  files have no env-var substitution mechanism (a real Redis limitation, not a gap
  in this project's approach), so fixed via Redis's own supported mechanism: password
  removed from the conf file entirely, now passed via --requirepass command override
  in docker-compose.yml sourced from the existing .env REDIS_PASSWORD, single source
  of truth for both the Redis server and backend client. Verified working via a full
  docker compose down/up cycle plus confirmed the backend could still connect
  post-fix.
  Rate limiting: added on POST /auth/login via slowapi, Redis-backed (reuses the
  existing settings.REDIS_URL property rather than reconstructing a connection
  string by hand -- caught and fixed during build, since hand-reconstructing risked
  silently connecting to the wrong endpoint given the project's known localhost:6380
  vs redis:6379 host/port distinction from Phase 2). 10/minute per-IP, deliberately
  documented as COMPLEMENTARY to, not a replacement for, Phase 4's existing 5-attempt
  account lockout: lockout protects one specific account from targeted brute force
  regardless of source IP; rate limiting protects the endpoint itself from broader
  abuse across many different accounts/usernames from one source. TESTED AND
  CONFIRMED with a real 12-rapid-request script: first ~10 returned 401 (normal
  failed-login), 11th-12th returned 429 -- real verified behavior, not assumed
  correct from the code alone.
  Input validation review (real findings, not assumed clean):
    - Global JSON body size limit: found NO limit existed anywhere for regular JSON
      endpoints (Phase 7's audio upload limit only covered multipart file uploads).
      Fixed via RequestSizeLimitMiddleware, 1MB cap, audio upload/record endpoints
      explicitly excluded (they keep their own larger, correct Phase 7 limit).
      TESTED: confirmed a ~2MB JSON payload returns 413.
    - Malformed UUID path params: reviewed, confirmed ALREADY correctly protected --
      every route across every phase consistently types path params as uuid.UUID,
      FastAPI/Pydantic auto-rejects non-UUID input with 422. No fix needed, verified
      by review rather than assumed.
    - SQL injection: reviewed, confirmed not applicable by construction -- every
      query across the entire codebase uses SQLAlchemy's ORM query builder with
      bound parameters, no raw string-interpolated SQL exists anywhere. No fix
      needed, verified by review.
  Secrets management review: full-repo grep for hardcoded secret patterns performed
  -- only the already-known Redis password was found (now fixed), nothing else.
  Confirmed via git ls-files (actual tracked history, not just the .gitignore rule)
  that .env has never been committed. REAL GAP FOUND AND FIXED: storage/prescriptions/
  (real patient names/MRNs/clinical text in PDFs since Phase 14) was NOT in
  .gitignore -- only storage/audio/ and storage/transcripts/ were covered, an
  oversight from before that directory existed. Fixed; confirmed via git ls-files
  that no PHI-bearing PDF had actually been committed before the fix landed (gap was
  real but hadn't yet caused actual exposure).
  Written deliverable: docs/SECURITY_CHECKLIST.md -- built as an honest, specific
  document reflecting exactly what was tested vs verified-by-inspection this phase,
  not a generic template with everything checked off. Explicitly lists open items
  (HTTPS/TLS itself out of this project's scope -- assumed handled by a fronting
  reverse proxy/load balancer at deployment; pyannote version drift; no task queue;
  no frontend for Phases 7-14; no nurse intake form) rather than hiding them, since
  a document meant to survive real government review needs to be accurate, not
  reassuring.
  NOT ADDRESSED (explicitly out of this phase's agreed scope, not forgotten):
  FIPS 140-2/3 compliance decision (flagged since Phase 4 as a possible future
  requirement, still not resolved -- would require replacing Argon2id with
  PBKDF2-SHA256 for password hashing specifically if ever mandated).
Phase 17: Full docker-compose production profile + deployment runbook + government
  presentation prep — NEXT

## User's stated working style
- Wants terminal commands with exact path context (which folder)
- Prefers file creation via "create file at X, paste this code" rather than heredoc/cat commands
- Wants explanation of what code/steps do, not just the code itself
- Confirms each step works before proceeding — going phase by phase, testing at each checkpoint
- No zip files/archives — always explicit file/folder creation instructions
- Wants frontend to look genuinely designed (proper alignment/spacing, not corner-pushed
  inline-styled blocks) — addressed starting Step 6.7 with a real token system + AppShell
- Wants PROJECT_STATUS.md updated at major completions/milestones, not just end-of-phase