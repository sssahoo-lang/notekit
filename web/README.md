# NoteKit web

Next.js UI for the NoteKit HTTP API. Streams course generation over SSE, keeps
every goal in History (including incomplete / still-generating courses), and
lets generation finish in the background after you leave the page.

## Setup

```bash
# from repo root: API (--reload-dir src avoids .venv reloads mid-generation)
docker compose up -d
uv run uvicorn notekit.api:app --reload --reload-dir src --port 8000

# frontend
cd web
cp .env.local.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

| Page | Talks to |
|---|---|
| `/` Study | `POST /api/course` (SSE), `GET /api/courses`, progress / cancel / resume |
| `/upload` Materials | `POST /api/upload` |
| `/style` Style | `GET /api/style/{user}`, `POST /api/style/learn` |

User id is stored in `localStorage` and sent as the API's trust-based `user`
field. There is no auth yet.
