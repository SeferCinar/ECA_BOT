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

