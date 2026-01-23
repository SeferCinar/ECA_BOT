# Discord Müzik Botu

Kişisel sunucunuz için geliştirilmiş Discord müzik botu. Yerel müzik dosyalarını çalabilir, YouTube ve diğer platformlardan müzik indirebilir ve playlist yönetimi yapabilir.

## Özellikler

- 🎵 Yerel müzik dosyalarını çalma
- 🔽 YouTube ve diğer platformlardan müzik indirme (yt-dlp)
- 🔍 YouTube'da şarkı arama ve seçme
- 📋 Playlist oluşturma ve yönetimi
- 🔗 Playlist'lere link ile şarkı ekleme
- 👥 Playlist'lere düzenleme yetkisi verme sistemi
- ⏭️ Şarkı geçme
- 🔊 Ses seviyesi kontrolü
- 🔀 Kuyruk karıştırma
- ⚡ Discord slash komutları desteği

## Kurulum

### 1. Gereksinimler

- Python 3.8 veya üzeri
- FFmpeg (ses dosyalarını çalmak için)

### 2. FFmpeg Kurulumu

**Windows:**
1. [FFmpeg'i indirin](https://ffmpeg.org/download.html)
2. ZIP dosyasını açın ve `bin` klasörünü PATH'e ekleyin
3. Veya `ffmpeg.exe` dosyasını proje klasörüne kopyalayın

**Linux:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### 3. Bot Token Alma

1. [Discord Developer Portal](https://discord.com/developers/applications) adresine gidin
2. Yeni bir uygulama oluşturun
3. "Bot" sekmesine gidin ve bir bot oluşturun
4. Bot token'ınızı kopyalayın
5. "OAuth2" > "URL Generator" sekmesinden bot izinlerini seçin:
   - **Scopes:**
     - `bot` ✅
     - `applications.commands` ✅ (Slash komutları için ZORUNLU!)
   - **Bot Permissions:**
     - `Connect` (Ses kanalına bağlanma)
     - `Speak` (Ses kanalında konuşma)
     - `Use Voice Activity` (Ses aktivitesi kullanma)
     - `Use Application Commands` (Slash komutları kullanma)
   
   **ÖNEMLİ:** `applications.commands` scope'unu mutlaka işaretleyin! Aksi halde slash komutlar görünmez.

### 4. Proje Kurulumu

```bash
# Bağımlılıkları yükleyin
pip install -r requirements.txt

# .env dosyasını oluşturun
copy .env.example .env

# .env dosyasını düzenleyin ve bot token'ınızı ekleyin
```

`.env` dosyasını düzenleyin:
```
DISCORD_TOKEN=your_bot_token_here
BOT_PREFIX=!
MUSIC_DIR=music
PLAYLISTS_DIR=playlists

# YouTube Cookie Desteği (Bot algılamasını önlemek için - OPSİYONEL)
# Cookie dosyası otomatik olarak cookies/cookies.txt yolundan okunur
# Cookie dosyası oluşturmak için aşağıdaki komutları kullanın:
# Chrome: yt-dlp --cookies-from-browser chrome --cookies cookies/cookies.txt
# Firefox: yt-dlp --cookies-from-browser firefox --cookies cookies/cookies.txt
# Edge: yt-dlp --cookies-from-browser edge --cookies cookies/cookies.txt
# Farklı bir yol kullanmak isterseniz .env içinde:
# YOUTUBE_COOKIES_FILE=cookies/cookies.txt
```

**Not:** `MUSIC_DIR` ve `PLAYLISTS_DIR` değerleri proje dizinine göre otomatik olarak ayarlanır. Sadece klasör adını belirtmeniz yeterlidir (örn: `music`, `playlists`). Bu klasörler projenin bulunduğu dizinde otomatik olarak oluşturulur.

### 4.5. YouTube Cookie Dosyası Oluşturma (Önerilir)

YouTube bot algılaması sorunlarını önlemek için cookie dosyası oluşturmanız önerilir:

```bash
# cookies klasörü otomatik oluşturulur, ama elle de oluşturabilirsiniz
mkdir -p cookies

# Chrome'dan cookie çek
yt-dlp --cookies-from-browser chrome --cookies cookies/cookies.txt

# VEYA Firefox'tan
yt-dlp --cookies-from-browser firefox --cookies cookies/cookies.txt

# VEYA Edge'den
yt-dlp --cookies-from-browser edge --cookies cookies/cookies.txt
```

**Önemli:** 
- Cookie dosyası `cookies/` klasörüne kaydedilir ve `.gitignore`'a eklenmiştir.
- Cookie dosyasını asla GitHub'a yüklemeyin!
- Cookie dosyası otomatik olarak `cookies/cookies.txt` yolundan okunur.
- Farklı bir yol kullanmak isterseniz `.env` dosyasında `YOUTUBE_COOKIES_FILE=cookies/cookies.txt` olarak belirtebilirsiniz.

### 5. Botu Çalıştırma

```bash
python bot.py
```

## 🐳 Docker ile Çalıştırma

Docker kullanarak botu çalıştırmak için aşağıdaki adımları izleyin:

### 1. Ön Gereksinimler

- [Docker](https://docs.docker.com/get-docker/) kurulu olmalı
- [Docker Compose](https://docs.docker.com/compose/install/) kurulu olmalı

### 2. .env Dosyasını Hazırlayın

```bash
# .env dosyasını oluşturun
cp .env.example .env

# .env dosyasını düzenleyin ve bot token'ınızı ekleyin
```

### 3. Docker Compose ile Başlatma

```bash
# Botu oluştur ve başlat
docker-compose up -d --build

# Logları izle
docker-compose logs -f

# Botu durdur
docker-compose down
```

### 4. Manuel Docker Kullanımı

```bash
# Image oluştur
docker build -t eca-discord-bot .

# Container başlat
docker run -d \
  --name eca-discord-bot \
  --env-file .env \
  -v $(pwd)/music:/app/music \
  -v $(pwd)/playlists:/app/playlists \
  -v $(pwd)/cookies:/app/cookies \
  eca-discord-bot
```

**Not:** Docker kullanırken `music/`, `playlists/` ve `cookies/` klasörleri volume olarak bağlanır, böylece veriler container yeniden başlatıldığında korunur.

**Cookie Dosyası:** Cookie dosyası `cookies/` klasörüne kaydedilir ve otomatik olarak okunur. Cookie dosyası yoksa bot çalışmaya devam eder ancak YouTube bot algılaması sorunları yaşanabilir.

## ☁️ Coolify ile Deploy

Coolify kullanarak botu deploy etmek için:

### 1. Coolify'da Uygulama Oluşturma

1. Coolify dashboard'unda yeni bir uygulama oluşturun
2. GitHub repository'nizi bağlayın
3. Docker Compose veya Dockerfile kullanarak deploy edin

### 2. Cookie Dosyasını Yükleme (Coolify)

Coolify'da cookie dosyasını yüklemek için iki yöntem var:

**Yöntem 1: Coolify File Manager (Önerilen)**
1. Coolify dashboard'unda uygulamanıza gidin
2. "File Manager" veya "Storage" sekmesine gidin
3. `cookies` klasörünü oluşturun (yoksa)
4. `cookies.txt` dosyasını `cookies/` klasörüne yükleyin
5. Dosya yolu: `/app/cookies/cookies.txt` olmalı

**Yöntem 2: Persistent Volume Mount**
1. Coolify'da uygulamanızın "Volumes" ayarlarına gidin
2. Yeni bir persistent volume ekleyin:
   - **Host Path:** `/data/cookies` (veya istediğiniz bir yol)
   - **Container Path:** `/app/cookies`
3. Cookie dosyasını host path'e yükleyin
4. Container içinde `/app/cookies/cookies.txt` olarak erişilebilir olmalı

### 3. Environment Variables

Coolify'da environment variables ayarlayın:
- `DISCORD_TOKEN`: Discord bot token'ınız
- `YOUTUBE_COOKIES_FILE`: `/app/cookies/cookies.txt` (opsiyonel, otomatik algılanır)

### 3.5. Coolify Healthcheck / Port Sorunu (Önemli)

Coolify bazı kurulumlarda uygulamayı "healthy" saymak için bir **port** üzerinden cevap bekleyebilir. Bu bot normalde port açmaz.

Eğer Coolify'da uygulama "unhealthy" görünüp restart döngüsüne giriyorsa şu env'leri ekleyin:
- `ENABLE_HEALTH_SERVER=1`
- `PORT=8080` (veya Coolify'nın beklediği port)

Sonra health endpoint:
- `/health` veya `/healthz`

### 4. Cookie Dosyası Oluşturma

Cookie dosyasını yerel bilgisayarınızda oluşturup Coolify'a yükleyin:

```bash
# Yerel bilgisayarınızda
yt-dlp --cookies-from-browser chrome --cookies cookies.txt

# Sonra Coolify File Manager'dan cookies/ klasörüne yükleyin
```

**Önemli:** Cookie dosyası formatı Netscape formatında olmalı (ilk satır `# Netscape HTTP Cookie File` ile başlamalı).

## Komutlar

Bot artık Discord'un slash komut sistemini kullanıyor! Discord'da `/` yazdığınızda tüm komutları görebilirsiniz.

### Temel Komutlar

- `/join` - Botu ses kanalına çağır
- `/leave` - Botu ses kanalından çıkar
- `/play query:<dosya/link>` - Müzik çal (yerel dosya veya YouTube linki)
- `/search query:<arama> [choice:<numara>]` - YouTube'da şarkı ara ve seç (1-5 arası, choice opsiyonel)
- `/skip` - Şarkıyı geç
- `/stop` - Müziği durdur
- `/pause` - Müziği duraklat
- `/resume` - Müziği devam ettir
- `/queue` - Kuyruğu göster
- `/nowplaying` - Şu an çalan şarkıyı göster
- `/volume [vol:<0-100>]` - Ses seviyesini ayarla
- `/clear` - Kuyruğu temizle
- `/shuffle` - Kuyruğu karıştır
- `/help` - Tüm komutlar hakkında bilgi göster
- `/sync` - Slash komutlarını yeniden senkronize et (komutlar görünmüyorsa kullanın)

### Playlist Komutları

- `/playlist action:list` - Tüm playlist'leri listele
- `/playlist action:create name:<ad>` - Yeni playlist oluştur
- `/playlist_add playlist_name:<ad> song:<şarkı>` - Playlist'e şarkı ekle (dosya adı veya link)
- `/playlist_remove playlist_name:<ad> song:<şarkı>` - Playlist'ten şarkı çıkar
- `/playlist action:show name:<ad>` - Playlist'i göster
- `/playlist action:info name:<ad>` - Playlist bilgilerini göster (sahip ve editörler)
- `/playlist action:play name:<ad>` - Playlist'i çal
- `/playlist action:delete name:<ad>` - Playlist'i sil
- `/playlist_editor action:add playlist_name:<ad> user:<kullanıcı>` - Playlist'e düzenleme yetkisi ver
- `/playlist_editor action:remove playlist_name:<ad> user:<kullanıcı>` - Playlist'ten düzenleme yetkisini kaldır

## Kullanım Örnekleri

### Yerel Dosya Çalma
```
/play query:şarkı_adı.mp3
```

### YouTube'dan İndirme ve Çalma
```
/play query:https://www.youtube.com/watch?v=VIDEO_ID
```

### YouTube'da Arama ve Çalma
```
# Arama yap - sonuçlar butonlarla gösterilir
/search query:eminem lose yourself

# Butonlara tıklayarak şarkı seçebilirsiniz
# Veya eski yöntemle choice parametresi kullanabilirsiniz:
/search query:eminem lose yourself choice:2
```

**Not:** `/play` komutu sadece yerel dosya veya link kabul eder. YouTube'da arama yapmak için `/search` komutunu kullanın. Arama sonuçları butonlarla gösterilir ve tıklayarak seçim yapabilirsiniz.

### Playlist Oluşturma ve Yönetimi
```
/playlist action:create name:favorilerim
/playlist_add playlist_name:favorilerim song:şarkı1.mp3
/playlist_add playlist_name:favorilerim song:https://www.youtube.com/watch?v=VIDEO_ID
/playlist action:play name:favorilerim
```

### Playlist Yetki Yönetimi
```
# Bir kullanıcıya düzenleme yetkisi ver
/playlist_editor action:add playlist_name:favorilerim user:@kullanıcı

# Düzenleme yetkisini kaldır
/playlist_editor action:remove playlist_name:favorilerim user:@kullanıcı

# Playlist bilgilerini görüntüle
/playlist action:info name:favorilerim
```

## Klasör Yapısı

```
ECA_BOT/
├── bot.py              # Ana bot dosyası
├── music.py            # Müzik çalma modülü
├── downloader.py       # yt-dlp indirme modülü
├── playlist.py         # Playlist yönetim modülü
├── config.py           # Yapılandırma
├── requirements.txt    # Python bağımlılıkları
├── .env                # Ortam değişkenleri (oluşturulmalı)
├── .env.example        # Örnek .env dosyası
├── music/              # İndirilen müzik dosyaları (otomatik oluşturulur)
└── playlists/          # Playlist dosyaları (otomatik oluşturulur)
```

## Notlar

- Bot, müzik dosyalarını `music/` klasöründe saklar
- Playlist'ler JSON formatında `playlists/` klasöründe saklanır
- İndirilen dosyalar otomatik olarak MP3 formatına dönüştürülür
- Her sunucu için ayrı müzik kuyruğu yönetilir

## Sorun Giderme

**Slash komutlar görünmüyor:**
1. Discord Developer Portal'da `applications.commands` scope'unun işaretli olduğundan emin olun
2. Botu sunucuya yeniden ekleyin (tüm izinlerle)
3. Botu yeniden başlatın
4. `/sync` komutunu kullanarak komutları manuel olarak senkronize edin
5. Komutların görünmesi birkaç dakika sürebilir (Discord API gecikmesi)

**Bot ses kanalına bağlanamıyor:**
- FFmpeg'in kurulu olduğundan ve PATH'te olduğundan emin olun

**Müzik çalmıyor:**
- Ses dosyası formatının desteklendiğinden emin olun (MP3, WAV, OGG, M4A, FLAC)
- Bot'un ses kanalında olduğundan emin olun

**İndirme çalışmıyor:**
- yt-dlp'nin güncel olduğundan emin olun: `pip install --upgrade yt-dlp`
- İnternet bağlantınızı kontrol edin

## Lisans

Bu proje kişisel kullanım için geliştirilmiştir.

