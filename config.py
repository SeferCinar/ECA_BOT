import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Proje kök dizinini bul (bu dosyanın bulunduğu dizin)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    # Discord Bot Token
    TOKEN = os.getenv('DISCORD_TOKEN', '')
    
    # Bot prefix
    PREFIX = os.getenv('BOT_PREFIX', '!')
    
    # Müzik dosyalarının saklanacağı klasör (proje dizinine göre)
    MUSIC_DIR = os.path.join(BASE_DIR, os.getenv('MUSIC_DIR', 'music'))
    
    # Playlist dosyalarının saklanacağı klasör (proje dizinine göre)
    PLAYLISTS_DIR = os.path.join(BASE_DIR, os.getenv('PLAYLISTS_DIR', 'playlists'))
    
    # Cookie dosyalarının saklanacağı klasör (proje dizinine göre)
    COOKIES_DIR = os.path.join(BASE_DIR, 'cookies')
    
    # YouTube cookie dosyası yolu (opsiyonel - bot algılamasını önlemek için)
    # Cookie dosyasını yt-dlp ile export edebilirsiniz: yt-dlp --cookies-from-browser chrome --cookies cookies/cookies.txt
    YOUTUBE_COOKIES_FILE = os.getenv('YOUTUBE_COOKIES_FILE', None)
    
    # Cookie dosyası yolunu işle
    if YOUTUBE_COOKIES_FILE is None:
        # Varsayılan olarak cookies/cookies.txt kullan
        default_cookie_path = os.path.join(COOKIES_DIR, 'cookies.txt')
        if os.path.exists(default_cookie_path):
            YOUTUBE_COOKIES_FILE = default_cookie_path
    elif not os.path.isabs(YOUTUBE_COOKIES_FILE):
        # Relative path ise BASE_DIR'e göre çöz
        YOUTUBE_COOKIES_FILE = os.path.join(BASE_DIR, YOUTUBE_COOKIES_FILE)
    
    # Browser'dan cookie çekme (chrome, firefox, edge, safari, opera, brave, vivaldi)
    # Eğer YOUTUBE_COOKIES_FILE belirtilmemişse, bu browser'dan cookie çekmeyi dener
    YOUTUBE_COOKIES_BROWSER = os.getenv('YOUTUBE_COOKIES_BROWSER', None)

