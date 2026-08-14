# NBK Engage

A working, self-hostable live audience engagement platform for classroom and
corporate finance training — MCQs, polls, word clouds, ratings and open-ended
questions, run live from a laptop/projector and answered by participants on
their own phones. Built with **Python + Streamlit** on the frontend and
**Supabase/PostgreSQL** as the shared backend, so every participant's browser
and the host's browser are reading and writing the *same* database rows —
not local, per-tab Streamlit state.

> The name "NBK Engage" is just a working title. Renaming it later only means
> changing `APP_NAME` in `.env` and the page title in `app.py` — nothing in
> the architecture depends on the name.

---

## 1. Architecture at a glance

```
Host browser  ──┐                                   ┌── Participant browser (phone)
                ├──►  Streamlit app (app.py)  ◄──────┤
Admin browser ──┘        │                           └── Participant browser (phone)
                          │  services/database.py
                          ▼
                  Supabase / PostgreSQL
           (sessions, questions, responses, ...)
```

- **Streamlit is a rendering + input layer only.** `st.session_state` is used
  strictly for *local, per-tab* UI bookkeeping (e.g. "which session_id is
  this browser currently looking at", cached immutable question lists,
  prepared Excel export bytes). Every piece of shared state — session
  status, the active question, who has joined, every answer, every score —
  lives in Postgres. That's what lets a host's laptop and ten participants'
  phones all agree on what's happening right now.
- **Realtime is done via polling**, using Streamlit's `st.fragment(run_every=...)`
  (every `POLL_INTERVAL_SECONDS`, default 2s) to re-read the database and
  redraw just the live portion of the screen. This was a deliberate choice
  over WebSockets/Supabase Realtime for the MVP — see [§9](#9-design-notes--known-limitations).
  Both host and participant screens are split so the polling fragment does
  the minimum necessary read + a change check, and the actual question/
  answer UI only re-renders on a real state change — not on every tick — so
  it never flickers or greys out while someone is mid-tap.
- **Scoring is always computed server-side** (`services/scoring.py` +
  `services/session_manager.py`), from the question's stored correct answer
  and a server-measured response time. The client only ever sends "which
  option did the participant pick" — never a score.
- **Two pacing models, chosen per session:**
  - **Host-paced** — the classic model: one shared question at a time, no
    timer, the host manually closes voting and advances (or, in *all-at-once*
    reveal mode, it advances itself once everyone's answered — see below).
  - **Self-paced** — every participant works through all questions
    independently, in any order, with a **Skip** option, at their own speed.
    The host sees live per-participant progress and closes/reveals manually,
    or it closes automatically once everyone has finished.
- **The session lifecycle is an explicit state machine**
  (`services/session_manager.py`): host-paced runs
  `WAITING → QUESTION_ACTIVE → VOTING_CLOSED → RESULTS_REVEALED → LEADERBOARD
  → (loops to QUESTION_ACTIVE, or) → SESSION_ENDED`; self-paced runs
  `WAITING → SELF_PACED_ACTIVE → LEADERBOARD → SESSION_ENDED`. Every
  transition re-reads the current status from the database and validates it
  before writing, so a stale tab or a double-click can't corrupt the flow.
- **Participants only ever see their own results** — correct/incorrect count
  and accuracy percentage, never group-level charts or the ranked
  leaderboard. Group results (donut chart, per-question breakdown, ranked
  leaderboard with everyone's names/scores) are visible to the host/trainer
  only, on the control-room screen.

### Project structure

```
app.py                     Entry point + routing (host/participant/admin) + global CSS
pages/
  host.py                  Trainer console: create/run a session (host-paced or self-paced), control room
  participant.py           Join → wait → answer → personal results (never group results)
  admin.py                 Question sets (create/edit/import nested inside each set), past sessions
components/
  question_card.py         Question prompt, answer widgets, read-only host options preview
  progress.py              "Question X of N" progress bar shown to host + participants
  leaderboard.py           Ranked leaderboard with medals, rank-change arrows, anonymize option (host-only view)
  results.py               Live result bars/pie charts, rating summary, word cloud, open-ended list (host-only)
  review.py                Per-question review with pass/fail badge (a participant's own answers)
  session_report.py        The "Group Results" screen (donut, tiles, per-question breakdown) — host-only
  wordcloud.py              Multi-color word cloud image rendering
services/
  database.py               The ONLY module that talks SQL (SQLAlchemy + psycopg2)
  session_manager.py        Session state machine (both pacing models) + server-side answer submission
  quiz_engine.py            Question sequencing / snapshotting a set into a session
  scoring.py                 Pure scoring math (no DB) — 1 point per correct answer by default
  analytics.py               Poll/MCQ result %, word-cloud frequencies, leaderboard, exports
  diagnostics.py             Temporary poll-cycle timing/query instrumentation — see §9
utils/
  excel_import.py           Bulk question upload straight into a question set + validation + template generator
  excel_export.py           Multi-sheet results workbook (participants/scores/results/raw), built on demand
  qr_code.py                 Join-link QR code generation (auto-detects LAN IP), cached per URL
  network.py                  LAN IP detection backing the QR code
  validation.py              Shared input validation (names, codes, question rows)
  auth.py                    Simple shared-password gate for host/admin
database/
  schema.sql                  Full Postgres schema (tables, views, constraints, triggers) -- fresh installs use this
  migrations/                  Incremental ALTERs for installs that ran an older schema.sql
  seed_questions.py           Seeds 14 sample finance questions + a ready-to-run set
  sample_question_bank.xlsx   The same 14 questions in the Excel import format
tests/                         pytest suite (unit + DB integration)
"Start NBK Engage.bat"         Windows launcher: sets up + starts the server + opens the app window
_open_app_window.bat            Helper invoked by the launcher (waits for the server, opens Edge app mode)
DEPLOYMENT.md                   Full deployment guide: instant internet (ngrok) + permanent custom domain
render.yaml                     Render.com blueprint used by DEPLOYMENT.md's deploy path
```

---

## 2. Prerequisites

- Python 3.10+
- A free [Supabase](https://supabase.com) account (Postgres database)

---

## 3. Supabase setup

1. Go to [supabase.com](https://supabase.com) → **New Project**. Pick any
   region close to you and set a database password (you'll need it below).
2. Once the project is provisioned, open **SQL Editor** and run the entire
   contents of [`database/schema.sql`](database/schema.sql). This creates all
   tables, the `session_leaderboard` / `session_question_results` views,
   indexes and triggers. It's safe to re-run.
3. Get your connection string: **Project Settings → Database → Connection
   string → URI**. Use the **Session pooler** or **Transaction pooler**
   variant, not the direct connection — the direct-connection host is
   IPv6-only unless you pay for Supabase's IPv4 add-on, which many hosting
   platforms (including some Streamlit/Render environments) can't reach
   reliably, causing slow/failed connections. It looks like:

   ```
   postgresql://postgres.xxxxxxxx:YOUR_PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```

   (Port `5432` = Session pooler, `6543` = Transaction pooler — either works;
   this project runs on the Session pooler.) If your password contains
   special characters (`@`, `#`, `%`, ...), URL-encode them (`@` → `%40`, etc.).

> **Already ran an earlier version of `schema.sql`?** Also run everything in
> `database/migrations/` (in order) in the SQL Editor:
> [`001_reveal_mode_and_scoring_defaults.sql`](database/migrations/001_reveal_mode_and_scoring_defaults.sql)
> adds the reveal-mode/anonymous-leaderboard columns and switches the
> default scoring from 1000-points-plus-bonus to flat 1-point-per-correct-
> answer; [`002_group_summary_reveal.sql`](database/migrations/002_group_summary_reveal.sql)
> adds the column backing the "Reveal to Participants" action on the group
> results screen; [`003_self_paced_mode.sql`](database/migrations/003_self_paced_mode.sql)
> adds self-paced mode + the Skip option (`sessions.pacing_mode`,
> `responses.is_skipped`, and the `SELF_PACED_ACTIVE` session status). All
> three are safe to re-run; brand-new installs get everything from
> `schema.sql` directly and don't need any of them.

---

## 4. Local setup

**Windows shortcut:** once your `.env` is configured (step 3 below), you can
skip everything else and just double-click **`Start NBK Engage.bat`** in the
project folder — it creates the virtual environment and installs
dependencies on first run, then starts the server and opens NBK Engage in
its own chromeless app window (via Edge `--app` mode, using the helper
script `_open_app_window.bat`) rather than a regular browser tab, so it
feels like a native app on your desktop. It opens on the same participant
join screen as the deployed web URL — expand **"Are you the trainer?"** to
get to the host console from there. Keep the console window open while
running a session; closing it stops the app. Participants always join from
their own separate, ordinary phone browser — this app-window behavior only
affects your own screen.

Otherwise, the manual steps:

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
# .venv\Scripts\Activate.ps1       # Windows PowerShell
# source .venv/bin/activate        # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# then edit .env and set DATABASE_URL (from step 3 above) and ADMIN_PASSWORD

# 4. Seed the sample finance question bank (optional but recommended)
python -m database.seed_questions

# 5. Run the app
streamlit run app.py
```

Open the URL Streamlit prints (default `http://localhost:8501`).

### `.env` reference

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **Yes** | Supabase Postgres connection string (pooler host, see §3). The app refuses to do anything DB-backed without it, and shows a friendly error instead of crashing. |
| `ADMIN_PASSWORD` | **Yes** | Shared password gating the Host and Admin areas. Participants never see or need this. **Change it from the default before sharing the app with anyone.** |
| `APP_NAME` | No | Cosmetic; shown in the browser tab. |
| `APP_BASE_URL` | No | Join URL / QR code base. Leave at the localhost placeholder for classroom/local-demo use — the app auto-detects this machine's LAN IP instead. Set this to your real deployed URL (e.g. `https://nbk-engage.onrender.com`) when deployed, so the QR code points at the live server instead of your laptop. See [§5](#5-network-access-getting-phones-to-connect). |
| `APP_PORT` | No | Port used when building the LAN join URL (default `8501`, matches Streamlit's default port). |
| `POLL_INTERVAL_SECONDS` | No | How often host/participant screens re-check the database (default 2s; keep at 2-3s). |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | No | Reserved for future use (e.g. Supabase Storage for question images). Not required for the MVP's core functionality — the app talks to Postgres directly via `DATABASE_URL`. **Never** put the service-role key anywhere participant-facing. |

> **Running locally while also deployed:** if you run the app locally (e.g.
> for a demo) while it's also deployed elsewhere, point both at the **same**
> `DATABASE_URL` (so they share live session data) but give each its own
> `APP_BASE_URL` — `http://localhost:8501` locally, your real deployed URL
> in production — so each generates QR codes/join links pointing at itself,
> not the other one.

---

## 5. Network access: getting phones to connect

A QR code that "doesn't scan" almost always means the URL baked into it was
`localhost` — which only ever means "this same phone", never the host's
laptop. NBK Engage avoids that automatically, but it helps to understand
what's actually happening for the two situations you'll run into:

### Same room, same Wi-Fi (the common case)

No configuration needed. `utils/qr_code.py` auto-detects this computer's LAN
IP (e.g. `192.168.1.23`) and bakes that into the join link/QR code instead
of `localhost`, and the launcher/`streamlit run` command binds to
`0.0.0.0` so the server actually listens on that address. If a phone still
can't connect:

1. **Confirm both devices are on the same Wi-Fi network** (not a "guest"
   network that isolates devices from each other — some venues/offices block
   this by default; ask IT or use a personal hotspot instead).
2. **Windows Firewall**: the first time you run the app, Windows may prompt
   "Allow Python to communicate on public/private networks" — click **Allow**.
   If you missed the prompt, add it manually: Windows Security → Firewall &
   network protection → Allow an app through firewall → add Python (or
   `streamlit.exe` inside your `.venv\Scripts\` folder).
3. **Double-check the IP**: if your laptop has multiple network adapters
   (Wi-Fi + Ethernet + a VPN), the auto-detected IP might pick the wrong one.
   Run `ipconfig` (Windows) and look for the IPv4 address under your actual
   Wi-Fi adapter, then set it explicitly: `APP_BASE_URL=http://<that-ip>:8501`
   in `.env`.

### Participants NOT on the same network (true internet access)

For a venue where attendees are on their own mobile data, or a remote
training session, pick one:

- **Deploy it** (recommended for repeat use) — see [§10 Deployment](#10-deployment).
  You get a permanent public URL; set `APP_BASE_URL` to it.
- **Tunnel it** (fastest for a one-off session, no deployment needed):
  install [ngrok](https://ngrok.com/download), then with the app already
  running locally:
  ```bash
  ngrok http 8501
  ```
  ngrok prints a public `https://....ngrok-free.app` URL. Set
  `APP_BASE_URL=https://....ngrok-free.app` in `.env` (or just share that
  URL manually with `?join=<code>` appended) and restart the app so the QR
  code picks it up. Free ngrok URLs are temporary and change each time you
  restart it.

---

## 6. Using the app

### As the trainer (Host)

1. From the join screen, expand **"Are you the trainer?"** → **Trainer /
   Host Login**, or open `?mode=host`.
2. Log in with `ADMIN_PASSWORD`.
3. If you haven't already, go to **Admin → Question Sets** to build a set
   (add questions to it directly, or bulk-import from Excel — see below), or
   run the seed script for a ready-made one.
4. **Create Session**: give it a title, pick a question set, and choose:
   - **Pacing** — *Host-paced* (one shared question at a time; you control
     when voting closes and when the group moves on) or *Self-paced*
     (everyone works through every question independently, at their own
     speed, with a **Skip** option — no timer, no host click needed between
     questions). Self-paced sessions always reveal everything together at
     the end (there's no single shared question to reveal one at a time).
   - **Reveal mode** (host-paced only) — *Per question* (classic Kahoot-
     style: reveal each question right after it closes) or *All at once*
     (nothing is shown until every question has been answered, then
     everything is revealed together — exam/survey-style).
   - **Anonymous leaderboard** (optional) — hides real names from other
     participants on the leaderboard. Moot in practice today, since
     participants no longer see the leaderboard at all (see below) — this
     flag only affects what would show if that changes later. You (the
     host) and the Excel export always see real names regardless.
   - **Scoring settings** (optional, collapsed by default) — the default is
     **1 point for a correct answer, 0 for incorrect, no time bonus, no
     negative marking**. Turn on the Kahoot-style "bonus points for faster
     answers" (up to +50%, based on server-measured response time) or
     negative marking here if you want them.
5. You'll land in the **control room**: session code + QR code, live
   participant count, and a progress bar that stays visible through every
   screen so you always know how much of the session is left. Click **START
   SESSION** once people have joined.
6. What happens next depends on the pacing/reveal mode you picked:
   - **Host-paced, per-question mode**: full manual control, no timer. The
     question and its **options are shown on your screen too** (read-only,
     correct answer never highlighted while voting is open). **CLOSE
     VOTING** when ready → **Reveal** (label adapts to question type,
     including a real word-cloud image for word-cloud questions) → choose
     **Bar** or **Pie** chart style → **SHOW LEADERBOARD** → **NEXT
     QUESTION**.
   - **Host-paced, all-at-once mode**: hands-off once started. Voting closes
     itself the moment every joined participant has answered, and the
     session moves straight to the next question — no clicks needed from
     you until the very end.
   - **Self-paced**: a live progress panel shows, per participant, how many
     of the total questions they've answered/skipped so far. Closes and
     reveals automatically once everyone's finished every question, or
     click **Close & Reveal Results** to end it early yourself.
7. All three paths converge on the same **Group Results** screen once
   there's nothing left to advance through — an anonymous, group-level
   summary: a donut chart of overall % correct, Participants / Total
   Questions / Group Accuracy / Average Score tiles, and a per-question
   breakdown (sortable by question # or incorrect %, Bar/Pie toggle, word
   clouds rendered for word-cloud questions, each question showing "X of N
   answered correctly (Y%)" plus its explanation). **This screen, and the
   ranked leaderboard, are visible to you only** — participants never see
   it. From here:
   - **🏆 Show Leaderboard** reveals the ranked leaderboard inline (with
     real names — host-only).
   - **🔄 Prepare Excel Export** then **⬇️ Download Results (Excel)** for
     offline records (built on demand when you click Prepare, not
     continuously in the background).
   - **🌐 Reveal to Participants** — participants only ever see their *own*
     personal scorecard (correct/incorrect count and accuracy %, plus their
     own answer-by-answer review); this button controls when that becomes
     visible to them, same as before, it just no longer also reveals group
     charts or the leaderboard to them, since they never see those.
   - **🏁 End Session** wraps up. The same Group Results screen (with the
     same controls) is shown again on **Session Ended**, and later for any
     past session from **Admin → Sessions & Results**.
8. If you refresh the host tab or come back later, log in again and click
   **Resume →** on your in-progress session — nothing is lost, because it's
   all in the database, not the browser tab.

### As a participant

1. Scan the QR code (or open the join URL / enter the 6-digit code manually).
2. Enter a name, tap **Join Session**.
3. A progress bar is visible at the top throughout. Wait for the host to
   start; when a question (or, in self-paced mode, the whole question set)
   goes live it appears automatically (polling, no refresh needed) — there
   is no timer or countdown.
4. Tap an answer (or type one for word-cloud/open-ended questions). Once
   submitted, the button disables and shows "Answer submitted". In
   self-paced mode there's also a **Skip this question** button, and the
   next question appears immediately after answering/skipping — no waiting
   for the host.
5. **You only ever see your own results — never anyone else's, and never
   group-level charts or a leaderboard.** In host-paced *per-question* mode,
   once the host reveals a question you see whether *you* got it right (and
   the correct answer/explanation for MCQs), not how the whole group
   answered. In *all-at-once* mode, nothing is shown per question at all.
6. After the last question, once the host clicks **Reveal to Participants**,
   you see your personal scorecard: how many you got **✅ Correct**, how many
   **❌ Incorrect**, your **Accuracy %**, and **⭐ Your Score**, plus a
   **"Your Answers"** section listing every question with a ✅/❌/⬜ badge
   right on the collapsed row — so you can tell at a glance which ones you
   got wrong without opening each one.
7. If your phone drops connection or you refresh, rejoin with the **same
   name** and you'll reconnect to your existing progress/score rather than
   starting over or being blocked as a "duplicate name".

### Admin console

`?mode=admin` (or the **Admin** button from the host screen): **Question
Sets** is the only workflow — there's no separate "question bank" screen.
Create a set, then add questions to it directly (a nested "add new question"
form right inside the set), add an existing question from elsewhere in the
bank (with search), or bulk-import from Excel straight into that set (with
row-level validation, a downloadable template, and duplicate detection — a
question matching an existing one by text + type is flagged and reused
instead of creating a duplicate row). Every question is worth 1 point by
default; edit an individual question's points afterward if you want to
weight a specific question higher. **Sessions & Results** browses/downloads
results for any past session.

---

## 7. Question types

| Type | Notes |
|---|---|
| **MCQ** | 2–6 options, one correct answer, explanation, points (default 1). Scored server-side. The host can optionally enable a Kahoot-style time bonus (up to +50%, scaled by server-measured response time against the question's configured `timer_seconds`) and/or negative marking per session (§6) — this is the only place `timer_seconds` still matters; there's no visible countdown in either pacing mode. Results shown to the host as a bar or pie chart. |
| **POLL** | 2–8 options (4 built into the form + optional extra options), no correct answer, live percentage bars/pie chart (host-only). |
| **WORD CLOUD** | Free-text, one response per participant. Aggregated with stop-word removal, lower-casing and punctuation stripping (`services/analytics.py`), rendered as an actual word-cloud image sized by frequency, on both the per-question reveal and the Group Results breakdown. |
| **RATING** | 1–5 stars, optional min/max labels, shows an average + distribution (host-only). |
| **OPEN ENDED** | Free text, shown to the host as a simple attributed list. |

Every group-level result view above (bar/pie charts, word clouds, rating
distributions, the open-ended list) is host-only and anonymous by
construction — option-level counts/percentages, never who picked what.
Participants only see their own answer to each question, never the group
breakdown. Real names only ever appear on the host's leaderboard view and in
the Excel export.

Adding a 6th type means: extend the `type` check constraint in
`database/schema.sql`, add a case to `services/scoring.py::score_response`
(if it should be scored), a rendering branch in `components/question_card.py`
and `components/results.py::render_question_results`, and (if it needs bulk
import) a branch in `utils/validation.py::validate_question_dict`. Nothing
else in the state machine or database layer needs to change.

---

## 8. Testing

```bash
python -m pytest -q
```

The suite is split by what it needs:

- **Pure unit tests** (`test_scoring.py`, `test_validation.py`,
  `test_excel_import.py`, `test_excel_export.py`, `test_session_manager.py`,
  `test_qr_code.py`, `test_leaderboard_anonymize.py`,
  `test_participant_reveal_gate.py`) — no database required, always run.
- **`test_analytics.py`** — monkeypatches `services.database`'s read
  functions to verify the aggregation *math* (percentages, stop-word
  filtering, rating averages) without a live DB.
- **`test_integration_db.py`** — end-to-end against a real database (session
  creation, joining, duplicate-name/duplicate-answer rejection, scoring,
  leaderboard ranking, both host-paced reveal-mode paths, self-paced mode
  including skip/progress/auto-close, Excel-import duplicate handling, the
  full state-machine walk to `SESSION_ENDED`). These **automatically skip**
  (not fail) if `DATABASE_URL` isn't set or isn't reachable, so the suite
  still passes in an environment with no DB configured. Point `DATABASE_URL`
  at your Supabase project (with `schema.sql` applied) to run them for real;
  every row they create is cleaned up in fixture teardown.

This project has also been manually tested end-to-end in a browser against a
live Supabase project: creating sessions in both pacing models and both
reveal modes, joining as a participant in a second tab, running through all
five question types with live polling between host and participant screens,
the per-question and all-at-once flows, self-paced answering with skip,
the admin question-set/import workflow, bar and pie chart results, word
clouds, the LAN-IP QR code actually resolving correctly, and Excel export —
plus a live deployment on Render (see §10).

---

## 9. Design notes / known limitations

- **Polling, not WebSockets.** `st.fragment(run_every=...)` re-reads the DB
  every couple of seconds. Host and participant screens are each split into
  a small polling fragment (does the minimum read + a "did anything change"
  check) and a plain rendering function that only re-runs on a real
  transition — this is what keeps the question/answer UI from flickering or
  greying out on every tick. If you outgrow polling entirely, the database
  layer is already the single source of truth, so the natural upgrade path
  is to add Supabase Realtime (Postgres logical replication → websocket)
  purely as a *notification* that triggers an immediate re-read, without
  touching the data model.
- **Auth is a single shared password**, not per-host accounts — appropriate
  for one trainer running their own sessions. The `users` table exists in
  the schema so real per-host accounts can be layered in later without a
  schema change.
- **Reconnect-by-name.** Since participants don't have accounts, a
  refreshed/dropped connection reconnects by matching the same name
  (case-insensitive) within a session, preserving their score. In practice
  this means two different people should avoid entering the exact same name
  in the same session.
- **Streamlit's `pages/` auto-multipage discovery is intentionally
  bypassed** (`st.navigation([...], position="hidden")` in `app.py`) so that
  participants never see host/admin links in a sidebar — the folder is
  still named `pages/` for code organization, but routing is done explicitly
  by `app.py` based on URL query params / in-app buttons. Once a role is set
  in `session_state` it takes priority over the URL on every subsequent
  rerun (a `?mode=host` link that stays in the address bar can't silently
  override switching to Admin, for example).
- **Excel export strips timezones.** Postgres always returns timezone-aware
  timestamps; openpyxl can't write those, so `utils/excel_export.py`
  normalizes them to naive UTC before writing. It's also built **on demand**
  (a "Prepare Excel Export" click), not regenerated on every poll tick —
  earlier versions did the latter and it was a major source of unnecessary
  database load on the host's screen.
- **Self-paced mode has no single shared "current question".** Each
  participant's own responses (answered or skipped, both are rows in
  `responses` — `is_skipped` distinguishes them) determine which question
  they see next, computed client-side from a full question list fetched
  once per session (it's immutable once a session starts) and their own
  response list. The host's live progress panel and the auto-close check
  both come from one aggregate query (`services/database.py::get_self_paced_progress`).
- **Both host-paced reveal modes, and self-paced, converge on one "Group
  Results" screen** (`components/session_report.py` +
  `pages/host.py::_render_group_summary_screen`) once there's no next
  question — every path routes into it rather than each having its own
  final-state UI, so they can't drift out of sync with each other. This
  screen (and the ranked leaderboard) is host-only.
- **"Reveal to Participants" is a flag, not a status transition.**
  `sessions.group_summary_revealed_at` is set independently of
  `sessions.status` (which stays `LEADERBOARD`), so it doesn't touch
  `VALID_TRANSITIONS` at all — see `services/database.py::reveal_group_summary`.
  `pages/participant.py::_final_results_revealed` is the single gate both
  pacing modes check before showing anything on the final screen.
- **Participants see personal results only, by design.** Every group-level
  aggregate (option breakdown bar/pie charts, rating distribution, word
  clouds, the ranked leaderboard) is rendered only from `pages/host.py` and
  `components/session_report.py`; `pages/participant.py` never calls into
  those — it computes a participant's own correct/incorrect/accuracy
  directly from their own rows in `responses`
  (`services/database.py::list_responses_for_participant`).
- **A temporary diagnostic layer exists** (`services/diagnostics.py`) for
  investigating live-polling performance — it prints per-query timing
  (pool-wait vs. SQL-execution time, new-connection detection) and a
  per-poll summary line (`HOST_POLL total=...ms db=...ms queries=N` /
  `PARTICIPANT_POLL ...`) to stdout, visible in your hosting platform's logs.
  It adds negligible overhead and is safe to leave in place; strip the
  `diagnostics.start_poll`/`mark`/`end_poll` calls from `pages/host.py`,
  `pages/participant.py` and `services/session_manager.py` (and delete the
  module) if you want it gone later.

---

## 10. Deployment

This is a plain Streamlit app with no filesystem state — any host that can
run `streamlit run app.py --server.port $PORT --server.address 0.0.0.0` with
the right environment variables works. Since all shared state is in
Supabase, you can even run multiple instances behind a load balancer with no
session-affinity requirement.

**This project is currently deployed on [Render](https://render.com)** (free
tier, Singapore region) — see [`render.yaml`](render.yaml) for the exact
service definition. **See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full
walkthrough**, covering two paths:
- An instant, temporary internet URL via **ngrok** (no deployment, ready in
  minutes — for a session happening today).
- A **permanent deployment on your own custom domain** via GitHub + Render,
  plus the DNS setup and the important warning about using a *subdomain* so
  you don't accidentally point your main website's domain at this app
  instead.

(Streamlit Community Cloud is intentionally not used for the custom-domain
path — it doesn't support custom domains. It's a perfectly good option if
you don't need one, though: free, no card required, connects straight to
GitHub.)

---

## 11. Deliverables checklist

- [x] Complete working source code
- [x] `requirements.txt`
- [x] `.env.example`
- [x] `database/schema.sql`
- [x] `README.md` (this file)
- [x] Sample Excel question bank — `database/sample_question_bank.xlsx`
- [x] Test files — `tests/`
- [x] Local setup instructions — [§4](#4-local-setup)
- [x] Supabase setup instructions — [§3](#3-supabase-setup)
- [x] Network access (LAN + internet) — [§5](#5-network-access-getting-phones-to-connect)
- [x] Deployment instructions, incl. custom domain via GitHub — [`DEPLOYMENT.md`](DEPLOYMENT.md)
