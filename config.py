import os
import sys
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
    
    # YouTube cookie dosyası yolu - .env'den veya None
    YOUTUBE_COOKIES_FILE = os.getenv('YOUTUBE_COOKIES_FILE', None)

    # PO Token provider adresi (bot algılamasını hesaba gerek kalmadan aşmak için)
    POT_PROVIDER_BASE_URL = os.getenv('POT_PROVIDER_BASE_URL', 'http://pot-provider:4416')

    # OAuth2 ile YouTube hesabı girişi (varsayılan açık - private bot için kabul edilebilir)
    YOUTUBE_OAUTH2_ENABLED = os.getenv('YOUTUBE_OAUTH2_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes', 'on')


    @classmethod
    def get_cookie_file(cls):
        """Cookie dosyası yolunu dinamik olarak belirle"""
        # Önce environment variable kontrolü
        env_cookie = os.getenv('YOUTUBE_COOKIES_FILE', None)
        if env_cookie:
            if os.path.isabs(env_cookie):
                return env_cookie if os.path.exists(env_cookie) else None
            else:
                full_path = os.path.join(BASE_DIR, env_cookie)
                return full_path if os.path.exists(full_path) else None
        
        # Varsayılan yolları kontrol et
        possible_paths = [
            os.path.join(cls.COOKIES_DIR, 'cookies.txt'),
            os.path.join(BASE_DIR, 'cookies', 'cookies.txt'),
            '/app/cookies/cookies.txt',
            'cookies/cookies.txt',
        ]
        
        for path in possible_paths:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        
        return None

