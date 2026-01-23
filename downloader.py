import yt_dlp
import os
import sys
import asyncio
from config import Config

class MusicDownloader:
    def __init__(self):
        self.output_dir = Config.MUSIC_DIR
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Cookie klasörünü oluştur
        cookies_dir = Config.COOKIES_DIR
        os.makedirs(cookies_dir, exist_ok=True)
        
        # Cookie dosyası yolunu belirle
        self.cookie_file = self._find_cookie_file()
        
        # yt-dlp ayarları - YouTube bot algılamasını önlemek için özel ayarlar
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.output_dir, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'no_warnings': False,
            # YouTube bot algılamasını atlamak için
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],  # Android client kullan
                    'player_skip': ['webpage', 'configs'],  # Gereksiz istekleri atla
                }
            },
            # Gerçek tarayıcı gibi görünmek için
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            'socket_timeout': 30,
            'retries': 3,
        }
        
        # Cookie desteği ekle (bot algılamasını önlemek için)
        self._add_cookie_support()
    
    def _find_cookie_file(self):
        """Cookie dosyasını bul"""
        print("=" * 50, flush=True)
        print("🔍 Cookie dosyası aranıyor...", flush=True)
        
        # Olası yolları kontrol et
        possible_paths = [
            os.getenv('YOUTUBE_COOKIES_FILE', ''),
            os.path.join(Config.COOKIES_DIR, 'cookies.txt'),
            '/app/cookies/cookies.txt',
            'cookies/cookies.txt',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies', 'cookies.txt'),
        ]
        
        for path in possible_paths:
            if not path:
                continue
            print(f"🔍 Kontrol ediliyor: {path}", flush=True)
            if os.path.exists(path):
                size = os.path.getsize(path)
                print(f"   ✅ Dosya bulundu! Boyut: {size} bytes", flush=True)
                if size > 0:
                    # İlk satırı kontrol et
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            first_line = f.readline().strip()
                            print(f"   📄 İlk satır: {first_line[:60]}", flush=True)
                    except Exception as e:
                        print(f"   ⚠️  Dosya okunamadı: {e}", flush=True)
                    print("=" * 50, flush=True)
                    return path
            else:
                print(f"   ❌ Dosya bulunamadı", flush=True)
        
        print("⚠️  Hiçbir cookie dosyası bulunamadı!", flush=True)
        print("=" * 50, flush=True)
        return None
    
    def _add_cookie_support(self):
        """Cookie desteği ekle - YouTube bot algılamasını önlemek için"""
        if self.cookie_file:
            self.ydl_opts['cookiefile'] = self.cookie_file
            print(f"✅ Cookie dosyası yüklendi: {self.cookie_file}", flush=True)
        else:
            print("⚠️  Cookie dosyası yüklenemedi. YouTube bot algılaması sorunları yaşanabilir.", flush=True)
            print(f"💡 Cookie dosyası yolu: {Config.COOKIES_DIR}/cookies.txt", flush=True)
    
    async def download_and_save(self, url):
        """URL'den müzik indir ve kaydet"""
        try:
            # yt-dlp işlemini async olarak çalıştır
            loop = asyncio.get_event_loop()
            file_path = await loop.run_in_executor(
                None,
                self._download_sync,
                url
            )
            return file_path
        except Exception as e:
            print(f"İndirme hatası: {e}")
            raise
    
    async def get_stream_url(self, url):
        """URL'den stream bilgisi al (indirmeden)"""
        try:
            loop = asyncio.get_event_loop()
            stream_info = await loop.run_in_executor(
                None,
                self._get_stream_sync,
                url
            )
            return stream_info
        except Exception as e:
            print(f"Stream hatası: {e}")
            raise
    
    def _get_stream_sync(self, url):
        """Senkron stream URL alma fonksiyonu"""
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                # YouTube bot algılamasını atlamak için
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['webpage', 'configs'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                },
            }
            # Cookie desteği ekle
            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                print(f"🔐 Stream için cookie kullanılıyor: {self.cookie_file}", flush=True)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # En iyi ses formatını bul
                if 'url' in info:
                    stream_url = info['url']
                elif 'formats' in info:
                    # En iyi ses formatını seç
                    audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none']
                    if audio_formats:
                        best_audio = max(audio_formats, key=lambda f: f.get('abr', 0) or 0)
                        stream_url = best_audio['url']
                    else:
                        stream_url = info['formats'][-1]['url']
                else:
                    return None
                
                return {
                    'url': stream_url,
                    'title': info.get('title', 'Bilinmeyen'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'webpage_url': info.get('webpage_url', url)
                }
        except Exception as e:
            print(f"Stream hatası: {e}")
            raise
    
    def _download_sync(self, url):
        """Senkron indirme fonksiyonu"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                # Video bilgilerini al
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'unknown')
                
                # Dosya adını temizle (geçersiz karakterleri kaldır)
                safe_title = self._sanitize_filename(title)
                output_path = os.path.join(
                    self.output_dir,
                    f"{safe_title}.mp3"
                )
                
                # Eğer dosya zaten varsa, yeni indirme yapma
                if os.path.exists(output_path):
                    print(f"Dosya zaten mevcut: {output_path}")
                    return output_path
                
                # İndir
                ydl.download([url])
                
                # İndirilen dosyayı bul (uzantı farklı olabilir)
                for file in os.listdir(self.output_dir):
                    if safe_title in file:
                        return os.path.join(self.output_dir, file)
                
                # Eğer bulunamazsa, en son değiştirilen dosyayı al
                files = [
                    os.path.join(self.output_dir, f)
                    for f in os.listdir(self.output_dir)
                    if os.path.isfile(os.path.join(self.output_dir, f))
                ]
                if files:
                    return max(files, key=os.path.getmtime)
                
                return None
        except Exception as e:
            print(f"İndirme hatası: {e}")
            raise
    
    async def search_youtube(self, query, max_results=5):
        """YouTube'da şarkı ara"""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                self._search_sync,
                query,
                max_results
            )
            return results
        except Exception as e:
            print(f"Arama hatası: {e}")
            raise
    
    def _search_sync(self, query, max_results):
        """Senkron arama fonksiyonu"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'default_search': 'ytsearch',
                'max_downloads': max_results,
                # YouTube bot algılamasını atlamak için
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['webpage', 'configs'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                },
            }
            # Cookie desteği ekle
            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                print(f"🔐 Arama için cookie kullanılıyor: {self.cookie_file}", flush=True)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Arama yap
                search_query = f"ytsearch{max_results}:{query}"
                results = ydl.extract_info(search_query, download=False)
                
                if not results or 'entries' not in results:
                    return []
                
                formatted_results = []
                for entry in results['entries']:
                    if entry:
                        formatted_results.append({
                            'title': entry.get('title', 'Bilinmeyen'),
                            'url': entry.get('url', ''),
                            'duration': entry.get('duration', 0),
                            'id': entry.get('id', '')
                        })
                
                return formatted_results
        except Exception as e:
            print(f"Arama hatası: {e}")
            return []
    
    def _sanitize_filename(self, filename):
        """Dosya adındaki geçersiz karakterleri temizle"""
        import re
        # Windows'ta geçersiz karakterler: < > : " / \ | ? *
        invalid_chars = r'[<>:"/\\|?*]'
        filename = re.sub(invalid_chars, '_', filename)
        # Başta ve sonda nokta ve boşluk olmamalı
        filename = filename.strip('. ')
        # Çok uzun dosya adlarını kısalt
        if len(filename) > 200:
            filename = filename[:200]
        return filename

