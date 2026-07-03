# YouTube Bot-Detection Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the deployed bot's YouTube "Sign in to confirm you're not a bot" failures by adding a PO Token provider service and an OAuth2 account-login option to yt-dlp, while keeping the existing cookie-file mechanism as a fallback.

**Architecture:** Two independent auth layers are layered on top of the existing cookie mechanism in `downloader.py`: (1) a sidecar Docker service (`pot-provider`) that supplies PO Tokens to yt-dlp via a plugin, and (2) an optional one-time OAuth2 device-code login (`yt-dlp-youtube-oauth2` plugin) that replaces the cookie file when enabled. Two small helper methods on `MusicDownloader` (`_auth_options()`, `_pot_extractor_args()`) centralize the auth/PO-token config so all three yt-dlp call sites (`_download_sync`, `_get_stream_sync`, `_search_sync`) stay in sync.

**Tech Stack:** Python 3.11 (Docker) / 3.13 (local dev venv), discord.py, yt-dlp, `bgutil-ytdlp-pot-provider`, `yt-dlp-youtube-oauth2`, Docker Compose.

## Global Constraints

- Platform-agnostic: no Coolify-specific instructions or commands — only plain `docker` / `docker compose exec`.
- The existing `cookies/cookies.txt` fallback must keep working unchanged when `YOUTUBE_OAUTH2_ENABLED=false`.
- `Config.POT_PROVIDER_BASE_URL` default is `http://pot-provider:4416` (must match the `docker-compose.yml` service name `pot-provider`).
- `Config.YOUTUBE_OAUTH2_ENABLED` default is `true` (this is a private, single-server bot — the spec explicitly accepts the account-login trade-off).
- The approved spec's non-goals explicitly exclude adding a test suite (repo has zero tests today). Every verification step in this plan is therefore a manual command run with real, observed output — not a committed test file or new test dependency.
- Do not modify `README.md` — the approved spec scopes documentation changes to `TROUBLESHOOTING.md` only.
- `docker` is not installed on this dev machine (confirmed during planning) — `docker-compose.yml` changes are verified by careful manual review of the diff, not by running `docker compose config`. Real infra verification happens manually post-deploy (already covered by the spec's verification plan).

---

### Task 1: Add new dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `bgutil-ytdlp-pot-provider` and `yt-dlp-youtube-oauth2` installed in the venv (used at runtime by yt-dlp once wired up in Task 4 — not directly imported by our code).

- [ ] **Step 1: Add the two new lines to `requirements.txt`**

Current content:
```
discord.py>=2.3.0
yt-dlp>=2024.1.0
python-dotenv>=1.0.0
PyNaCl>=1.5.0
```

New content:
```
discord.py>=2.3.0
yt-dlp>=2024.1.0
python-dotenv>=1.0.0
PyNaCl>=1.5.0
bgutil-ytdlp-pot-provider
yt-dlp-youtube-oauth2
```

We deliberately don't pin a minimum version for these two — their correct minimum working versions weren't verifiable during planning (no network access), so pinning a guessed floor risks a broken `pip install` for no benefit.

- [ ] **Step 2: Install the updated requirements into the project venv**

Run (PowerShell, from repo root):
```powershell
.venv\Scripts\pip.exe install -r requirements.txt
```
Expected: all packages install with no errors, ending in a line like `Successfully installed ... bgutil-ytdlp-pot-provider-... yt-dlp-youtube-oauth2-...` (exact versions will vary — that's fine).

If this fails because the sandbox has no network access, say so explicitly instead of claiming success — this step must be re-run wherever the bot is actually deployed/developed with network access.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "Add PO token provider and OAuth2 yt-dlp plugin dependencies"
```

---

### Task 2: Add PO Token provider service and OAuth2 cache volume to Docker Compose

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: a `pot-provider` service reachable (once deployed) at `http://pot-provider:4416` on the `bot-network` — this exact host:port is the value Task 3 will use as `Config.POT_PROVIDER_BASE_URL`'s default. A `./ytdlp-cache` host directory mounted at `/root/.cache/yt-dlp` in the `discord-bot` container — this is where the OAuth2 plugin (Task 4) persists its refresh token.

- [ ] **Step 1: Update `docker-compose.yml`**

Current content:
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
    volumes:
      # Persist music and playlists
      - ./music:/app/music
      - ./playlists:/app/playlists
      # Cookies directory
      - ./cookies:/app/cookies
      # YouTube cookies (optional - only if you have cookies.txt file)
      # Uncomment the line below if you have a cookies.txt file
      # - ./cookies.txt:/app/cookies.txt
    networks:
      - bot-network

networks:
  bot-network:
    driver: bridge
```

New content:
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

- [ ] **Step 2: Update `.gitignore`**

Find this existing block:
```
# YouTube cookies (contains sensitive authentication data)
cookies/
cookies.txt
*.cookies
```

Add immediately after it:
```
# yt-dlp OAuth2 token cache (contains sensitive authentication data)
ytdlp-cache/
```

- [ ] **Step 3: Manually verify the YAML structure**

`docker` is not installed in this dev environment, so `docker compose config` cannot be run here. Instead, re-read the full `docker-compose.yml` file and confirm:
- `pot-provider` is a sibling key of `discord-bot` under `services:`, indented exactly 2 spaces (same level as `discord-bot:`).
- `depends_on:` and the new volume line are indented exactly 4 spaces (same level as the existing `volumes:` and other `discord-bot` keys).
- The file still has exactly one top-level `networks:` block at the end.

Note in your task summary that real validation (`docker compose config` / `docker compose up -d --build`) must happen on a machine with Docker installed before relying on this in production.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "Add PO token provider service and OAuth2 cache volume"
```

---

### Task 3: Add Config fields for PO token provider and OAuth2 toggle

**Files:**
- Modify: `config.py:27-29`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.Config.POT_PROVIDER_BASE_URL` (str, default `'http://pot-provider:4416'`) and `config.Config.YOUTUBE_OAUTH2_ENABLED` (bool, default `True`) — Task 4's `_auth_options()` and `_pot_extractor_args()` read these two attributes directly.

- [ ] **Step 1: Add the two fields to `config.py`**

Current `config.py:27-29`:
```python
    # YouTube cookie dosyası yolu - .env'den veya None
    YOUTUBE_COOKIES_FILE = os.getenv('YOUTUBE_COOKIES_FILE', None)
    
```

New:
```python
    # YouTube cookie dosyası yolu - .env'den veya None
    YOUTUBE_COOKIES_FILE = os.getenv('YOUTUBE_COOKIES_FILE', None)

    # PO Token provider adresi (bot algılamasını hesaba gerek kalmadan aşmak için)
    POT_PROVIDER_BASE_URL = os.getenv('POT_PROVIDER_BASE_URL', 'http://pot-provider:4416')

    # OAuth2 ile YouTube hesabı girişi (varsayılan açık - private bot için kabul edilebilir)
    YOUTUBE_OAUTH2_ENABLED = os.getenv('YOUTUBE_OAUTH2_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes', 'on')

```

- [ ] **Step 2: Manually verify default values**

Run (PowerShell, from repo root):
```powershell
Remove-Item Env:POT_PROVIDER_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:YOUTUBE_OAUTH2_ENABLED -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -c "import config; print(config.Config.POT_PROVIDER_BASE_URL); print(config.Config.YOUTUBE_OAUTH2_ENABLED)"
```
Expected output:
```
http://pot-provider:4416
True
```

- [ ] **Step 3: Manually verify overrides**

Run:
```powershell
$env:POT_PROVIDER_BASE_URL = 'http://custom-host:1234'
$env:YOUTUBE_OAUTH2_ENABLED = 'false'
.venv\Scripts\python.exe -c "import config; print(config.Config.POT_PROVIDER_BASE_URL); print(config.Config.YOUTUBE_OAUTH2_ENABLED)"
Remove-Item Env:POT_PROVIDER_BASE_URL
Remove-Item Env:YOUTUBE_OAUTH2_ENABLED
```
Expected output:
```
http://custom-host:1234
False
```
(The `Remove-Item` cleanup lines matter — otherwise these env vars leak into your shell session and affect later steps in this plan.)

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "Add POT_PROVIDER_BASE_URL and YOUTUBE_OAUTH2_ENABLED config fields"
```

---

### Task 4: Wire PO token provider and OAuth2 into `downloader.py`

**Files:**
- Modify: `downloader.py:95-102` (replace `_add_cookie_support`), `downloader.py:40-41` (call site in `__init__`), `downloader.py:147-150` (`_get_stream_sync`), `downloader.py:278-281` (`_search_sync`)

**Interfaces:**
- Consumes: `config.Config.POT_PROVIDER_BASE_URL` (str), `config.Config.YOUTUBE_OAUTH2_ENABLED` (bool) — from Task 3.
- Produces: `MusicDownloader._auth_options()` → `dict` (either `{'username': 'oauth2', 'password': ''}`, `{'cookiefile': <path>}`, or `{}`). `MusicDownloader._pot_extractor_args()` → `dict` (either `{'youtubepot-bgutilhttp': {'base_url': [<url>]}}` or `{}`). These two methods are the only things later tasks (Task 5's docs) refer to by name.

- [ ] **Step 1: Replace `_add_cookie_support` with `_auth_options`, `_pot_extractor_args`, and `_configure_auth` in `downloader.py`**

Current `downloader.py:95-102`:
```python
    def _add_cookie_support(self):
        """Cookie desteği ekle - YouTube bot algılamasını önlemek için"""
        if self.cookie_file:
            self.ydl_opts['cookiefile'] = self.cookie_file
            print(f"✅ Cookie dosyası yüklendi: {self.cookie_file}", flush=True)
        else:
            print("⚠️  Cookie dosyası yüklenemedi. YouTube bot algılaması sorunları yaşanabilir.", flush=True)
            print(f"💡 Cookie dosyası yolu: {Config.COOKIES_DIR}/cookies.txt", flush=True)
```

New:
```python
    def _auth_options(self):
        """yt-dlp için kimlik doğrulama ayarlarını döndür (oauth2 öncelikli, yoksa cookiefile)"""
        if Config.YOUTUBE_OAUTH2_ENABLED:
            return {'username': 'oauth2', 'password': ''}
        if self.cookie_file:
            return {'cookiefile': self.cookie_file}
        return {}

    def _pot_extractor_args(self):
        """yt-dlp için PO Token provider extractor_args ayarını döndür"""
        if not Config.POT_PROVIDER_BASE_URL:
            return {}
        return {'youtubepot-bgutilhttp': {'base_url': [Config.POT_PROVIDER_BASE_URL]}}

    def _configure_auth(self):
        """Kimlik doğrulama ve PO token ayarlarını ydl_opts'a uygula"""
        auth = self._auth_options()
        self.ydl_opts.update(auth)

        pot_args = self._pot_extractor_args()
        if pot_args:
            self.ydl_opts['extractor_args'] = pot_args
            print(f"✅ PO Token provider aktif: {Config.POT_PROVIDER_BASE_URL}", flush=True)
        else:
            print("⚠️  PO Token provider yapılandırılmadı.", flush=True)

        if 'username' in auth:
            print("✅ YouTube OAuth2 kimlik doğrulama aktif (username=oauth2)", flush=True)
        elif 'cookiefile' in auth:
            print(f"✅ Cookie dosyası yüklendi: {auth['cookiefile']}", flush=True)
        else:
            print("⚠️  Kimlik doğrulama yapılandırılmadı. YouTube bot algılaması sorunları yaşanabilir.", flush=True)
            print(f"💡 Cookie dosyası yolu: {Config.COOKIES_DIR}/cookies.txt", flush=True)
```

- [ ] **Step 2: Update the call site in `__init__` (`downloader.py:40-41`)**

Current:
```python
        # Cookie desteği ekle (bot algılamasını önlemek için)
        self._add_cookie_support()
```

New:
```python
        # Kimlik doğrulama ve PO token ayarlarını ekle
        self._configure_auth()
```

- [ ] **Step 3: Update `_get_stream_sync` (`downloader.py:147-150`)**

Current:
```python
            # Cookie dosyası ekle
            if self.cookie_file:
                cmd.extend(['--cookies', self.cookie_file])
                print(f"🔐 Cookie kullanılıyor: {self.cookie_file}", flush=True)
            
            cmd.append(url)
```

New:
```python
            # Kimlik doğrulama ekle (oauth2 veya cookiefile)
            auth = self._auth_options()
            if 'username' in auth:
                cmd.extend(['--username', auth['username'], '--password', auth['password']])
                print("🔐 OAuth2 kimlik doğrulama kullanılıyor", flush=True)
            elif 'cookiefile' in auth:
                cmd.extend(['--cookies', auth['cookiefile']])
                print(f"🔐 Cookie kullanılıyor: {auth['cookiefile']}", flush=True)

            # PO Token provider ekle
            pot_args = self._pot_extractor_args()
            if pot_args:
                base_url = pot_args['youtubepot-bgutilhttp']['base_url'][0]
                cmd.extend(['--extractor-args', f'youtubepot-bgutilhttp:base_url={base_url}'])
                print(f"🔐 PO Token provider kullanılıyor: {base_url}", flush=True)

            cmd.append(url)
```

- [ ] **Step 4: Update `_search_sync` (`downloader.py:278-281`)**

Current:
```python
            # Cookie desteği ekle
            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                print(f"🔐 Arama için cookie kullanılıyor: {self.cookie_file}", flush=True)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
```

New:
```python
            # Kimlik doğrulama ve PO token ayarlarını ekle
            ydl_opts.update(self._auth_options())
            pot_args = self._pot_extractor_args()
            if pot_args:
                ydl_opts['extractor_args'] = pot_args

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
```

- [ ] **Step 5: Manually verify `_auth_options()` and `_pot_extractor_args()` behavior**

Run (PowerShell, from repo root — this constructs a real `MusicDownloader`, which will print its normal startup diagnostics; that's expected):
```powershell
.venv\Scripts\python.exe -c "
from config import Config
import downloader

Config.YOUTUBE_OAUTH2_ENABLED = True
Config.POT_PROVIDER_BASE_URL = 'http://pot-provider:4416'
d = downloader.MusicDownloader()
print('RESULT oauth2-on:', d._auth_options())
print('RESULT pot-args:', d._pot_extractor_args())

Config.YOUTUBE_OAUTH2_ENABLED = False
d.cookie_file = 'C:/fake/cookies.txt'
print('RESULT oauth2-off-with-cookie:', d._auth_options())

d.cookie_file = None
print('RESULT oauth2-off-no-cookie:', d._auth_options())

Config.POT_PROVIDER_BASE_URL = ''
print('RESULT pot-args-empty:', d._pot_extractor_args())
"
```
Expected (among the startup diagnostic noise, look for these five `RESULT` lines):
```
RESULT oauth2-on: {'username': 'oauth2', 'password': ''}
RESULT pot-args: {'youtubepot-bgutilhttp': {'base_url': ['http://pot-provider:4416']}}
RESULT oauth2-off-with-cookie: {'cookiefile': 'C:/fake/cookies.txt'}
RESULT oauth2-off-no-cookie: {}
RESULT pot-args-empty: {}
```

- [ ] **Step 6: Commit**

```bash
git add downloader.py
git commit -m "Wire PO token provider and OAuth2 auth into yt-dlp calls"
```

---

### Task 5: Document the new setup in TROUBLESHOOTING.md

**Files:**
- Modify: `TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: the exact commands and env var names/defaults established in Tasks 2-4 (`POT_PROVIDER_BASE_URL`, `YOUTUBE_OAUTH2_ENABLED`, `docker compose exec discord-bot yt-dlp --username oauth2 --password ''`, `./ytdlp-cache`).
- Produces: nothing consumed by other tasks — this is the last task.

- [ ] **Step 1: Insert a new section into `TROUBLESHOOTING.md`**

Find this existing text (the end of the cookie-creation section, right before the Coolify terminal commands section):
```
**Önemli:** Cookie dosyası formatı Netscape formatında olmalı (ilk satır `# Netscape HTTP Cookie File` ile başlamalı).

---

## 🔧 Coolify Terminal Komutları
```

Replace it with:
```
**Önemli:** Cookie dosyası formatı Netscape formatında olmalı (ilk satır `# Netscape HTTP Cookie File` ile başlamalı).

---

## 🤖 PO Token Provider ve OAuth2 (Kalıcı Sunucu Tarafı Çözüm)

Cookie dosyası haftalar içinde expire olduğu için, kalıcı bir çözüm olarak iki katman eklendi. İkisi de mevcut cookie yöntemini bozmuyor, üstüne ekleniyor.

### PO Token Provider

`docker-compose.yml` içinde `pot-provider` adında ayrı bir servis çalışır (`brainicism/bgutil-ytdlp-pot-provider` image'ı). Bu servis, YouTube'un bot kontrolünü hesaba giriş yapmadan aşmak için gereken PO Token'ı üretir.

**Doğrulama:**
```bash
docker compose ps pot-provider
docker compose logs pot-provider
```

`pot-provider` servisi ayakta değilse bot loglarında `⚠️  PO Token provider yapılandırılmadı.` uyarısı görülür ve istekler PO Token olmadan devam eder (eski davranış, bot çökmez).

`POT_PROVIDER_BASE_URL` env değişkeni ile adres override edilebilir (varsayılan: `http://pot-provider:4416`, docker-compose'daki servis adıyla eşleşir).

### OAuth2 ile YouTube Hesabı Girişi

`YOUTUBE_OAUTH2_ENABLED` (varsayılan: `true`) açıkken, bot cookie yerine gerçek bir YouTube hesabına OAuth2 ile giriş yapar. Bu, cookie'lerin haftalık expire olma sorununu ortadan kaldırır.

**Tek seferlik kurulum (herhangi bir Docker host'ta, platformdan bağımsız):**

```bash
docker compose exec discord-bot yt-dlp --username oauth2 --password '' -f bestaudio -g "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Bu komut `https://www.google.com/device` adresini ve bir kod gösterir. Herhangi bir cihazdan/tarayıcıdan bu adrese gidip kodu girerek hesabı yetkilendirin. Token `./ytdlp-cache` klasöründe (docker-compose'da volume olarak bağlı) saklanır ve otomatik yenilenir — `ytdlp-cache` klasörü silinmediği sürece bu adımı tekrar yapmanız gerekmez, redeploy sonrası da geçerliliğini korur.

**Not:** Coolify kullanıyorsanız yukarıdaki komutu Coolify'ın web terminalinden de çalıştırabilirsiniz — bu Coolify'a özgü bir adım değildir, sadece bir shell'e erişim gerektirir ve `docker` kurulu her yerde aynı şekilde çalışır.

Cookie yöntemine geri dönmek isterseniz `.env` dosyasına `YOUTUBE_OAUTH2_ENABLED=false` ekleyin; bot otomatik olarak mevcut `cookies/cookies.txt` dosyasını kullanmaya devam eder.

---

## 🔧 Coolify Terminal Komutları
```

- [ ] **Step 2: Verify the section was inserted correctly**

Run:
```powershell
Select-String -Path TROUBLESHOOTING.md -Pattern "PO Token Provider ve OAuth2"
```
Expected: one match, confirming the new `##` heading exists in the file.

- [ ] **Step 3: Commit**

```bash
git add TROUBLESHOOTING.md
git commit -m "Document PO token provider and OAuth2 setup"
```
