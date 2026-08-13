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
  this browser currently looking at"). Every piece of shared state — session
  status, the active question, who has joined, every answer, every score —
  lives in Postgres. That's what lets a host's laptop and ten participants'
  phones all agree on what's happening right now.
- **Realtime is done via polling**, using Streamlit's `st.fragment(run_every=...)`
  (every `POLL_INTERVAL_SECONDS`, default 2s) to re-read the database and
  redraw just the live portion of the screen. This was a deliberate choice
  over WebSockets/Supabase Realtime for the MVP — see [§9](#9-design-notes--known-limitations).
- **Scoring is always computed server-side** (`services/scoring.py` +
  `services/session_manager.py`), from the question's stored correct answer
  and a server-measured response time. The client only ever sends "which
  option did the participant pick" — never a score.
- **The session lifecycle is an explicit state machine**
  (`services/session_manager.py`): `WAITING → QUESTION_ACTIVE → VOTING_CLOSED
  → RESULTS_REVEALED → LEADERBOARD → (loops to QUESTION_ACTIVE, or) →
  SESSION_ENDED`. Every transition re-reads the current status from the
  database and validates it before writing, so a stale tab or a double-click
  can't corrupt the flow.

### Project structure

```
app.py                     Entry point + routing (host/participant/admin) + global CSS
pages/
  host.py                  Trainer console: create/run a session, control room
  participant.py           Join → wait → answer → results → leaderboard
  admin.py                 Question bank, question sets, Excel import, past sessions
components/
  question_card.py         Question prompt, answer widgets, read-only host options preview
  timer.py                 Server-time-based countdown
  progress.py              "Question X of N" progress bar shown to host + participants
  leaderboard.py           Ranked leaderboard with medals, rank-change arrows, anonymize option
  results.py               Live result bars/pie charts, rating summary, open-ended list
  review.py                Personal per-question review with pass/fail badge (participant's own answers)
  session_report.py        The anonymous "Group Results" screen (donut, tiles, per-question breakdown)
  wordcloud.py             Multi-color word cloud image rendering
services/
  database.py              The ONLY module that talks SQL (SQLAlchemy + psycopg2)
  session_manager.py       Session state machine + server-side answer submission
  quiz_engine.py           Question sequencing / snapshotting a set into a session
  scoring.py                Pure scoring math (no DB) — 1 point per correct answer by default
  analytics.py              Poll/MCQ result %, word-cloud frequencies, leaderboard, exports
utils/
  excel_import.py          Bulk question upload + validation + template generator
  excel_export.py          Multi-sheet results workbook (participants/scores/results/raw)
  qr_code.py                Join-link QR code generation (auto-detects LAN IP)
  network.py                 LAN IP detection backing the QR code
  validation.py             Shared input validation (names, codes, question rows)
  auth.py                   Simple shared-password gate for host/admin
database/
  schema.sql                 Full Postgres schema (tables, views, constraints, triggers)
  migrations/                 Incremental ALTERs for installs that ran an older schema.sql
  seed_questions.py          Seeds 14 sample finance questions + a ready-to-run set
  sample_question_bank.xlsx  The same 14 questions in the Excel import format
tests/                        pytest suite (unit + DB integration)
"Start NBK Engage.bat"        Windows launcher: sets up + starts the server + opens the trainer app window
_open_app_window.bat           Helper invoked by the launcher (waits for the server, opens Edge app mode)
DEPLOYMENT.md                  Full deployment guide: instant internet (ngrok) + permanent custom domain
render.yaml                    Render.com blueprint used by DEPLOYMENT.md's deploy path
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
   string → URI**. Prefer the **Session pooler** variant if offered — it
   plays nicer with Streamlit's connection pooling than a direct connection.
   It looks like:

   ```
   postgresql://postgres.xxxxxxxx:YOUR_PASSWORD@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```

   If your password contains special characters (`@`, `#`, `%`, ...), URL-encode
   them (`@` → `%40`, etc.).

> **Already ran an earlier version of `schema.sql`?** Also run everything in
> `database/migrations/` (in order) in the SQL Editor:
> [`001_reveal_mode_and_scoring_defaults.sql`](database/migrations/001_reveal_mode_and_scoring_defaults.sql)
> adds the reveal-mode/anonymous-leaderboard columns and switches the
> default scoring from 1000-points-plus-bonus to flat 1-point-per-correct-
> answer; [`002_group_summary_reveal.sql`](database/migrations/002_group_summary_reveal.sql)
> adds the column backing the "Reveal to Participants" action on the group
> results screen. Both are safe to re-run; brand-new installs get everything
> from `schema.sql` directly and don't need either.

---

## 4. Local setup

**Windows shortcut:** once your `.env` is configured (step 3 below), you can
skip everything else and just double-click **`Start NBK Engage.bat`** in the
project folder — it creates the virtual environment and installs
dependencies on first run, then starts the server and opens the Trainer
Console in its own chromeless app window (via Edge `--app` mode, using the
helper script `_open_app_window.bat`) rather than a regular browser tab, so
it feels like a native app on your desktop. Keep the console window open
while running a session; closing it stops the app. Participants always join
from their own separate, ordinary phone browser — this app-window behavior
only affects your own trainer screen.

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
| `DATABASE_URL` | **Yes** | Supabase Postgres connection string. The app refuses to do anything DB-backed without it, and shows a friendly error instead of crashing. |
| `ADMIN_PASSWORD` | **Yes** | Shared password gating the Host and Admin areas. Participants never see or need this. **Change it from the default before sharing the app with anyone.** |
| `APP_NAME` | No | Cosmetic; shown in the browser tab. |
| `APP_BASE_URL` | No | Join URL / QR code base. Leave at the localhost placeholder for classroom use — the app auto-detects this machine's LAN IP instead. Only set this if you deploy to a real public URL. See [§5](#5-network-access-getting-phones-to-connect). |
| `APP_PORT` | No | Port used when building the LAN join URL (default `8501`, matches Streamlit's default port). |
| `POLL_INTERVAL_SECONDS` | No | How often host/participant screens re-check the database (default 2s). |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | No | Reserved for future use (e.g. Supabase Storage for question images). Not required for the MVP's core functionality — the app talks to Postgres directly via `DATABASE_URL`. **Never** put the service-role key anywhere participant-facing. |

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
3. If you haven't already, go to **Admin → Question Bank** to add questions
   and build a **Question Set**, or run the seed script for a ready-made one.
4. **Create Session**: give it a title, pick a question set, and choose:
   - **Reveal mode** — *Per question* (classic Kahoot-style: reveal each
     question right after it closes) or *All at once* (nothing is shown
     until every question has been answered, then everything is revealed
     together — exam/survey-style). Pick whichever fits how you want to run
     the session; both are fully supported end-to-end.
   - **Anonymous leaderboard** (optional) — hides real names from other
     participants on the leaderboard. You (the host) always see real names,
     and so does the Excel export; only what *other participants* see is
     anonymized (as "Participant 123"-style labels).
   - **Scoring settings** (optional, collapsed by default) — the default is
     **1 point for a correct answer, 0 for incorrect, no time bonus, no
     negative marking**. Turn on the Kahoot-style "bonus points for faster
     answers" (up to +50%) or negative marking here if you want them.
5. You'll land in the **control room**: session code + QR code, live
   participant count, and a progress bar ("Question X of N") that stays
   visible through every screen so you always know how much of the session
   is left. The question and its **options are shown on your screen too**
   (read-only, correct answer never highlighted while voting is open) so
   you and participants are looking at the same thing on the projector.
   Click **START SESSION** once people have joined.
6. What happens per question depends on the reveal mode you picked:
   - **Per-question mode**: you're in full manual control. **CLOSE VOTING**
     when ready → **Reveal** (label adapts to question type) → choose
     **Bar** or **Pie** chart style → **SHOW LEADERBOARD** → **NEXT
     QUESTION**.
   - **All-at-once mode**: fully hands-off. Voting closes itself the
     moment the timer runs out *or* every joined participant has answered
     (whichever comes first), and the session moves straight to the next
     question — no clicks needed from you at all until the very end.
7. Both modes converge on the same **Group Results** screen once the last
   question is done (automatically for all-at-once, or via **SHOW
   LEADERBOARD** on the last question for per-question mode) — an
   anonymous, group-level summary: a donut chart of overall % correct,
   Participants / Total Questions / Group Accuracy / Average Score tiles,
   and a per-question breakdown (sortable by question # or incorrect %,
   Bar/Pie toggle, each question showing "X of N answered correctly (Y%)"
   plus its explanation). From here:
   - **🏆 Show Leaderboard** reveals the ranked leaderboard inline (with
     real names — this is host-only, never anonymized for you).
   - **⬇️ Download Results (Excel)** for offline records.
   - **🌐 Reveal to Participants** pushes this same anonymous group summary
     to every participant's phone — nothing on this screen is visible to
     participants until you click this.
   - **🏁 End Session** wraps up. The same Group Results screen (with the
     same four controls) is shown again on **Session Ended**, and later
     for any past session from **Admin → Sessions & Results**.
8. If you refresh the host tab or come back later, log in again and click
   **Resume →** on your in-progress session — nothing is lost, because it's
   all in the database, not the browser tab.

### As a participant

1. Scan the QR code (or open the join URL / enter the 6-digit code manually).
2. Enter a name, tap **Join Session**.
3. A progress bar ("Question X of N") is visible at the top throughout, so
   you always know how many questions are left. Wait for the host to start;
   when a question goes live it appears automatically (polling, no refresh
   needed) with a countdown timer (a consistent 30s by default).
4. Tap an answer (or type one for word-cloud/open-ended questions). Once
   submitted, the button disables and shows "Answer submitted".
   - In *per-question* reveal mode, the correct answer/results appear as
     soon as the host reveals them.
   - In *all-at-once* mode, nothing is shown per question — the next
     question just appears on its own once voting closes.
5. After the last question, once the host clicks **Reveal to Participants**,
   you see the same anonymous **Group Results** the host sees, plus a
   **"Your Answers"** section listing every question with a ✅/❌/⬜ badge
   right on the collapsed row — so you can tell at a glance which ones you
   got wrong without opening each one, and only expand those for detail.
5. A "Your rank: #N · X pts" line always shows your own real result. If the
   host enabled anonymous mode for this session, the ranked list below it
   shows every participant (including you) as an anonymous label like
   "Participant 123" instead of real names — the pseudonym is stable for
   the whole session, so you'll recognize your own row across screens even
   without your name on it.
6. If your phone drops connection or you refresh, rejoin with the **same
   name** and you'll reconnect to your existing score rather than starting
   over or being blocked as a "duplicate name".

### Admin console

`?mode=admin` (or the **Admin** button from the host screen): manage the
question bank (create/edit/duplicate/delete/search/filter), build and edit
question sets, bulk-import questions from Excel (with row-level validation
and a downloadable template), and browse/download results for any past
session.

---

## 7. Question types

| Type | Notes |
|---|---|
| **MCQ** | 2–6 options, one correct answer, explanation, points, optional timer. Scored server-side. **Default: 1 point for a correct answer, 0 for incorrect** — the host can optionally enable a Kahoot-style time bonus (up to +50% scaled by remaining time) and/or negative marking per session (§6). Results can be shown as a bar or pie chart. |
| **POLL** | 2–8 options (4 built into the form + optional extra options), no correct answer, live percentage bars/pie chart. |
| **WORD CLOUD** | Free-text, one response per participant. Aggregated with stop-word removal, lower-casing and punctuation stripping (`services/analytics.py`), rendered as an actual word-cloud image sized by frequency. |
| **RATING** | 1–5 stars, optional min/max labels, shows an average + distribution. |
| **OPEN ENDED** | Free text, shown to the host as a simple attributed list. |

Every result view above is anonymous by construction — it shows option-level
counts/percentages, never who picked what. Real names only ever appear on
the leaderboard (optionally anonymized too, see §6) and in the host's Excel
export.

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
  `test_qr_code.py`, `test_leaderboard_anonymize.py`) — no database required,
  always run.
- **`test_analytics.py`** — monkeypatches `services.database`'s read
  functions to verify the aggregation *math* (percentages, stop-word
  filtering, rating averages) without a live DB.
- **`test_integration_db.py`** — end-to-end against a real database (session
  creation, joining, duplicate-name/duplicate-answer rejection, scoring,
  leaderboard ranking, both reveal-mode paths, the full state-machine walk to
  `SESSION_ENDED`). These **automatically skip** (not fail) if `DATABASE_URL`
  isn't set or isn't reachable, so the suite still passes in an environment
  with no DB configured. Point `DATABASE_URL` at your Supabase project (with
  `schema.sql` applied) to run them for real; every row they create is
  cleaned up in fixture teardown.

This project has also been manually tested end-to-end in a browser against a
live Supabase project: creating sessions in both reveal modes, joining as a
participant in a second tab, running through all five question types with
live polling between host and participant screens, timer auto-expiry, the
per-question and all-at-once leaderboards (anonymized and real-name), bar
and pie chart results, the LAN-IP QR code actually resolving correctly, and
Excel export.

---

## 9. Design notes / known limitations

- **Polling, not WebSockets.** `st.fragment(run_every=...)` re-reads the DB
  every couple of seconds. This is simple, has no extra moving parts, and is
  fast enough for a classroom (host and participant screens visibly update
  within ~2s in testing). If you outgrow it, the database layer is already
  the single source of truth, so the natural upgrade path is to add
  Supabase Realtime (Postgres logical replication → websocket) purely as a
  *notification* that triggers an immediate re-read, without touching the
  data model.
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
  by `app.py` based on URL query params / in-app buttons.
- **Excel export strips timezones.** Postgres always returns timezone-aware
  timestamps; openpyxl can't write those, so `utils/excel_export.py`
  normalizes them to naive UTC before writing.
- **DEFERRED reveal mode reuses the same state machine**, not a parallel
  one — it just takes an extra edge (`VOTING_CLOSED → QUESTION_ACTIVE`
  directly, skipping `RESULTS_REVEALED`/`LEADERBOARD` per question) that
  `INSTANT` mode never uses, plus one new terminal action
  (`reveal_all_and_show_leaderboard`) that marks every question revealed at
  once. See the docstring at the top of `services/session_manager.py`.
- **DEFERRED auto-advance is a poll-loop side effect, not a background
  job.** `services/session_manager.py::auto_advance_deferred` is called on
  every host-side fragment tick (`pages/host.py::_render_control_room`); it
  closes voting once the timer expires or every joined participant has
  answered, then immediately chains into `next_question`/
  `reveal_all_and_show_leaderboard` within the same call. There's no
  separate scheduler — if the host's browser tab isn't open, nothing
  advances, same as every other state transition in this app.
- **Both reveal modes converge on one "Group Results" screen**
  (`components/session_report.py` + `pages/host.py::_render_group_summary_screen`)
  once there's no next question — `_render_leaderboard` and
  `_render_session_ended` both route into it rather than each having their
  own final-state UI, so the two modes can't drift out of sync with each
  other.
- **"Reveal to Participants" is a flag, not a status transition.**
  `sessions.group_summary_revealed_at` is set independently of
  `sessions.status` (which stays `LEADERBOARD`), so it doesn't touch
  `VALID_TRANSITIONS` at all — see `services/database.py::reveal_group_summary`.
- **Anonymization happens at render time, not query time.** The database
  and the `session_leaderboard` view always return real names; only the
  participant-facing call to `components/leaderboard.py::render_leaderboard`
  passes `anonymize=True`. The host's view and the Excel export always call
  it with `anonymize=False`, so the trainer never loses visibility into who
  is who even when participants can't see each other's names. The Group
  Results screen is anonymous by construction for a different reason: it's
  built entirely from option-level counts/percentages (`services/analytics.py`),
  which never carry a participant identity in the first place.

---

## 10. Deployment

This is a plain Streamlit app with no filesystem state — any host that can
run `streamlit run app.py --server.port $PORT --server.address 0.0.0.0` with
the right environment variables works. Since all shared state is in
Supabase, you can even run multiple instances behind a load balancer with no
session-affinity requirement.

**See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full walkthrough**, covering
two paths:
- An instant, temporary internet URL via **ngrok** (no deployment, ready in
  minutes — for a session happening today).
- A **permanent deployment on your own custom domain** via GitHub + Render
  (with a `render.yaml` blueprint already included in this repo), plus the
  DNS setup and the important warning about using a *subdomain* so you don't
  accidentally point your main website's domain at this app instead.

(Streamlit Community Cloud is intentionally not used here — it doesn't
support custom domains, which the deployment guide treats as a requirement.)

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
