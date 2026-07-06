# Cloudflare WARP Docker Compose Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the `discord-bot` container's entire outbound network traffic through a Cloudflare WARP sidecar, to avoid YouTube's IP-based blocking of the deployment VPS.

**Architecture:** Add a new `warp` service (`caomingjun/warp` image) to `docker-compose.yml`, attached to `bot-network`. Switch `discord-bot` from `networks: [bot-network]` to `network_mode: "service:warp"` so it shares WARP's network namespace entirely. `pot-provider` stays on `bot-network` unchanged, and stays reachable from `discord-bot` because `warp` (whose namespace `discord-bot` now shares) is also on `bot-network`.

**Tech Stack:** Docker Compose, `caomingjun/warp` image (anonymous consumer WARP registration, no Cloudflare account). No Python/application code changes.

## Global Constraints

- No Cloudflare account, team domain, or WARP+ license — anonymous consumer WARP registration only (per design spec decision).
- `discord-bot`'s entire traffic (Discord gateway + voice + YouTube) routes through WARP, not just yt-dlp calls — this was an explicit, accepted design decision, not an oversight.
- `pot-provider` connectivity (`http://pot-provider:4416`) from inside `discord-bot` must keep working after this change.
- No changes to `downloader.py`, `config.py`, or any other Python file — this is a pure `docker-compose.yml` / docs change.
- **This dev environment has no `docker` binary installed.** Every step that runs an actual `docker compose` command must be executed on the real deployment host (the VPS/Coolify instance, via SSH or its web terminal) — not in this local sandbox. Steps below say explicitly "Run on the deployment host" whenever this applies.
- Design spec: `docs/superpowers/specs/2026-07-06-cloudflare-warp-docker-compose-design.md` — read it first if anything below is ambiguous.

---

### Task 1: Add `warp` service and rewire `discord-bot` networking in `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a `docker-compose.yml` where `discord-bot` has `network_mode: "service:warp"` and no `networks:` key; a `warp` service with container name `eca-warp` reachable via a Docker healthcheck that verifies actual WARP tunnel connectivity (Cloudflare trace check, not just daemon liveness); a `.gitignore` entry `warp-data/`. Task 3 (deploy/verify) depends on this file being correct.

- [ ] **Step 1: Replace the full contents of `docker-compose.yml`**

Current file (for reference — confirm it still matches before editing; if it doesn't, stop and reconcile with whoever last touched it instead of blindly overwriting):

```yaml
services:
  discord-bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: eca-discord-bot
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      - pot-provider
    volumes:
      # Persist music and playlists
      - ./music:/app/music
      - ./playlists:/app/playlists
      # Cookies directory
      - ./cookies:/app/cookies
      # YouTube cookies (optional - only if you have cookies.txt file)
      # Uncomment the line below if you have a cookies.txt file
      # - ./cookies.txt:/app/cookies.txt
      # yt-dlp OAuth2 token cache (persists YouTube login across restarts)
      - ./ytdlp-cache:/root/.cache/yt-dlp
    networks:
      - bot-network

  pot-provider:
    image: brainicism/bgutil-ytdlp-pot-provider
    container_name: eca-pot-provider
    restart: unless-stopped
    networks:
      - bot-network

networks:
  bot-network:
    driver: bridge
```

Replace it with:

```yaml
services:
  warp:
    image: caomingjun/warp
    container_name: eca-warp
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=0
      - net.ipv4.conf.all.src_valid_mark=1
    volumes:
      - ./warp-data:/var/lib/cloudflare-warp
    networks:
      - bot-network
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS https://www.cloudflare.com/cdn-cgi/trace | grep -q 'warp=on'"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

  discord-bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: eca-discord-bot
    restart: unless-stopped
    env_file:
      - .env
    network_mode: "service:warp"
    depends_on:
      warp:
        condition: service_healthy
      pot-provider:
        condition: service_started
    volumes:
      # Persist music and playlists
      - ./music:/app/music
      - ./playlists:/app/playlists
      # Cookies directory
      - ./cookies:/app/cookies
      # YouTube cookies (optional - only if you have cookies.txt file)
      # Uncomment the line below if you have a cookies.txt file
      # - ./cookies.txt:/app/cookies.txt
      # yt-dlp OAuth2 token cache (persists YouTube login across restarts)
      - ./ytdlp-cache:/root/.cache/yt-dlp

  pot-provider:
    image: brainicism/bgutil-ytdlp-pot-provider
    container_name: eca-pot-provider
    restart: unless-stopped
    networks:
      - bot-network

networks:
  bot-network:
    driver: bridge
```

Note what changed: `warp` is new; `discord-bot` lost its `networks:` block and `depends_on: [pot-provider]` list form, gained `network_mode: "service:warp"` and the two-condition `depends_on` map form; `pot-provider` is untouched.

- [ ] **Step 2: Add `warp-data/` to `.gitignore`**

Open `.gitignore` and find this existing block:

```
# yt-dlp OAuth2 token cache (contains sensitive authentication data)
ytdlp-cache/
```

Add a new block directly after it:

```
# Cloudflare WARP device registration/key material
warp-data/
```

- [ ] **Step 3: Validate Compose syntax (run on the deployment host, not locally)**

```bash
docker compose config
```

Expected: no errors; output YAML includes a `warp` service and a `discord-bot` service where `discord-bot` has no `networks` key (it inherits `warp`'s network via `network_mode`).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "Add Cloudflare WARP sidecar and route discord-bot traffic through it"
```

---

### Task 2: Document Cloudflare WARP in `TROUBLESHOOTING.md`

**Files:**
- Modify: `TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: the `warp` service name/container name (`eca-warp`) and healthcheck defined in Task 1.
- Produces: a documented, discoverable explanation of the WARP layer for future maintenance — no other task depends on this one.

- [ ] **Step 1: Add a new "Cloudflare WARP" section**

Find the existing section in `TROUBLESHOOTING.md` that starts with:

```
## 🤖 PO Token Provider ve OAuth2 (Kalıcı Sunucu Tarafı Çözüm)
```

Insert a new section **immediately before** that heading (so WARP — routing the whole container — is documented ahead of the more targeted yt-dlp-only mitigations):

```markdown
## 🌐 Cloudflare WARP (VPS IP'sini Değiştirme)

Bazı cloud/VPS sağlayıcılarının IP aralıkları, cookie/OAuth2/PO-Token durumundan bağımsız olarak YouTube tarafından engellenmiş olabilir. Bunu aşmak için `discord-bot` container'ının **tüm** ağ trafiği (Discord gateway/ses bağlantısı dahil), `warp` adlı bir sidecar servis üzerinden Cloudflare WARP'a yönlendirilir.

### Nasıl çalışır

`docker-compose.yml`'deki `warp` servisi (`caomingjun/warp` image'ı) açılışta anonim bir WARP cihazı olarak kayıt olur (Cloudflare hesabı gerekmez). `discord-bot` servisi `network_mode: "service:warp"` ile bu container'ın ağ namespace'ini birebir paylaşır — yani kendi ağı yoktur, tüm giden trafiği WARP arayüzünden çıkar.

`pot-provider` servisi hâlâ `bot-network` üzerinde durur; `warp` da aynı ağa bağlı olduğu için `discord-bot`, `warp`'ın namespace'i üzerinden `http://pot-provider:4416` adresine erişmeye devam eder.

### Doğrulama

```bash
docker compose ps
# 'warp' servisi "healthy" görünmeli

docker compose exec discord-bot curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp=
# beklenen: warp=on

docker compose exec discord-bot curl -s -o /dev/null -w "%{http_code}\n" http://pot-provider:4416
# pot-provider'a hâlâ erişilebildiğini doğrular
```

### Kabul edilen risk

`discord-bot`'un kendi ağı olmadığı için, `warp` container'ı çökerse veya yeniden başlarsa `discord-bot` **tüm** bağlantısını kaybeder — sadece YouTube erişimini değil, Discord gateway/ses bağlantısını da. `network_mode: "service:warp"`, `discord-bot`'u `warp`'ın o anki ağ namespace'ine bağlar; `warp` yeniden başladığında namespace'i yenilenir ama `discord-bot` eski (artık ölü) namespace'e bağlı kalır — discord.py'nin kendi reconnect mantığı bunu kurtaramaz, çünkü sorun uygulama katmanında değil, kernel network namespace'inin kendisinde.

**Bu yüzden `warp` her ne sebeple yeniden başlarsa başlasın (elle `docker compose restart warp`, çökme sonrası `restart: unless-stopped`, ya da başka bir müdahale), `discord-bot`'un da yeniden başlatılması gerekir:**

```bash
docker compose restart warp discord-bot
```

`docker compose up -d --build` ile yapılan tam bir redeploy bu sorunu yaşamaz (Compose her iki servisi de doğru sırayla yeniden oluşturur) — risk yalnızca `warp`'ın tek başına yeniden başlaması durumunda geçerlidir. Bu, tüm trafiği tek bir noktadan geçirmenin bilinçli olarak kabul edilmiş bir bedelidir.

### Health check endpoint kullanıyorsanız

`ENABLE_HEALTH_SERVER=1` / `PORT` (bkz. `config.py`, `bot.py`'deki `_start_health_server_if_enabled`) ileride bir deployment platformu için açılırsa, `ports:` eşlemesinin `discord-bot` yerine **`warp` servisine** eklenmesi gerekir — dinleyen soket fiziksel olarak `warp`'ın ağ namespace'inde yaşar.
```

- [ ] **Step 2: Commit**

```bash
git add TROUBLESHOOTING.md
git commit -m "Document Cloudflare WARP setup and trade-offs in TROUBLESHOOTING.md"
```

---

### Task 3: Deploy and verify on the real host

**Files:** none (deployment + manual verification only — no repo files change in this task).

**Interfaces:**
- Consumes: `docker-compose.yml` and `.gitignore` from Task 1, `TROUBLESHOOTING.md` from Task 2.
- Produces: a confirmed-working deployment. Nothing depends on this task; it's the end of the plan.

- [ ] **Step 1: Pull the latest code on the deployment host**

Run on the deployment host:

```bash
git pull
```

Expected: fast-forwards to include the commits from Task 1 and Task 2.

- [ ] **Step 2: Rebuild and start**

Run on the deployment host:

```bash
docker compose up -d --build
```

Expected: `warp`, `discord-bot`, and `pot-provider` all report `Started`/`Created` with no errors.

- [ ] **Step 3: Confirm `warp` is healthy**

Run on the deployment host:

```bash
docker compose ps
```

Expected: the `warp` row shows `healthy` (may take up to `start_period` (20s) + a couple of healthcheck intervals to flip from `starting` to `healthy`).

- [ ] **Step 4: Confirm traffic is actually routed through WARP**

Run on the deployment host:

```bash
docker compose exec discord-bot curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp=
```

Expected output: `warp=on`

- [ ] **Step 5: Confirm `pot-provider` is still reachable**

Run on the deployment host:

```bash
docker compose exec discord-bot curl -s -o /dev/null -w "%{http_code}\n" http://pot-provider:4416
```

Expected: a numeric HTTP status code is printed (any response at all, e.g. `404` or `200`, confirms the TCP connection and DNS resolution succeeded — a hang or `curl: (7) Failed to connect` means the network wiring from Task 1 is wrong and `warp` needs to be checked for `bot-network` membership).

- [ ] **Step 6: Confirm the bot itself still works end-to-end**

In a real Discord server the bot is in, run `/play query:<a real YouTube URL>` and confirm audio plays.

- [ ] **Step 7: Confirm the accepted trade-off and its documented recovery procedure**

While the bot is connected to a voice channel and playing audio, run on the deployment host:

```bash
docker compose restart warp
```

Expected: the bot's voice/gateway connection drops and does **not** recover on its own — `discord-bot` remains attached to the network namespace `warp` had before the restart, which is now gone. Then run:

```bash
docker compose restart warp discord-bot
```

Expected: the bot reconnects and voice playback can resume. This confirms the failure mode from the design spec is real but recoverable via the documented procedure (restart both services together) — not a silent auto-recovery, and not a permanent unrecoverable hang either.
