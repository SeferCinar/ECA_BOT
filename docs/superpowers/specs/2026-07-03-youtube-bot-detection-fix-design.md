# YouTube Bot-Detection Fix — Design

## Problem

When deployed to a remote server, yt-dlp frequently fails to fetch YouTube audio with `Sign in to confirm you're not a bot` (and related `PO Token` warnings). This is documented in `TROUBLESHOOTING.md`. The current mitigation (a manually-exported browser `cookies.txt`, see `Config.get_cookie_file()` / `MusicDownloader._find_cookie_file()`) is fragile: cookies expire in roughly 1–4 weeks and must be re-exported from a real browser and re-uploaded by hand.

This is a private, single-server bot (not public), so logging into a real Google/YouTube account server-side is an acceptable trade-off if it reduces maintenance.

## Goals

- Eliminate (or drastically reduce) the "sign in to confirm you're not a bot" failures on the deployed server.
- Reduce recurring manual maintenance (no more periodic browser cookie re-export).
- Keep the existing cookie-file mechanism working as a fallback — don't remove it.
- No dependency on any specific deployment platform (Coolify, plain VPS, etc.) — everything must work via plain `docker` / `docker compose` commands.

## Non-goals

- No automated test suite is being added (none exists in this repo today; verification is manual).
- No UI/command changes — this is purely an internal reliability fix to `downloader.py` and deployment config.

## Chosen approach: PO Token Provider + OAuth2 account login (combined)

Two independent layers are added on top of the existing cookie-file support:

### A) PO Token Provider (`bgutil-ytdlp-pot-provider`)

yt-dlp's currently-recommended fix for PO-Token-gated bot checks. A small companion HTTP service generates a valid Proof-of-Origin token; yt-dlp (via a plugin) queries it instead of requiring a signed-in session. No Google account or ban risk involved.

- **New Docker Compose service** `pot-provider` using image `brainicism/bgutil-ytdlp-pot-provider`, attached only to the existing `bot-network` (no external port published).
- **New Python dependency** `bgutil-ytdlp-pot-provider` in `requirements.txt` — this is the yt-dlp-side plugin that talks to the service above.
- The bot service (`discord-bot`) depends on `pot-provider` (`depends_on`).
- yt-dlp is invoked (both via the Python API and the CLI subprocess path) with an extra `extractor_args` entry: `youtubepot-bgutilhttp:base_url=<POT_PROVIDER_BASE_URL>`.

### B) OAuth2 account login (`yt-dlp-youtube-oauth2`)

A one-time device-code login into a real Google account, avoiding repeated manual cookie exports. The refresh token is cached by yt-dlp and renews itself automatically.

- **New Python dependency** `yt-dlp-youtube-oauth2` in `requirements.txt`.
- When enabled, yt-dlp is invoked with `username=oauth2, password=''` (Python API) / `--username oauth2 --password ''` (CLI) **instead of** the cookie file — the two auth mechanisms are not combined, to avoid conflicting behavior.
- yt-dlp's cache directory (default `/root/.cache/yt-dlp` inside the container, since the container runs as root) must be a persistent Docker volume, otherwise the OAuth2 refresh token is lost on every rebuild/redeploy and the device-code login has to be redone.
- **One-time setup step (platform-agnostic):** after first deploy, run:
  ```bash
  docker compose exec discord-bot yt-dlp --username oauth2 --password '' -f bestaudio -g "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ```
  This prints a `https://www.google.com/device` URL and a code; authorize from any browser/device. The token is then cached in the mounted volume and reused/refreshed automatically on subsequent runs — this step is not repeated after redeploys as long as the volume persists.

### Fallback / toggles

- `YOUTUBE_OAUTH2_ENABLED` (env var, default `true`): when `false`, auth falls back to the existing cookie-file mechanism unchanged. Nothing about the current cookie code is removed.
- `POT_PROVIDER_BASE_URL` (env var, default `http://pot-provider:4416`, matching the compose service name): if the provider is unreachable, yt-dlp logs a warning and continues without a PO token (same behavior as today) — it does not crash the bot.

## Components changed

- **`requirements.txt`** — add `bgutil-ytdlp-pot-provider` and `yt-dlp-youtube-oauth2`.
- **`docker-compose.yml`** — add `pot-provider` service; add `depends_on` on the bot service; add a named volume for `/root/.cache/yt-dlp` on the bot service.
- **`config.py`** — add `POT_PROVIDER_BASE_URL` and `YOUTUBE_OAUTH2_ENABLED` (env-driven, with the defaults above).
- **`downloader.py`** — introduce two small private helpers on `MusicDownloader` to avoid triple-duplicating auth/extractor-arg logic across `_download_sync` (yt-dlp Python API), `_get_stream_sync` (yt-dlp CLI subprocess), and `_search_sync` (yt-dlp Python API):
  - `_auth_options()` → returns either `{'cookiefile': ...}` or `{'username': 'oauth2', 'password': ''}` depending on `Config.YOUTUBE_OAUTH2_ENABLED`, for merging into `ydl_opts` dicts.
  - `_pot_extractor_args()` → returns the `extractor_args` dict fragment for the PO token provider base URL.
  - The CLI subprocess path (`_get_stream_sync`) translates the same two helpers into `--username/--password` or `--cookies`, plus `--extractor-args "youtubepot-bgutilhttp:base_url=..."`.
  - No new abstraction layer/plugin system is introduced beyond these two helpers — three call sites, two shared helpers.
- **`TROUBLESHOOTING.md`** — add a section documenting: how the PO token provider works and how to verify it's reachable; the one-time OAuth2 device-login command (generic `docker compose exec` / `docker exec`, not tied to any specific platform's UI); the two new env vars and how to disable OAuth2 to fall back to cookies.

## Error handling

- Missing/unreachable PO token provider → yt-dlp logs a warning, proceeds without a token (matches current no-cookie behavior — degrades gracefully, doesn't raise).
- OAuth2 not yet authorized (no cached token) → yt-dlp's own device-code prompt appears in the container logs; this is expected on first run until the one-time setup step is completed. Existing error handling in `downloader.py` (catching yt-dlp/subprocess exceptions and surfacing `❌ Hata: ...` to Discord) is unchanged and still applies.
- `YOUTUBE_OAUTH2_ENABLED=false` with no cookie file present → identical to today's behavior (bot runs, YouTube reliability degraded, already logged via `_find_cookie_file`).

## Verification plan

No automated tests exist in this repo (confirmed during initial `CLAUDE.md` codebase read). Verification is manual, post-deploy:

1. `docker compose up -d --build` and confirm the `pot-provider` service starts and stays healthy.
2. Run the one-time OAuth2 device-login command and complete authorization.
3. Restart the bot service and run `/play query:<a real YouTube URL>` in Discord; confirm audio streams without a "sign in to confirm you're not a bot" error.
4. Check bot logs for confirmation that both the cookie/oauth2 path and the PO token provider are being used (existing `print(...)` diagnostics in `downloader.py` will be extended to log which auth mode is active).
5. Restart the container (simulating a redeploy) and confirm OAuth2 does *not* require re-authorization (proves the cache volume persists correctly).
