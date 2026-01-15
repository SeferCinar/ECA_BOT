import yt_dlp
import os
import asyncio
from config import Config

class MusicDownloader:
    def __init__(self):
        self.output_dir = Config.MUSIC_DIR
        os.makedirs(self.output_dir, exist_ok=True)
        
        # yt-dlp ayarları
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
        }
    
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
                'max_downloads': max_results
            }
            
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

