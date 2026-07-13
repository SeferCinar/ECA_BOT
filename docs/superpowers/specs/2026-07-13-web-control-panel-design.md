# Web Control Panel Design

**Date:** 2026-07-13  
**Project:** ECA_BOT (Discord music bot)  
**Status:** Approved for implementation planning

## Goal

Add a **full web control panel** that mirrors Discord slash commands so the bot owner can manage playback, queue, playlists, and library from a browser. Runs in the **same Python process** as the Discord bot, with **simple token auth** and a **dark music-player UI** (Spotify/Discord feel).

## Non-goals (v1)

- Discord OAuth / multi-user roles
- Playlist editor-permission management (Discord-user based)
- Multi-guild picker UI (API stays guild-aware for later)
- Drag-and-drop queue reordering
- File upload to `music/`
- Separate web microservice or Node/React build pipeline

## Decisions

| Topic | Choice |
|-------|--------|
| Purpose | Full control panel (not read-only dashboard) |
| Auth | Single admin token (`WEB_UI_TOKEN`); session cookie + optional Bearer |
| Visual | Dark music player (Spotify/Discord) |
| Guilds | Single-guild UX now; multi-guild-ready API (`WEB_UI_GUILD_ID` / `?guild_id=`) |
| Hosting | Same process as bot (FastAPI + uvicorn on existing health port) |
| Stack | FastAPI + vanilla HTML/CSS/JS; REST + WebSocket; no frontend build step |

## Architecture

```
┌─────────────────────────────────────────────┐
│              bot.py (single process)        │
│  ┌──────────────┐    ┌───────────────────┐  │
│  │ Discord bot  │◄──►│  MusicPlayer(s)   │  │
│  │ (discord.py) │    │  PlaylistManager  │  │
│  └──────────────┘    │  Downloader       │  │
│          ▲           └─────────┬─────────┘  │
│          │                     │            │
│  ┌───────┴─────────────────────┴─────────┐  │
│  │  web/  FastAPI (uvicorn on bot loop)  │  │
│  │  • REST /api/*                        │  │
│  │  • WS  /ws/state                      │  │
│  │  • static UI                          │  │
│  │  • GET /health (deploy healthchecks)  │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Process model

- Replace the existing `HTTPServer` health handler in `bot.py` with FastAPI.
- Bind FastAPI/uvicorn to the bot’s asyncio event loop (or start web as a concurrent task on the same loop). Do **not** run a second event loop for bot operations.
- Port: `PORT` or `HEALTHCHECK_PORT` (default `8080`). `/health` and `/healthz` are always unauthenticated when the HTTP server is running.
- **When to start HTTP:**
  1. If `WEB_UI_TOKEN` is non-empty → start FastAPI with full UI + API + `/health`.
  2. Else if `ENABLE_HEALTH_SERVER` is truthy → start FastAPI with **health only** (no control API/UI, or static disabled page).
  3. Else → no HTTP server (same as today when health is off).

### Service layer

```
HTTP/WS route → MusicService(guild_id) → MusicPlayer | PlaylistManager | MusicDownloader
```

- Introduce a small **service layer** so Discord commands and web routes do not duplicate business logic long-term. v1 may wrap existing `MusicPlayer` methods with a `WebContext` (guild, pseudo-user label `"Web UI"`) where methods still expect interaction-like messaging.
- Web actions must not require a Discord `Interaction`. Where current APIs only send Discord messages, add path(s) that return structured results for the API (and optionally notify a text channel later—out of scope for v1).
- `music_players` remains keyed by `guild_id`.

### Default guild resolution

1. Explicit `guild_id` query/body when provided  
2. Else `WEB_UI_GUILD_ID` from env  
3. Else if the bot is in exactly one guild, use that  
4. Else 400 with a clear error asking to set `WEB_UI_GUILD_ID`

## UI layout and features (v1)

Single-page app served as static files from FastAPI.

1. **Top bar** — bot online, voice connected, guild name, logout  
2. **Main area** — tabs: Player · Queue · Search/Play · Playlists · Library  
3. **Bottom player bar** — now playing, pause/resume, skip, stop, volume (sticky)

### Feature map

| Area | Actions |
|------|---------|
| Voice | List voice channels; join by `channel_id`; leave |
| Play | Play query/URL (stream default, optional download); YouTube search + pick result |
| Control | Pause, resume, skip, stop, volume 0–100, clear queue, shuffle |
| Queue | List entries (name, source, requester) |
| Now playing | Title, stream vs local, requester |
| Playlists | List, create, delete, add/remove song, play playlist |
| Library | List files under `MUSIC_DIR`; play selected local file |
| Auth | Login page; session cookie; logout |

## Auth and security

- **Required for control UI:** `WEB_UI_TOKEN` (non-empty). Without it, control routes and authenticated static app are not enabled (see process model: health-only mode possible via `ENABLE_HEALTH_SERVER`).
- **Login:** `POST /api/auth/login` with token → signed **HttpOnly** session cookie. Signing secret: `WEB_UI_SESSION_SECRET` if set; otherwise a random secret generated at process start (sessions invalid after restart). Document that multi-instance/replicas need a stable `WEB_UI_SESSION_SECRET`.
- **API:** Cookie session **or** `Authorization: Bearer <WEB_UI_TOKEN>`.
- **WebSocket:** Same cookie or token query/header on connect.
- **CORS:** Default same-origin only (static UI from same host).
- **Login rate limit:** Simple in-memory throttle (e.g. N failures per IP per minute).
- **Docs:** Warn that exposing the port publicly requires a strong token; prefer reverse proxy / VPN for personal use.

## API surface

All `/api/*` except login require auth. `/health` is public.

| Method | Path | Body / notes |
|--------|------|----------------|
| POST | `/api/auth/login` | `{ "token": "..." }` |
| POST | `/api/auth/logout` | Clears session |
| GET | `/api/status` | Online, guild, voice channel, volume, playing/paused flags |
| GET | `/api/now` | Current track or null |
| GET | `/api/queue` | Ordered list |
| POST | `/api/play` | `{ "query": "...", "download": false }` |
| POST | `/api/search` | `{ "query": "..." }` → up to 5 results (`title`, `url`, `duration`, …); server stores last results per session |
| POST | `/api/search/play` | `{ "index": 0..4 }` against last search for that session; reject if no search or index out of range |
| POST | `/api/control/{action}` | `pause` \| `resume` \| `skip` \| `stop` \| `clear` \| `shuffle` |
| POST | `/api/volume` | `{ "vol": 0-100 }` |
| GET | `/api/channels` | Voice channels for default guild |
| POST | `/api/voice/join` | `{ "channel_id": "..." }` |
| POST | `/api/voice/leave` | |
| GET | `/api/playlists` | |
| POST | `/api/playlists` | `{ "name": "..." }` create |
| DELETE | `/api/playlists/{name}` | |
| POST | `/api/playlists/{name}/add` | `{ "song": "..." }` |
| POST | `/api/playlists/{name}/remove` | `{ "song": "..." }` |
| POST | `/api/playlists/{name}/play` | Enqueue/play playlist |
| GET | `/api/library` | Local files |
| POST | `/api/library/play` | `{ "name": "filename.ext" }` (basename under `MUSIC_DIR` only; reject path traversal) |

### WebSocket

- Path: `/ws/state`
- After auth, push JSON snapshots on change and/or on interval (~1–2s): `{ status, now, queue }`.
- UI may fall back to REST polling every 2–3s if WS fails.

### Error format

```json
{ "error": "Human-readable message", "code": "VOICE_NOT_CONNECTED" }
```

Examples: `401` unauthorized, `409` voice not connected / invalid state, `400` bad input, `404` playlist/file not found, `502` downstream yt-dlp failure.

## Visual design

- Background ~`#0d0d12`, cards ~`#1a1a24`, text light gray/white  
- Accent: Discord blurple `#5865F2` and/or green play control  
- Sticky bottom player bar; clean sans-serif  
- Responsive: single column on narrow screens  

## File layout

```
web/
  __init__.py
  app.py              # FastAPI factory, mount static, include routers
  auth.py             # token check, session cookie, rate limit
  service.py          # MusicService, guild resolution, WebContext
  routes/
    api.py
    ws.py
  static/
    index.html
    css/app.css
    js/app.js
```

Touches existing:

- `bot.py` — start FastAPI; remove `BaseHTTPRequestHandler` health server  
- `config.py` — `WEB_UI_TOKEN`, `WEB_UI_GUILD_ID`, `WEB_UI_SESSION_SECRET`, port flags  
- `requirements.txt` — `fastapi`, `uvicorn[standard]`  
- `.env.example`, `README.md` — document web UI  
- `docker-compose.yml` / `Dockerfile` — only if port/env docs need updates (same port preferred)

## Integration constraints

- **Thread/async safety:** Call discord.py and player APIs only on the bot event loop (`asyncio.run_coroutine_threadsafe` only if web ever leaves that loop—prefer staying on one loop).
- **Long operations:** Search/download/stream resolve must not block the event loop; use existing async patterns / executors as in `downloader.py`.
- **Search selection:** `POST /api/search` returns result payloads and stores them server-side per session; `POST /api/search/play` uses `{ "index" }` only. No Discord button views.

## Testing (v1)

- Unit: auth accept/reject; guild resolution cases  
- API smoke with mocked service: login → status  
- Manual checklist: login, join channel, play URL, search+play, skip/pause/volume, playlist play, library play, logout, health unauthenticated  

## Success criteria

1. With `WEB_UI_TOKEN` set, opening `http://host:PORT/` shows login then the control panel.  
2. Owner can join voice, play, control queue, and manage playlists without Discord.  
3. `/health` still returns OK for deploy probes without auth.  
4. Unauthorized API calls return 401.  
5. Docker single-container deploy continues to work on one port.

## Implementation order (for planning)

1. Config + FastAPI shell + `/health` + static placeholder + bot lifecycle wire-up  
2. Auth (login/logout/session/Bearer)  
3. MusicService + status/now/queue read APIs + WebSocket/polling  
4. Control + voice + play/search  
5. Playlists + library  
6. Full dark UI polish  
7. Docs, env example, manual verification  
