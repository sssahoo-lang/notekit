# Deploying NoteKit

Two pieces go up separately: the API (a container, on Railway) and the web UI
(a Next.js app, on Vercel). The database is managed Postgres with pgvector.

Everything here is something you run with your own accounts — the config and the
container are built and verified, but nobody else can sign in as you.

---

## What the container actually needs

Measured on the built image, not estimated:

| | |
|---|---|
| Image size | 609 MB |
| Peak RSS with both models loaded and warm | 590 MB |
| Realistic ceiling with uvicorn and a request in flight | ~800 MB |

So **1 GB of RAM is the floor and 2 GB is comfortable**. A 512 MB instance will
be OOM-killed the first time a request touches retrieval. This is the price of
running the embedding and reranking models locally, which is also the reason the
whole project needs one API key instead of two.

The image runs a single worker on purpose. A second worker would load its own
copy of both models and double the memory for no throughput gain — the bottleneck
is the Anthropic API, not local CPU.

Cold start is a few seconds: the model weights are baked into the image at build
time, so nothing is downloaded on boot. That is deliberate — fetching 421 MB
from HuggingFace on first request would blow through any platform health check.

---

## 1. Database

Create a managed Postgres instance and confirm pgvector is available:

```bash
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If that fails, the provider doesn't ship pgvector — Neon and Supabase both do.
Then load the schema:

```bash
psql "$DATABASE_URL" -f scripts/schema.sql
```

Keep the connection string. Managed providers usually require TLS, so use the
`?sslmode=require` form they give you rather than trimming it off.

## 2. API on Railway

Railway reads [`railway.json`](railway.json) and builds the
[`Dockerfile`](Dockerfile) — no build configuration to fill in. Point a new
service at this repo, then set:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your key |
| `DATABASE_URL` | from step 1 |
| `SITE_PASSWORD` | any passphrase — see below |
| `ALLOWED_ORIGINS` | leave empty for now; step 4 fills it in |

Raise the memory limit to at least 1 GB before the first deploy.

`PORT` is injected by Railway and the container already reads it. The health
check at `/api/health` stays reachable without the password, so the platform can
verify the service is up.

Sanity check once it's live:

```bash
curl https://YOUR-API.up.railway.app/api/health
```

## 3. Web UI on Vercel

Import the repo and set **Root Directory** to `web` — without that, Vercel builds
from the repository root and finds no Next.js app. One environment variable:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://YOUR-API.up.railway.app` |

It is `NEXT_PUBLIC_`, so it is compiled into the browser bundle. Changing it
means redeploying, and it is readable by anyone who loads the page — which is
fine, it is just the API's address, and the API is behind the password.

## 4. Close the loop

Set `ALLOWED_ORIGINS` on the Railway service to the Vercel URL and redeploy:

```
ALLOWED_ORIGINS=https://YOUR-APP.vercel.app
```

Until this is set the browser blocks every call and the UI shows its offline
state. Comma-separate if you want preview deployments to work too.

---

## About the password

`SITE_PASSWORD` puts one shared password in front of the API. The server hands
back a token derived from it; the browser stores that and sends it on every
request. Unset the variable and the gate disappears, which is why local
development is unaffected.

**It is a lock on the front door, not authentication.** Everyone who gets in
shares one identity. The per-user namespaces behind it separate one browser from
another, not one person from another — someone inside who knows another
browser's profile id can read its material. Real auth means sessions and a user
id derived from them, and is deliberately not what this is.

What it does buy is the difference between a demo you can show someone and an
upload form, pointed at a paid API key, open to the whole internet.

Rotating the password invalidates every issued token: the next page load finds
the stored one rejected, discards it, and prompts again.

---

## Running costs

| | |
|---|---|
| Railway, 1–2 GB instance | roughly $5–10/month |
| Managed Postgres | free tier is enough for a demo |
| Vercel | free tier |
| Anthropic API | per course — see the cost breakdown in the README |

The API instance is the only fixed cost, and it exists because the models run
locally.
