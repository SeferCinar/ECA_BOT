import discord
import json
import os
from config import Config

class PlaylistManager:
    def __init__(self):
        self.playlists_dir = Config.PLAYLISTS_DIR
        os.makedirs(self.playlists_dir, exist_ok=True)
    
    def _send_message(self, interaction, message, ephemeral=False):
        """Mesaj gönder (hem interaction hem de ctx destekler)"""
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            return interaction.response.send_message(message, ephemeral=ephemeral)
        elif hasattr(interaction, 'followup'):
            return interaction.followup.send(message, ephemeral=ephemeral)
        else:
            return interaction.send(message)
    
    def _get_author(self, interaction):
        """Interaction'dan author al"""
        if hasattr(interaction, 'user'):
            return interaction.user
        return interaction.author
    
    def _get_playlist_path(self, name):
        """Playlist dosya yolunu al"""
        safe_name = self._sanitize_filename(name)
        return os.path.join(self.playlists_dir, f"{safe_name}.json")
    
    def _sanitize_filename(self, filename):
        """Dosya adındaki geçersiz karakterleri temizle"""
        import re
        invalid_chars = r'[<>:"/\\|?*]'
        filename = re.sub(invalid_chars, '_', filename)
        filename = filename.strip('. ')
        return filename
    
    def _load_playlist(self, name):
        """Playlist'i yükle"""
        path = self._get_playlist_path(name)
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Playlist yükleme hatası: {e}")
            return None
    
    def _save_playlist(self, name, playlist_data):
        """Playlist'i kaydet"""
        path = self._get_playlist_path(name)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(playlist_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Playlist kaydetme hatası: {e}")
            return False
    
    async def create_playlist(self, interaction, name):
        """Yeni playlist oluştur"""
        path = self._get_playlist_path(name)
        if os.path.exists(path):
            await self._send_message(interaction, f"❌ **{name}** adında bir playlist zaten var!")
            return
        
        author = self._get_author(interaction)
        playlist_data = {
            'name': name,
            'owner': str(author.id),
            'editors': [],  # Düzenleme yetkisi olan kullanıcılar
            'songs': []
        }
        
        if self._save_playlist(name, playlist_data):
            await self._send_message(interaction, f"✅ **{name}** playlist'i oluşturuldu!")
        else:
            await self._send_message(interaction, "❌ Playlist oluşturulurken bir hata oluştu!")
    
    def _can_edit(self, playlist, user_id):
        """Kullanıcının playlist'i düzenleyip düzenleyemeyeceğini kontrol et"""
        user_id_str = str(user_id)
        return (playlist['owner'] == user_id_str or 
                user_id_str in playlist.get('editors', []))
    
    async def add_to_playlist(self, interaction, playlist_name, song_input, downloader=None):
        """Playlist'e şarkı ekle (dosya adı veya link)"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await self._send_message(interaction, f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        # Yetki kontrolü
        author = self._get_author(interaction)
        if not self._can_edit(playlist, author.id):
            await self._send_message(interaction, "❌ Bu playlist'i düzenleme yetkiniz yok!")
            return
        
        song_path = None
        
        # Link kontrolü
        if song_input.startswith(('http://', 'https://', 'www.')):
            if downloader is None:
                await self._send_message(interaction, "❌ Link indirmek için downloader gerekli!")
                return
            
            await self._send_message(interaction, f"🔽 İndiriliyor: {song_input}")
            try:
                song_path = await downloader.download_and_save(song_input)
                if not song_path:
                    await self._send_message(interaction, "❌ İndirme başarısız oldu!")
                    return
            except Exception as e:
                await self._send_message(interaction, f"❌ İndirme hatası: {str(e)}")
                return
        else:
            # Yerel dosya kontrolü
            from config import Config
            import os
            
            full_path = os.path.join(Config.MUSIC_DIR, song_input)
            
            # Tam yol veya uzantılı dene
            if os.path.exists(full_path):
                song_path = full_path
            else:
                # Uzantı olmadan dene
                for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']:
                    test_path = full_path + ext
                    if os.path.exists(test_path):
                        song_path = test_path
                        break
            
            if song_path is None:
                await self._send_message(interaction, f"❌ Şarkı bulunamadı: {song_input}")
                return
        
        # Şarkı zaten listede mi kontrol et
        if song_path in playlist['songs']:
            await self._send_message(interaction, f"❌ Bu şarkı zaten playlist'te!")
            return
        
        playlist['songs'].append(song_path)
        
        if self._save_playlist(playlist_name, playlist):
            await self._send_message(interaction, f"✅ **{os.path.basename(song_path)}** playlist'e eklendi!")
        else:
            await self._send_message(interaction, "❌ Şarkı eklenirken bir hata oluştu!")
    
    async def remove_from_playlist(self, interaction, playlist_name, song_name):
        """Playlist'ten şarkı çıkar"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await self._send_message(interaction, f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        # Yetki kontrolü
        author = self._get_author(interaction)
        if not self._can_edit(playlist, author.id):
            await self._send_message(interaction, "❌ Bu playlist'i düzenleme yetkiniz yok!")
            return
        
        # Şarkıyı bul ve çıkar
        removed = False
        for song in playlist['songs'][:]:
            if song_name.lower() in os.path.basename(song).lower():
                playlist['songs'].remove(song)
                removed = True
                break
        
        if not removed:
            await ctx.send(f"❌ Şarkı playlist'te bulunamadı!")
            return
        
        if self._save_playlist(playlist_name, playlist):
            await ctx.send(f"✅ Şarkı playlist'ten çıkarıldı!")
        else:
            await ctx.send("❌ Şarkı çıkarılırken bir hata oluştu!")
    
    async def show_playlist(self, ctx, playlist_name):
        """Playlist'i göster"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await ctx.send(f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        if len(playlist['songs']) == 0:
            await ctx.send(f"📭 **{playlist_name}** playlist'i boş!")
            return
        
        songs_list = [f"**{playlist_name}** - {len(playlist['songs'])} şarkı\n"]
        for i, song_path in enumerate(playlist['songs'][:20], 1):
            song_name = os.path.basename(song_path)
            songs_list.append(f"{i}. {song_name}")
        
        if len(playlist['songs']) > 20:
            songs_list.append(f"\n... ve {len(playlist['songs']) - 20} şarkı daha")
        
        await ctx.send("\n".join(songs_list))
    
    async def play_playlist(self, ctx, playlist_name, music_player):
        """Playlist'i çal"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await ctx.send(f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        if len(playlist['songs']) == 0:
            await ctx.send(f"❌ **{playlist_name}** playlist'i boş!")
            return
        
        # Ses kanalı kontrolü
        if ctx.voice_client is None:
            if ctx.author.voice is None:
                await ctx.send("❌ Önce bir ses kanalına katılmanız gerekiyor!")
                return
            await ctx.author.voice.channel.connect()
        
        # Tüm şarkıları kuyruğa ekle
        added_count = 0
        for song_path in playlist['songs']:
            if os.path.exists(song_path):
                await music_player.add_to_queue(ctx, song_path, ctx.author)
                added_count += 1
        
        await ctx.send(f"✅ **{playlist_name}** playlist'inden {added_count} şarkı kuyruğa eklendi!")
    
    async def add_editor(self, ctx, playlist_name, user):
        """Playlist'e düzenleme yetkisi ver"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await ctx.send(f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        # Sadece sahip yetki verebilir
        if playlist['owner'] != str(ctx.author.id):
            await ctx.send("❌ Bu playlist'in sahibi değilsiniz!")
            return
        
        user_id_str = str(user.id)
        
        # Zaten sahip mi kontrol et
        if playlist['owner'] == user_id_str:
            await self._send_message(interaction, "❌ Bu kullanıcı zaten playlist'in sahibi!")
            return
        
        # Zaten editor mü kontrol et
        if 'editors' not in playlist:
            playlist['editors'] = []
        
        if user_id_str in playlist['editors']:
            await self._send_message(interaction, f"❌ {user.mention} zaten bu playlist'i düzenleyebiliyor!")
            return
        
        playlist['editors'].append(user_id_str)
        
        if self._save_playlist(playlist_name, playlist):
            await self._send_message(interaction, f"✅ {user.mention} artık **{playlist_name}** playlist'ini düzenleyebilir!")
        else:
            await self._send_message(interaction, "❌ Yetki verilirken bir hata oluştu!")
    
    async def remove_editor(self, interaction, playlist_name, user):
        """Playlist'ten düzenleme yetkisini kaldır"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await self._send_message(interaction, f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        # Sadece sahip yetki kaldırabilir
        author = self._get_author(interaction)
        if playlist['owner'] != str(author.id):
            await self._send_message(interaction, "❌ Bu playlist'in sahibi değilsiniz!")
            return
        
        user_id_str = str(user.id)
        
        if 'editors' not in playlist or user_id_str not in playlist['editors']:
            await self._send_message(interaction, f"❌ {user.mention} bu playlist'i düzenleme yetkisine sahip değil!")
            return
        
        playlist['editors'].remove(user_id_str)
        
        if self._save_playlist(playlist_name, playlist):
            await self._send_message(interaction, f"✅ {user.mention}'ın **{playlist_name}** playlist'i düzenleme yetkisi kaldırıldı!")
        else:
            await self._send_message(interaction, "❌ Yetki kaldırılırken bir hata oluştu!")
    
    async def delete_playlist(self, ctx, playlist_name):
        """Playlist'i sil"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await ctx.send(f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        # Sadece sahip silebilir
        if playlist['owner'] != str(ctx.author.id):
            await ctx.send("❌ Bu playlist'i sadece sahibi silebilir!")
            return
        
        path = self._get_playlist_path(playlist_name)
        try:
            os.remove(path)
            await ctx.send(f"✅ **{playlist_name}** playlist'i silindi!")
        except Exception as e:
            await ctx.send(f"❌ Playlist silinirken bir hata oluştu: {e}")
    
    async def list_playlists(self, interaction):
        """Tüm playlist'leri listele"""
        playlists = []
        for file in os.listdir(self.playlists_dir):
            if file.endswith('.json'):
                playlist_name = file[:-5]  # .json uzantısını kaldır
                playlist = self._load_playlist(playlist_name)
                if playlist:
                    song_count = len(playlist['songs'])
                    owner_mention = f"<@{playlist['owner']}>"
                    editor_count = len(playlist.get('editors', []))
                    editor_text = f", {editor_count} editör" if editor_count > 0 else ""
                    playlists.append(f"• **{playlist_name}** - {song_count} şarkı (Sahip: {owner_mention}{editor_text})")
        
        if len(playlists) == 0:
            await self._send_message(interaction, "📭 Henüz hiç playlist oluşturulmamış!")
            return
        
        await self._send_message(interaction, "📋 **Playlist'ler:**\n" + "\n".join(playlists))
    
    async def show_playlist_info(self, interaction, playlist_name):
        """Playlist bilgilerini göster (sahip ve editörler dahil)"""
        playlist = self._load_playlist(playlist_name)
        if playlist is None:
            await self._send_message(interaction, f"❌ **{playlist_name}** adında bir playlist bulunamadı!")
            return
        
        owner_mention = f"<@{playlist['owner']}>"
        editors = playlist.get('editors', [])
        editor_mentions = [f"<@{eid}>" for eid in editors] if editors else ["Yok"]
        
        info = [
            f"**{playlist_name}** Playlist Bilgileri",
            f"👤 Sahip: {owner_mention}",
            f"✏️ Editörler: {', '.join(editor_mentions)}",
            f"🎵 Şarkı Sayısı: {len(playlist['songs'])}"
        ]
        
        await self._send_message(interaction, "\n".join(info))

