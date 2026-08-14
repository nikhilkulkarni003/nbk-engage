# Deploying NBK Engage to the internet

Two different needs, two different answers:

- **"I need this working on the internet today/soon"** → [Option A: ngrok](#option-a-instant-internet-access-today-ngrok) — no deployment, ready in 2 minutes, temporary.
- **"I want a permanent link on my own domain"** → [Option B: real deployment](#option-b-permanent-deployment-with-your-custom-domain) — takes ~30-60 minutes once, gives you a stable URL like `https://engage.yourhappinesspartner.in` that works from anywhere, forever.

Both get you the same result participants see: a normal web page they open in their own phone's browser over their own data/Wi-Fi — nothing to install on their end either way.

---

## Option A: Instant internet access today (ngrok)

Use this when you have a session coming up soon and don't want to deal with deployment yet.

1. Download [ngrok](https://ngrok.com/download) and follow its (free) sign-up + `ngrok config add-authtoken ...` setup step.
2. Start NBK Engage normally on your laptop (double-click `Start NBK Engage.bat`).
3. In a separate terminal:
   ```bash
   ngrok http 8501
   ```
4. ngrok prints a public URL like `https://a1b2-c3d4.ngrok-free.app`. That's your session's internet address for today.
5. In `.env`, set `APP_BASE_URL=https://a1b2-c3d4.ngrok-free.app` and restart NBK Engage so the QR code/join link picks it up.

**Limits**: the free ngrok URL changes every time you restart it, and your laptop has to stay on and connected for the whole session (it's still your machine doing the work — ngrok just makes it reachable). Fine for a one-off; not something to rely on every week.

---

## Option B: Permanent deployment with your custom domain

### Overview

```
GitHub (your code)  ──►  Render.com (runs the app)  ──►  Supabase (your data, already set up)
        ▲
        │  DNS: engage.yourhappinesspartner.in → Render
   your domain registrar
```

We'll use **[Render.com](https://render.com)**: it supports custom domains on every plan (including free), connects directly to a GitHub repo for auto-deploy on every push, and runs Python/Streamlit apps natively — no Docker knowledge needed. (Streamlit Community Cloud, the other obvious option, does **not** support custom domains, which is why it's not used here.)

> ⚠️ **Before you touch DNS**: `www.yourhappinesspartner.in` is presumably your main business website. Pointing that exact domain at this quiz app would **replace your website**. Use a **subdomain** instead — e.g. `engage.yourhappinesspartner.in` or `quiz.yourhappinesspartner.in` — which is a separate DNS record that leaves `www.yourhappinesspartner.in` completely untouched. Everything below assumes a subdomain; substitute whichever one you pick.

### Step 1 — Finish preparing your local Git repo

I've already run `git init` and staged every file in this project (with `.env` correctly excluded — only `.env.example` is tracked). I intentionally did **not** run `git config` or create the commit myself, since that sets your authorship identity and should be yours, not mine. Finish it with:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
git commit -m "Initial commit: NBK Engage"
```

### Step 2 — Push to GitHub

1. On [github.com](https://github.com), create a **new empty repository** (no README/license — this project already has one). Public or private both work with Render.
2. Back in your terminal:
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git branch -M main
   git push -u origin main
   ```

### Step 3 — Deploy on Render

1. Sign up at [render.com](https://render.com) (GitHub sign-in is easiest — it also handles the repo connection).
2. **New +** → **Blueprint** → pick your `nbk-engage` repo. Render reads [`render.yaml`](render.yaml) (already included in this project) and pre-fills the service — Python web service, correct build/start commands.
   - No `render.yaml` support on your plan, or prefer manual? **New +** → **Web Service** instead, then set:
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless=true`
3. When prompted for environment variables (these are the ones marked `sync: false` in `render.yaml`, meaning Render deliberately doesn't store them in the repo):
   - `DATABASE_URL` — your Supabase connection string (same one in your local `.env`)
   - `ADMIN_PASSWORD` — your trainer login password
   - `APP_BASE_URL` — leave this until Step 4, then come back and set it to `https://engage.yourhappinesspartner.in`
4. Pick a plan. `render.yaml` in this repo defaults to **Free** (what this
   project actually runs on). Free-tier Render services spin down after 15
   minutes idle and take 30-60 seconds to wake up on the next request — if a
   participant hits the app right as it's waking up, that first request is
   slow. In practice this is manageable for a scheduled training session
   (open the app yourself a minute or two before people join, so it's
   already awake), but if you're running unscheduled/drop-in sessions where
   that wake-up delay would be disruptive, upgrade to **Starter** (~$7/month,
   stays on) instead — edit `plan:` in `render.yaml` or change it in Render's
   dashboard under Settings → Instance Type.
5. Click **Deploy**. First build takes a few minutes; watch the logs for `You can now view your Streamlit app`.
6. Once deployed, Render gives you a `https://nbk-engage-xxxx.onrender.com` URL — confirm the app loads there before moving to DNS.

### Step 4 — Point your subdomain at it

1. In Render, open your service → **Settings** → **Custom Domains** → **Add Custom Domain** → enter `engage.yourhappinesspartner.in`. Render shows you a target (either a `CNAME` value like `nbk-engage-xxxx.onrender.com`, or an IP for an `A` record — Render tells you which).
2. Go to wherever `yourhappinesspartner.in`'s DNS is managed (your domain registrar, or Cloudflare/similar if you use it) → **DNS records** → **Add record**:
   - Type: `CNAME`
   - Name/Host: `engage` (just the subdomain part, not the full domain)
   - Value/Target: whatever Render showed you
   - Leave every existing record for `@`/`www` exactly as it is.
3. DNS changes typically take a few minutes, sometimes up to an hour. Render will show the domain as "Verified" once it detects it.
4. Back in Render's environment variables, set `APP_BASE_URL=https://engage.yourhappinesspartner.in` and let it redeploy — this is what makes the QR code/join links use your real domain instead of the `.onrender.com` one.

### Step 5 — Verify

- Open `https://engage.yourhappinesspartner.in` — you should see the participant join screen.
- `https://engage.yourhappinesspartner.in/?mode=host` — trainer login.
- Create a real session, scan the QR code with your phone **on mobile data (Wi-Fi off)** to confirm it truly works off-network, not just on your office Wi-Fi.

### Ongoing: updates

Every `git push` to `main` auto-redeploys on Render. Your local development workflow doesn't change — keep using `Start NBK Engage.bat` for local testing, and push when you want changes live.

### Alternatives to Render

If you'd rather not use Render: **Railway.app** and **Fly.io** both also support custom domains + GitHub deploys, with similar setup shapes (env vars in a dashboard, connect repo, add domain). The steps above translate directly; the main difference is Railway's free tier is now trial-credits-based rather than indefinite, and Fly.io leans more toward a CLI (`flyctl`) than a web dashboard.

---

## The trainer's desktop shortcut, pointed at your deployed URL

Once deployed, you don't need to run anything locally to host a session — just open your deployed URL. To keep the "feels like an app" experience from `Start NBK Engage.bat`, create a Windows shortcut that opens it the same chromeless way:

1. Right-click your Desktop → **New** → **Shortcut**.
2. Target:
   ```
   "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=https://engage.yourhappinesspartner.in/?mode=host --window-size=1360,900
   ```
3. Name it "NBK Engage" and optionally give it a custom icon (Shortcut Properties → Change Icon).

Double-clicking it opens your live trainer console in its own app-style window, no browser tabs — from anywhere with internet, not just your home/office network.
