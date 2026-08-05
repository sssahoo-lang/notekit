# NoteKit web

Next.js UI for the NoteKit HTTP API. Streams course generation over SSE, with
upload and style pages for the milestone-4 surfaces.

## Setup

```bash
# from repo root — API
docker compose up -d
uv run uvicorn notekit.api:app --reload --port 8000

# frontend
cd web
cp .env.local.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

| Page | Talks to |
|---|---|
| `/` Course | `POST /api/course` (SSE), `GET /api/namespaces`, `GET /api/courses`, `GET /api/health` |
| `/upload` | `POST /api/upload` |
| `/style` | `GET /api/style/{user}`, `POST /api/style/learn` |

User id is stored in `localStorage` and sent as the API's trust-based `--user`
field. Finished courses are saved under that id and listed in the History
sidebar — reopen them without regenerating. There is no auth yet.
