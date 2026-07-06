# YouTube Bot Algılama Sorunları ve Çözümleri

Bu belge, Discord müzik botunun YouTube'dan müzik çekerken karşılaşabileceği sorunları ve çözümlerini içerir.

## 🚨 Yaygın Hata Mesajları

### 1. "Sign in to confirm you're not a bot"

```
ERROR: [youtube] XXXXX: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for the authentication.
```

**Nedenleri:**
- Cookie dosyası eksik veya geçersiz
- Cookie'lerin süresi dolmuş
- YouTube hesabı bot olarak işaretlenmiş
- Sunucu IP'si YouTube tarafından şüpheli görülüyor
- Bazı videolar ekstra koruma altında

**Çözümler:**
1. Cookie dosyasını yeniden oluşturun (aşağıya bakın)
2. Farklı bir YouTube hesabı deneyin
3. Farklı bir video deneyin (bazı videolar özel korunuyor)

---

### 2. "No supported JavaScript runtime could be found"

```
WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default
```

**Nedeni:**
- yt-dlp artık JavaScript runtime gerektiriyor (2024+ sürümleri)
- Node.js veya Deno kurulu değil

**Çözüm:**
- Dockerfile'a Node.js eklendi
- `--js-runtimes node` parametresi kullanılıyor

---

### 3. "android client https formats require a GVS PO Token"

```
WARNING: [youtube] XXXXX: android client https formats require a GVS PO Token which was not provided
```

**Nedeni:**
- YouTube, Android client için PO Token istiyor
- Bu yeni bir YouTube güvenlik önlemi

**Çözüm:**
- Bot otomatik olarak farklı formatları deniyor
- Genellikle başka bir format çalışır

---

## 🍪 Cookie Dosyası Oluşturma

### Adım 1: Yerel Bilgisayarında

```bash
# Chrome'dan cookie çek
yt-dlp --cookies-from-browser chrome --cookies cookies.txt

# Firefox'tan
yt-dlp --cookies-from-browser firefox --cookies cookies.txt

# Edge'den
yt-dlp --cookies-from-browser edge --cookies cookies.txt
```

### Adım 2: Cookie Dosyasını Kontrol Et

İlk satır şu şekilde olmalı:
```
# Netscape HTTP Cookie File
```

### Adım 3: Sunucuya Yükle

Cookie dosyasını `/app/cookies/cookies.txt` yoluna yükleyin.

### Adım 4: Test Et

```bash
# Container içinde test
yt-dlp --cookies /app/cookies/cookies.txt --js-runtimes node -f bestaudio -g "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

---

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

`discord-bot`'un kendi ağı olmadığı için, `warp` container'ı çökerse veya yeniden başlarsa `discord-bot` **tüm** bağlantısını kaybeder — sadece YouTube erişimini değil, Discord gateway/ses bağlantısını da. `restart: unless-stopped` ve healthcheck'e bağlı `depends_on` bunu büyük ölçüde toparlar (discord.py kendi reconnect mantığıyla `warp` geri geldiğinde otomatik bağlanır) ama garanti değildir. Bu, tüm trafiği tek bir noktadan geçirmenin bilinçli olarak kabul edilmiş bir bedelidir.

### Health check endpoint kullanıyorsanız

`ENABLE_HEALTH_SERVER=1` / `PORT` (bkz. `config.py`, `bot.py`'deki `_start_health_server_if_enabled`) ileride bir deployment platformu için açılırsa, `ports:` eşlemesinin `discord-bot` yerine **`warp` servisine** eklenmesi gerekir — dinleyen soket fiziksel olarak `warp`'ın ağ namespace'inde yaşar.

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

### Cookie Dosyasını Kontrol Et
```bash
ls -la /app/cookies/
cat /app/cookies/cookies.txt | head -5
```

### Node.js Kontrolü
```bash
node --version
```

### yt-dlp Testi
```bash
# Basit test
yt-dlp --cookies /app/cookies/cookies.txt --js-runtimes node -f bestaudio -g "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# JSON çıktı ile test
yt-dlp --cookies /app/cookies/cookies.txt --js-runtimes node --dump-json "https://www.youtube.com/watch?v=dQw4w9WgXcQ" | head -20
```

### Python API Testi
```bash
python3 -c "
import yt_dlp
ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'cookiefile': '/app/cookies/cookies.txt',
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ', download=False)
    print('Title:', info.get('title'))
    print('URL:', info.get('url', 'No direct URL'))
"
```

---

## ⚠️ Bilinen Kısıtlamalar

### Bazı Videolar Çalışmayabilir

YouTube, bazı videoları ekstra koruma altına alır:
- Telif hakkı korumalı içerikler
- Yaş sınırlı videolar
- Bölge kısıtlamalı videolar
- Yeni yüklenen popüler videolar

**Çözüm:** Farklı bir video deneyin.

### Cookie'ler Zaman İçinde Geçersiz Olabilir

YouTube cookie'leri genellikle 1-4 hafta içinde expire olur.

**Çözüm:** Cookie dosyasını düzenli olarak yenileyin.

### Sunucu IP'si Engellenmiş Olabilir

VPS/Cloud sunucu IP'leri YouTube tarafından şüpheli görülebilir.

**Çözüm:** Farklı bir sunucu veya residential proxy deneyin.

---

## 📋 Teknik Detaylar

### Kullanılan Teknolojiler
- **yt-dlp**: YouTube video/audio indirme
- **Node.js**: JavaScript runtime (yt-dlp için gerekli)
- **FFmpeg**: Ses dönüştürme
- **discord.py**: Discord bot framework

### Dockerfile Gereksinimleri
```dockerfile
# Node.js kurulumu (yt-dlp JS runtime için)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs
```

### yt-dlp Parametreleri
```
--js-runtimes node     # JavaScript runtime olarak Node.js kullan
--cookies FILE         # Cookie dosyası
-f bestaudio/best      # En iyi ses kalitesi
--dump-json            # JSON çıktı (API için)
```

---

## 🔗 Faydalı Linkler

- [yt-dlp Wiki - Cookies](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
- [yt-dlp Wiki - EJS (JavaScript Runtime)](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [yt-dlp GitHub Issues](https://github.com/yt-dlp/yt-dlp/issues)

---

*Son güncelleme: Ocak 2026*
