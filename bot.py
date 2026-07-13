import discord
from discord import app_commands
from discord.ext import commands
import os
from typing import Optional
from music import MusicPlayer
from downloader import MusicDownloader
from playlist import PlaylistManager
from config import Config

# Bot intents ayarları
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# Bot oluştur
bot = commands.Bot(command_prefix=Config.PREFIX, intents=intents)
tree = bot.tree  # Slash komutları için

# Global müzik player ve downloader
music_players = {}
downloader = MusicDownloader()
playlist_manager = PlaylistManager()

def get_music_player(guild_id):
    """Guild için müzik player'ı al veya oluştur"""
    if guild_id not in music_players:
        music_players[guild_id] = MusicPlayer(bot)
    return music_players[guild_id]

# ========== SEARCH BUTON VIEW ==========

class SearchView(discord.ui.View):
    """YouTube arama sonuçları için buton view"""
    def __init__(self, results, interaction, downloader, timeout=60):
        super().__init__(timeout=timeout)
        self.results = results
        self.original_interaction = interaction
        self.downloader = downloader
        self.selected = None
        
        # Her sonuç için bir buton oluştur
        for i, result in enumerate(results[:5], 1):
            # Buton etiketi çok uzunsa kısalt
            label = result['title'][:80] if len(result['title']) > 80 else result['title']
            
            # Closure sorununu önlemek için factory fonksiyonu
            def make_callback(index):
                async def callback(btn_interaction):
                    await self.select_result(btn_interaction, index)
                return callback
            
            button = discord.ui.Button(
                label=f"{i}. {label}",
                style=discord.ButtonStyle.primary,
                custom_id=f"search_{i}"
            )
            button.callback = make_callback(i - 1)
            self.add_item(button)
    
    async def select_result(self, interaction: discord.Interaction, index: int):
        """Butona tıklandığında çağrılır"""
        if self.selected is not None:
            await interaction.response.send_message("❌ Zaten bir seçim yapıldı!", ephemeral=True)
            return
        
        self.selected = self.results[index]
        
        # Butonları devre dışı bırak
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(view=self)
        
        # Ses kanalı kontrolü
        if interaction.guild.voice_client is None:
            if interaction.user.voice is None:
                await interaction.followup.send("❌ Önce bir ses kanalına katılmanız gerekiyor!", ephemeral=True)
                return
            await interaction.user.voice.channel.connect()
        
        player = get_music_player(interaction.guild.id)
        
        video_url = f"https://www.youtube.com/watch?v={self.selected['id']}"
        
        # Stream (varsayılan - indirmeden çal)
        await interaction.followup.send(f"🌐 Stream hazırlanıyor: {self.selected['title']}")
        
        try:
            stream_info = await self.downloader.get_stream_url(video_url)
            
            if stream_info:
                await player.add_stream_to_queue(interaction, stream_info, interaction.user)
            else:
                await interaction.followup.send("❌ Stream alınamadı!")
        except Exception as e:
            await interaction.followup.send(f"❌ Hata: {str(e)}")
    
    async def on_timeout(self):
        """Timeout olduğunda butonları devre dışı bırak"""
        for item in self.children:
            item.disabled = True
        # View'ı güncellemek için mesajı bulmaya çalış
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except:
            pass

@bot.event
async def on_ready():
    print(f'{bot.user} olarak giriş yapıldı!')
    print(f'Bot {len(bot.guilds)} sunucuda aktif')
    try:
        # Global komutları senkronize et (tüm sunucularda görünür)
        synced = await tree.sync()
        print(f'{len(synced)} slash komutu senkronize edildi!')
        print('Komutların Discord\'da görünmesi birkaç dakika sürebilir.')
    except Exception as e:
        print(f'Slash komut senkronizasyon hatası: {e}')
        import traceback
        traceback.print_exc()

# ========== SES KANALI KOMUTLARI ==========

@tree.command(name='join', description='Botu ses kanalına çağır')
async def join(interaction: discord.Interaction):
    """Botu ses kanalına çağır"""
    if interaction.user.voice is None:
        await interaction.response.send_message("❌ Önce bir ses kanalına katılmanız gerekiyor!", ephemeral=True)
        return
    
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client is None:
        await channel.connect()
        await interaction.response.send_message(f"✅ {channel.name} kanalına katıldım!")
    else:
        await interaction.guild.voice_client.move_to(channel)
        await interaction.response.send_message(f"✅ {channel.name} kanalına taşındım!")

@tree.command(name='leave', description='Botu ses kanalından çıkar')
async def leave(interaction: discord.Interaction):
    """Botu ses kanalından çıkar"""
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("❌ Zaten hiçbir ses kanalında değilim!", ephemeral=True)
        return
    
    await interaction.guild.voice_client.disconnect()
    if interaction.guild.id in music_players:
        music_players[interaction.guild.id].cleanup()
        del music_players[interaction.guild.id]
    await interaction.response.send_message("👋 Ses kanalından ayrıldım!")

# ========== MÜZİK ÇALMA KOMUTLARI ==========

@tree.command(name='play', description='Müzik çal (dosya adı veya link - varsayılan stream)')
@app_commands.describe(query='Şarkı adı veya YouTube linki', download='True ise indir ve kaydet, False ise sadece stream (varsayılan: False)')
async def play(interaction: discord.Interaction, query: str, download: bool = False):
    """Yerel dosyadan veya linkten müzik çal (varsayılan: stream)"""
    await interaction.response.defer()
    
    if interaction.guild.voice_client is None:
        if interaction.user.voice is None:
            await interaction.followup.send("❌ Önce bir ses kanalına katılmanız gerekiyor!")
            return
        await interaction.user.voice.channel.connect()
    
    player = get_music_player(interaction.guild.id)
    
    # Link kontrolü
    if query.startswith(('http://', 'https://', 'www.')):
        if download:
            # İndir ve kaydet
            await interaction.followup.send(f"🔽 İndiriliyor: {query}")
            try:
                file_path = await downloader.download_and_save(query)
                if file_path:
                    await player.add_to_queue(interaction, file_path, interaction.user)
                    await interaction.followup.send(f"✅ Kütüphaneye kaydedildi ve kuyruğa eklendi!")
                else:
                    await interaction.followup.send("❌ İndirme başarısız oldu!")
            except Exception as e:
                await interaction.followup.send(f"❌ Hata: {str(e)}")
        else:
            # Stream (varsayılan)
            await interaction.followup.send(f"🌐 Stream hazırlanıyor: {query}")
            try:
                stream_info = await downloader.get_stream_url(query)
                if stream_info:
                    await player.add_stream_to_queue(interaction, stream_info, interaction.user)
                else:
                    await interaction.followup.send("❌ Stream alınamadı!")
            except Exception as e:
                await interaction.followup.send(f"❌ Hata: {str(e)}")
    else:
        # Önce yerel dosya kontrolü
        file_path = os.path.join(Config.MUSIC_DIR, query)
        if not os.path.exists(file_path):
            # Uzantı olmadan dene
            for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']:
                test_path = file_path + ext
                if os.path.exists(test_path):
                    file_path = test_path
                    break
            else:
                # Yerel dosya bulunamadı
                await interaction.followup.send(f"❌ Dosya bulunamadı: {query}\n💡 YouTube'da aramak için `/search query:{query}` komutunu kullanın!")
                return
        
        await player.add_to_queue(interaction, file_path, interaction.user)

@tree.command(name='search', description='YouTube\'da şarkı ara ve seç')
@app_commands.describe(query='Arama terimi', choice='Seçilecek sonuç numarası (1-5, opsiyonel - butonlar kullanılıyorsa gerekli değil)')
async def search(interaction: discord.Interaction, query: str, choice: Optional[int] = None):
    """YouTube'da şarkı ara"""
    await interaction.response.defer()
    
    await interaction.followup.send(f"🔍 Aranıyor: {query}")
    
    try:
        results = await downloader.search_youtube(query, max_results=5)
        if not results:
            await interaction.followup.send("❌ Arama sonucu bulunamadı!")
            return
        
        # Sonuçları göster
        embed = discord.Embed(
            title="🔍 Arama Sonuçları",
            description="Aşağıdaki butonlardan birini seçin:",
            color=discord.Color.blue()
        )
        
        for i, result in enumerate(results, 1):
            duration_min = result['duration'] // 60 if result.get('duration') else 0
            duration_sec = result['duration'] % 60 if result.get('duration') else 0
            embed.add_field(
                name=f"{i}. {result['title'][:256]}",
                value=f"⏱️ Süre: {duration_min}:{duration_sec:02d}",
                inline=False
            )
        
        embed.set_footer(text="Butonlar 60 saniye sonra devre dışı kalacak")
        
        # Buton view oluştur
        view = SearchView(results, interaction, downloader, timeout=60)
        
        # Mesajı gönder ve view'ı ekle
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message  # Timeout için mesaj referansı
        
        # Eğer choice parametresi verilmişse (eski yöntem, geriye dönük uyumluluk için)
        if choice is not None:
            if choice < 1 or choice > 5:
                await interaction.followup.send("❌ Seçim 1-5 arasında olmalı!", ephemeral=True)
                return
            
            if choice > len(results):
                await interaction.followup.send(f"❌ Sadece {len(results)} sonuç bulundu!", ephemeral=True)
                return
            
            selected = results[choice - 1]
            video_url = f"https://www.youtube.com/watch?v={selected['id']}"
            
            # Ses kanalı kontrolü
            if interaction.guild.voice_client is None:
                if interaction.user.voice is None:
                    await interaction.followup.send("❌ Önce bir ses kanalına katılmanız gerekiyor!")
                    return
                await interaction.user.voice.channel.connect()
            
            player = get_music_player(interaction.guild.id)
            
            # Stream (varsayılan)
            await interaction.followup.send(f"🌐 Stream hazırlanıyor: {selected['title']}")
            stream_info = await downloader.get_stream_url(video_url)
            
            if stream_info:
                await player.add_stream_to_queue(interaction, stream_info, interaction.user)
            else:
                await interaction.followup.send("❌ Stream alınamadı!")
        
    except Exception as e:
        await interaction.followup.send(f"❌ Hata: {str(e)}")
        import traceback
        traceback.print_exc()

@tree.command(name='skip', description='Şarkıyı geç')
async def skip(interaction: discord.Interaction):
    """Şarkıyı geç"""
    player = get_music_player(interaction.guild.id)
    await player.skip(interaction)

@tree.command(name='stop', description='Müziği durdur')
async def stop(interaction: discord.Interaction):
    """Müziği durdur"""
    player = get_music_player(interaction.guild.id)
    await player.stop(interaction)

@tree.command(name='pause', description='Müziği duraklat')
async def pause(interaction: discord.Interaction):
    """Müziği duraklat"""
    player = get_music_player(interaction.guild.id)
    await player.pause(interaction)

@tree.command(name='resume', description='Müziği devam ettir')
async def resume(interaction: discord.Interaction):
    """Müziği devam ettir"""
    player = get_music_player(interaction.guild.id)
    await player.resume(interaction)

@tree.command(name='queue', description='Kuyruğu göster')
async def queue(interaction: discord.Interaction):
    """Kuyruğu göster"""
    player = get_music_player(interaction.guild.id)
    await player.show_queue(interaction)

@tree.command(name='nowplaying', description='Şu an çalan şarkıyı göster')
async def nowplaying(interaction: discord.Interaction):
    """Şu an çalan şarkıyı göster"""
    player = get_music_player(interaction.guild.id)
    await player.now_playing(interaction)

@tree.command(name='volume', description='Ses seviyesini ayarla')
@app_commands.describe(vol='Ses seviyesi (0-100)')
async def volume(interaction: discord.Interaction, vol: int = None):
    """Ses seviyesini ayarla (0-100)"""
    if vol is None:
        player = get_music_player(interaction.guild.id)
        current_vol = player.get_volume()
        await interaction.response.send_message(f"🔊 Mevcut ses seviyesi: {current_vol}%")
        return
    
    if vol < 0 or vol > 100:
        await interaction.response.send_message("❌ Ses seviyesi 0-100 arasında olmalı!", ephemeral=True)
        return
    
    player = get_music_player(interaction.guild.id)
    await player.set_volume(interaction, vol / 100.0)
    await interaction.response.send_message(f"🔊 Ses seviyesi {vol}% olarak ayarlandı!")

@tree.command(name='clear', description='Kuyruğu temizle')
async def clear_queue(interaction: discord.Interaction):
    """Kuyruğu temizle"""
    player = get_music_player(interaction.guild.id)
    await player.clear_queue(interaction)

@tree.command(name='shuffle', description='Kuyruğu karıştır')
async def shuffle_queue(interaction: discord.Interaction):
    """Kuyruğu karıştır"""
    player = get_music_player(interaction.guild.id)
    await player.shuffle_queue(interaction)

@tree.command(name='help', description='Tüm komutlar hakkında bilgi göster')
async def help_command(interaction: discord.Interaction):
    """Tüm komutlar hakkında bilgi göster"""
    embed = discord.Embed(
        title="🎵 Discord Müzik Botu - Komutlar",
        description="Tüm komutlar ve kullanımları",
        color=discord.Color.blue()
    )
    
    # Ses Kanalı Komutları
    embed.add_field(
        name="🔊 Ses Kanalı Komutları",
        value=(
            "`/join` - Botu ses kanalına çağır\n"
            "`/leave` - Botu ses kanalından çıkar"
        ),
        inline=False
    )
    
    # Müzik Çalma Komutları
    embed.add_field(
        name="🎵 Müzik Çalma Komutları",
        value=(
            "`/play query:<dosya/link> [download:True]` - Yerel dosya veya link çal (varsayılan: stream)\n"
            "`/search query:<arama>` - YouTube'da ara ve stream et\n"
            "`/skip` - Şarkıyı geç\n"
            "`/stop` - Müziği durdur\n"
            "`/pause` - Müziği duraklat\n"
            "`/resume` - Müziği devam ettir\n"
            "`/queue` - Kuyruğu göster\n"
            "`/nowplaying` - Şu an çalan şarkıyı göster\n"
            "`/volume [vol:<0-100>]` - Ses seviyesini ayarla\n"
            "`/clear` - Kuyruğu temizle\n"
            "`/shuffle` - Kuyruğu karıştır"
        ),
        inline=False
    )
    
    # Playlist Komutları
    embed.add_field(
        name="📋 Playlist Komutları",
        value=(
            "`/playlist action:list` - Tüm playlist'leri listele\n"
            "`/playlist action:create name:<ad>` - Yeni playlist oluştur\n"
            "`/playlist_add playlist_name:<ad> song:<şarkı/link>` - Playlist'e şarkı ekle\n"
            "`/playlist_remove playlist_name:<ad> song:<şarkı>` - Playlist'ten şarkı çıkar\n"
            "`/playlist action:show name:<ad>` - Playlist'i göster\n"
            "`/playlist action:info name:<ad>` - Playlist bilgilerini göster\n"
            "`/playlist action:play name:<ad>` - Playlist'i çal\n"
            "`/playlist action:delete name:<ad>` - Playlist'i sil\n"
            "`/playlist_editor action:add playlist_name:<ad> user:<kullanıcı>` - Düzenleme yetkisi ver\n"
            "`/playlist_editor action:remove playlist_name:<ad> user:<kullanıcı>` - Düzenleme yetkisini kaldır"
        ),
        inline=False
    )
    
    # Yardımcı Komutlar
    embed.add_field(
        name="🛠️ Yardımcı Komutlar",
        value=(
            "`/help` - Bu yardım mesajını göster\n"
            "`/sync` - Slash komutlarını yeniden senkronize et"
        ),
        inline=False
    )
    
    # Kullanım Örnekleri
    embed.add_field(
        name="📖 Kullanım Örnekleri",
        value=(
            "```\n"
            "/play query:şarkı.mp3\n"
            "/play query:https://youtube.com/watch?v=...\n"
            "/search query:eminem lose yourself\n"
            "/search query:eminem lose yourself choice:2\n"
            "/playlist action:create name:favorilerim\n"
            "/playlist_add playlist_name:favorilerim song:şarkı.mp3\n"
            "```"
        ),
        inline=False
    )
    
    embed.set_footer(text="Bot geliştirildi: ECA_BOT")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name='sync', description='Slash komutlarını yeniden senkronize et (sadece bot sahibi)')
async def sync_commands(interaction: discord.Interaction):
    """Slash komutlarını yeniden senkronize et"""
    # Bot sahibi kontrolü (isteğe bağlı - kaldırabilirsiniz)
    # if interaction.user.id != YOUR_USER_ID:
    #     await interaction.response.send_message("❌ Bu komutu sadece bot sahibi kullanabilir!", ephemeral=True)
    #     return
    
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await tree.sync()
        await interaction.followup.send(f"✅ {len(synced)} slash komutu senkronize edildi! Komutların görünmesi birkaç dakika sürebilir.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Hata: {str(e)}", ephemeral=True)

# ========== PLAYLIST KOMUTLARI ==========

@tree.command(name='playlist', description='Playlist yönetimi')
@app_commands.describe(action='İşlem türü', name='Playlist adı')
@app_commands.choices(action=[
    app_commands.Choice(name='list', value='list'),
    app_commands.Choice(name='create', value='create'),
    app_commands.Choice(name='show', value='show'),
    app_commands.Choice(name='info', value='info'),
    app_commands.Choice(name='play', value='play'),
    app_commands.Choice(name='delete', value='delete'),
])
async def playlist_command(interaction: discord.Interaction, action: str, name: str = None):
    """Playlist yönetimi"""
    await interaction.response.defer()
    
    if action == 'list':
        await playlist_manager.list_playlists(interaction)
        return
    
    if name is None:
        await interaction.followup.send("❌ Lütfen bir playlist adı belirtin!")
        return
    
    if action == 'create':
        await playlist_manager.create_playlist(interaction, name)
    elif action == 'show':
        await playlist_manager.show_playlist(interaction, name)
    elif action == 'info':
        await playlist_manager.show_playlist_info(interaction, name)
    elif action == 'play':
        await playlist_manager.play_playlist(interaction, name, get_music_player(interaction.guild.id))
    elif action == 'delete':
        await playlist_manager.delete_playlist(interaction, name)
    else:
        await interaction.followup.send("❌ Geçersiz işlem!")

@tree.command(name='playlist_add', description='Playlist\'e şarkı ekle')
@app_commands.describe(playlist_name='Playlist adı', song='Şarkı adı veya link')
async def playlist_add(interaction: discord.Interaction, playlist_name: str, song: str):
    """Playlist'e şarkı ekle"""
    await interaction.response.defer()
    await playlist_manager.add_to_playlist(interaction, playlist_name, song, downloader)

@tree.command(name='playlist_remove', description='Playlist\'ten şarkı çıkar')
@app_commands.describe(playlist_name='Playlist adı', song='Şarkı adı')
async def playlist_remove(interaction: discord.Interaction, playlist_name: str, song: str):
    """Playlist'ten şarkı çıkar"""
    await interaction.response.defer()
    await playlist_manager.remove_from_playlist(interaction, playlist_name, song)

@tree.command(name='playlist_editor', description='Playlist düzenleme yetkisi yönetimi')
@app_commands.describe(action='İşlem türü', playlist_name='Playlist adı', user='Kullanıcı')
@app_commands.choices(action=[
    app_commands.Choice(name='add', value='add'),
    app_commands.Choice(name='remove', value='remove'),
])
async def playlist_editor(interaction: discord.Interaction, action: str, playlist_name: str, user: discord.User):
    """Playlist düzenleme yetkisi yönetimi"""
    await interaction.response.defer()
    
    if action == 'add':
        await playlist_manager.add_editor(interaction, playlist_name, user)
    elif action == 'remove':
        await playlist_manager.remove_editor(interaction, playlist_name, user)
    else:
        await interaction.followup.send("❌ Geçersiz işlem! 'add' veya 'remove' kullanın.")

# Botu çalıştır
if __name__ == '__main__':
    if not Config.TOKEN:
        print("❌ DISCORD_TOKEN bulunamadı. Coolify -> Environment Variables bölümüne DISCORD_TOKEN ekleyin.", flush=True)
        raise SystemExit(1)

    @bot.event
    async def setup_hook():
        mode = Config.web_http_mode()
        if mode == 'off':
            print("ℹ️ Web/health HTTP kapalı (WEB_UI_TOKEN veya ENABLE_HEALTH_SERVER yok)", flush=True)
            return
        from web.app import create_app, start_web_server
        from web.auth import create_session_secret
        full = mode == 'full'
        app = create_app(bot=bot, full_ui=full)
        app.state.web_token = Config.WEB_UI_TOKEN
        app.state.session_secret = create_session_secret(Config.WEB_UI_SESSION_SECRET)
        port = Config.web_port()
        bot.loop.create_task(start_web_server(app, port=port))
        print(f"✅ HTTP sunucu ({mode}): http://0.0.0.0:{port}/health", flush=True)

    bot.run(Config.TOKEN)
