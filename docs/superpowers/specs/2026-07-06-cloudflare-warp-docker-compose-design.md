# Cloudflare WARP for Docker Compose — Design

## Problem

The bot runs on a cloud/VPS server whose IP is sometimes flagged by YouTube independent of cookies/OAuth2/PO-token mitigations (documented in `TROUBLESHOOTING.md` as a known, unavoidable constraint). Routing the container's outbound traffic through Cloudflare WARP swaps the VPS's flagged/datacenter IP for a Cloudflare egress IP, which can avoid this class of IP-based blocking.

## Goals

- Route the `discord-bot` container's entire outbound network traffic through Cloudflare WARP.
- No Cloudflare account or paid plan required — anonymous consumer WARP registration only.
- Don't break the existing `pot-provider` connectivity (`POT_PROVIDER_BASE_URL=http://pot-provider:4416`) when `discord-bot`'s networking changes.
- Keep it operable with plain `docker compose` commands, consistent with the rest of the project's deployment story.

## Non-goals

- Not scoping WARP to only yt-dlp traffic (rejected alternative — see below). The whole `discord-bot` container's traffic, including the Discord gateway/voice connection, goes through WARP.
- No Cloudflare Zero Trust / WARP+ enrollment (team domain, license key) — anonymous consumer mode only.
- No Python code changes (`downloader.py`, `config.py`) — this is a pure deployment/infrastructure change, since routing happens at the container network level, not per-request.

## Chosen approach: `caomingjun/warp` sidecar via `network_mode: "service:warp"`

`caomingjun/warp` is a community-maintained image built specifically for this "front another container's entire network stack" pattern: it registers an anonymous WARP device on startup (no account needed) and exposes a healthcheck that verifies the tunnel is actually connected (a `warp-cli status` check alone would return success even while disconnected, since it only confirms the daemon process is responsive).

**Rejected alternative:** scoping WARP to only yt-dlp calls via a SOCKS5 proxy (`--proxy` / `ydl_opts['proxy']` in `downloader.py`), leaving the Discord gateway connection on the VPS's normal network. This was rejected in favor of routing all traffic, per explicit decision during design — accepting the trade-off below.

**Rejected alternative:** `wgcf` + a vanilla WireGuard sidecar (e.g. `linuxserver/wireguard`) instead of a WARP-specific daemon. More moving parts (one-time `wgcf register`/`wgcf generate` step to produce a config file) for no benefit over `caomingjun/warp`'s built-in anonymous registration; not chosen.

### Topology

- New `warp` service (`caomingjun/warp`) is added to `docker-compose.yml`, attached to the existing `bot-network`, with `NET_ADMIN` capability, `/dev/net/tun` device, the sysctls the image requires, and a bind-mounted volume (`./warp-data:/var/lib/cloudflare-warp`) so the anonymous device registration survives restarts/redeploys.
- `discord-bot` switches from `networks: [bot-network]` to `network_mode: "service:warp"` — it shares `warp`'s network namespace entirely (a container can't use both `network_mode` and its own `networks:` at once). `discord-bot` no longer declares its own `networks:` block.
- **Why `warp` (not `discord-bot`) stays on `bot-network`:** since `discord-bot` now shares `warp`'s network namespace, DNS resolution and routing for `discord-bot` are whatever `warp`'s namespace has access to. Attaching `warp` to `bot-network` keeps `pot-provider` (which stays on `bot-network`, unchanged) reachable at `http://pot-provider:4416` from inside `discord-bot`, exactly as before.
- `discord-bot`'s `depends_on` changes to `warp: condition: service_healthy` (so it doesn't start before WARP has actually registered and connected) plus `pot-provider: condition: service_started`.

### Trade-off accepted

Because `discord-bot` has no network of its own, if the `warp` container crashes or is restarted, `discord-bot` loses **all** connectivity — including the Discord gateway/voice connection, not just YouTube access. Worse: because `network_mode: "service:warp"` binds `discord-bot` to `warp`'s network namespace at container-start time, a `warp` restart tears down and recreates that namespace — `discord-bot` remains attached to the old, dead one. Nothing in discord.py's reconnect logic can repair this, since the failure is below the socket layer. Recovering requires restarting `discord-bot` alongside `warp` (`docker compose restart warp discord-bot`). The healthcheck-gated `depends_on` still protects the startup-ordering case (discord-bot won't start before warp is genuinely connected) — it just doesn't cover a later warp restart. This was discussed and explicitly accepted in favor of the simpler, uniform routing; the operational consequence is documented in `TROUBLESHOOTING.md` so it isn't a surprise during an incident.

### Operational consequence: health check port

If `ENABLE_HEALTH_SERVER=1` / `PORT` (see `config.py`, `bot.py`'s `_start_health_server_if_enabled`) is ever enabled for a deployment platform's health checks, the `ports:` mapping must be declared on the `warp` service, not `discord-bot` — the listening socket physically lives in `warp`'s network namespace. Not currently used (no platform health check is configured today), but documented so it isn't a surprise later.

## Components changed

- **`docker-compose.yml`**:
  - New `warp` service: image `caomingjun/warp`, `restart: unless-stopped`, `cap_add: [NET_ADMIN]`, `devices: [/dev/net/tun:/dev/net/tun]`, `sysctls: [net.ipv6.conf.all.disable_ipv6=0, net.ipv4.conf.all.src_valid_mark=1]`, volume `./warp-data:/var/lib/cloudflare-warp`, attached to `bot-network`, healthcheck via a `curl`-based Cloudflare trace check (confirms the tunnel is actually connected, not just that the daemon responds).
  - `discord-bot` service: replace `networks: [bot-network]` with `network_mode: "service:warp"`; update `depends_on` to `warp: condition: service_healthy` and `pot-provider: condition: service_started`.
  - `pot-provider` service: unchanged (stays on `bot-network`).
- **`.gitignore`**: add `warp-data/` (holds the anonymous WARP device registration/key material — same treatment as `cookies/` and `ytdlp-cache/`).
- **`TROUBLESHOOTING.md`**: new section, same style as the existing "PO Token Provider ve OAuth2" section — what WARP does, how to verify it's active, the shared-network trade-off, and the health-check-port caveat above.

## Error handling

- `warp` container fails to register/connect on first start → its healthcheck (Cloudflare trace check) fails, `discord-bot`'s `depends_on: condition: service_healthy` keeps it from starting until `warp` recovers (or the operator investigates `docker compose logs warp`). This matches the existing project convention of failing loudly on infra-level problems rather than silently degrading, since — unlike the PO token provider — there's no meaningful "degraded" mode when the whole network is gone.
- `warp` container crashes or is restarted after `discord-bot` is already running → `discord-bot` loses network entirely (Discord gateway drops, voice drops, YouTube fetches fail) and does **not** recover on its own even after `warp` (via `restart: unless-stopped`) comes back — the shared network namespace was torn down and recreated, and `discord-bot` is still attached to the old one. The operator must restart `discord-bot` alongside `warp` (`docker compose restart warp discord-bot`) to restore connectivity; this is documented in `TROUBLESHOOTING.md`.
- `pot-provider` unreachable from `discord-bot` (e.g. `warp` misconfigured/not on `bot-network`) → same existing graceful-degradation path as today (yt-dlp logs a warning, proceeds without a PO token) — this design does not change that behavior, it only must not *newly break* the network path that makes it reachable in the first place.

## Verification plan

No automated tests exist in this repo; verification is manual, post-deploy:

1. `docker compose up -d --build` and confirm `docker compose ps` shows `warp` as `healthy`.
2. `docker compose exec discord-bot curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp=` → expect `warp=on`.
3. `docker compose exec discord-bot curl -s -o /dev/null -w "%{http_code}\n" http://pot-provider:4416` → confirm `pot-provider` is still reachable through the shared namespace.
4. Restart the `warp` container (`docker compose restart warp`) while the bot is connected in a Discord voice channel, and confirm the bot's voice/gateway connection drops and stays dropped until `discord-bot` is also restarted (`docker compose restart warp discord-bot`) — validates that the documented recovery procedure, not silent self-healing, is what actually works.
5. Run `/play query:<a real YouTube URL>` in Discord and confirm playback works as before.
