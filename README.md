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
```

**Not:** `MUSIC_DIR` ve `PLAYLISTS_DIR` değerleri proje dizinine göre otomatik olarak ayarlanır. Sadece klasör adını belirtmeniz yeterlidir (örn: `music`, `playlists`). Bu klasörler projenin bulunduğu dizinde otomatik olarak oluşturulur.

### 5. Botu Çalıştırma

```bash
python bot.py
```

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

