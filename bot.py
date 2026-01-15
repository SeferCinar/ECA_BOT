import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
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

@tree.command(name='play', description='Müzik çal (dosya adı, link veya arama)')
@app_commands.describe(query='Şarkı adı, YouTube linki veya arama terimi')
async def play(interaction: discord.Interaction, query: str):
    """Yerel dosyadan, linkten veya aramadan müzik çal"""
    await interaction.response.defer()
    
    if interaction.guild.voice_client is None:
        if interaction.user.voice is None:
            await interaction.followup.send("❌ Önce bir ses kanalına katılmanız gerekiyor!")
            return
        await interaction.user.voice.channel.connect()
    
    player = get_music_player(interaction.guild.id)
    
    # Link kontrolü
    if query.startswith(('http://', 'https://', 'www.')):
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
                # Yerel dosya bulunamadı, YouTube'da ara
                await interaction.followup.send(f"🔍 YouTube'da aranıyor: {query}")
                try:
                    results = await downloader.search_youtube(query, max_results=5)
                    if not results:
                        await interaction.followup.send("❌ Arama sonucu bulunamadı!")
                        return
                    
                    # İlk sonucu seç
                    first_result = results[0]
                    video_url = f"https://www.youtube.com/watch?v={first_result['id']}"
                    await interaction.followup.send(f"🔽 İndiriliyor: {first_result['title']}")
                    
                    file_path = await downloader.download_and_save(video_url)
                    if file_path:
                        await player.add_to_queue(interaction, file_path, interaction.user)
                        await interaction.followup.send(f"✅ **{first_result['title']}** kütüphaneye kaydedildi ve kuyruğa eklendi!")
                    else:
                        await interaction.followup.send("❌ İndirme başarısız oldu!")
                except Exception as e:
                    await interaction.followup.send(f"❌ Hata: {str(e)}")
                return
        
        await player.add_to_queue(interaction, file_path, interaction.user)

@tree.command(name='search', description='YouTube\'da şarkı ara ve seç')
@app_commands.describe(query='Arama terimi', choice='Seçilecek sonuç numarası (1-5)')
async def search(interaction: discord.Interaction, query: str, choice: int = 1):
    """YouTube'da şarkı ara"""
    await interaction.response.defer()
    
    if choice < 1 or choice > 5:
        await interaction.followup.send("❌ Seçim 1-5 arasında olmalı!", ephemeral=True)
        return
    
    await interaction.followup.send(f"🔍 Aranıyor: {query}")
    
    try:
        results = await downloader.search_youtube(query, max_results=5)
        if not results:
            await interaction.followup.send("❌ Arama sonucu bulunamadı!")
            return
        
        # Sonuçları göster
        results_text = "🔍 **Arama Sonuçları:**\n"
        for i, result in enumerate(results, 1):
            marker = "✅" if i == choice else f"{i}."
            duration_min = result['duration'] // 60
            duration_sec = result['duration'] % 60
            results_text += f"{marker} {result['title']} ({duration_min}:{duration_sec:02d})\n"
        
        await interaction.followup.send(results_text)
        
        if choice > len(results):
            await interaction.followup.send(f"❌ Sadece {len(results)} sonuç bulundu!")
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
        
        await interaction.followup.send(f"🔽 İndiriliyor: {selected['title']}")
        file_path = await downloader.download_and_save(video_url)
        
        if file_path:
            await player.add_to_queue(interaction, file_path, interaction.user)
            await interaction.followup.send(f"✅ **{selected['title']}** kütüphaneye kaydedildi ve kuyruğa eklendi!")
        else:
            await interaction.followup.send("❌ İndirme başarısız oldu!")
        
    except Exception as e:
        await interaction.followup.send(f"❌ Hata: {str(e)}")

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
    bot.run(Config.TOKEN)
