import discord
from discord.ext import commands
import asyncio
import yt_dlp
from collections import deque
import re
import os
import json

# Bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Müzik çalar sınıfı
class MusicPlayer:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.voice_client = None
        self.volume = 0.5
        self.loop_mode = "off"  # "off", "song", "queue"
        
    def add_to_queue(self, song):
        self.queue.append(song)
    
    def skip(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
    
    def clear_queue(self):
        self.queue.clear()
    
    def get_queue(self):
        return list(self.queue)

# Sunucu bazlı müzik çalarlar
music_players = {}

def get_player(guild_id):
    if guild_id not in music_players:
        music_players[guild_id] = MusicPlayer()
    return music_players[guild_id]

# Çalma listesi sistemi
PLAYLISTS_FILE = "playlists.json"

def load_playlists():
    """Çalma listelerini yükle"""
    try:
        if os.path.exists(PLAYLISTS_FILE):
            with open(PLAYLISTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Çalma listesi yükleme hatası: {e}")
    return {}

def save_playlists(playlists):
    """Çalma listelerini kaydet"""
    try:
        with open(PLAYLISTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(playlists, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Çalma listesi kaydetme hatası: {e}")
        return False

# Çalma listelerini yükle
user_playlists = load_playlists()

# YouTube indirme ayarları
ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    'nocheckcertificate': True,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

async def search_youtube(query):
    """YouTube'da arama yap"""
    ydl_opts_search = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch5',
        'extract_flat': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False)
            )
            if 'entries' in info:
                return info['entries']
        except Exception as e:
            print(f"Arama hatası: {e}")
            return None

async def get_video_info(url_or_query):
    """Video bilgilerini al"""
    ydl_opts_custom = ydl_opts.copy()
    ydl_opts_custom.update({
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    with yt_dlp.YoutubeDL(ydl_opts_custom) as ydl:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url_or_query, download=False)
            )
            
            if 'entries' in info:
                info = info['entries'][0]
            
            return {
                'url': info['url'],
                'title': info.get('title', 'Bilinmeyen'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'webpage_url': info.get('webpage_url', '')
            }
        except Exception as e:
            print(f"Video bilgisi alma hatası: {e}")
            return None

def format_duration(seconds):
    """Saniyeyi dakika:saniye formatına çevir"""
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{int(hours)}:{int(mins):02d}:{int(secs):02d}"
    return f"{int(mins)}:{int(secs):02d}"

async def play_next(ctx, player):
    """Sıradaki şarkıyı çal"""
    # Loop song mode - aynı şarkıyı tekrar çal
    if player.loop_mode == "song" and player.current:
        song = player.current
    # Loop queue mode - şarkıyı kuyruğun sonuna ekle
    elif player.loop_mode == "queue" and player.current:
        player.queue.append(player.current)
        if len(player.queue) == 0:
            player.current = None
            await ctx.send("✅ Çalma listesi bitti!")
            return
        song = player.queue.popleft()
        player.current = song
    # Normal mode
    else:
        if len(player.queue) == 0:
            player.current = None
            await ctx.send("✅ Çalma listesi bitti!")
            return
        song = player.queue.popleft()
        player.current = song
    
    def after_playing(error):
        if error:
            print(f"Çalma hatası: {error}")
        
        coro = play_next(ctx, player)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Sonraki şarkı hatası: {e}")
    
    try:
        audio_source = discord.FFmpegPCMAudio(song['url'], **ffmpeg_options)
        audio_source = discord.PCMVolumeTransformer(audio_source, volume=player.volume)
        player.voice_client.play(audio_source, after=after_playing)
        
        embed = discord.Embed(
            title="🎵 Şimdi Çalıyor",
            description=f"[{song['title']}]({song['webpage_url']})",
            color=discord.Color.green()
        )
        embed.add_field(name="Süre", value=format_duration(song['duration']))
        if song['thumbnail']:
            embed.set_thumbnail(url=song['thumbnail'])
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Çalma hatası: {str(e)}")
        await play_next(ctx, player)

@bot.event
async def on_ready():
    print(f'✅ {bot.user} olarak giriş yapıldı!')
    print(f'Bot {len(bot.guilds)} sunucuda aktif')
    await bot.change_presence(activity=discord.Game(name="!help - Müzik"))

@bot.command(name='play', aliases=['p', 'çal'])
async def play(ctx, *, query):
    """YouTube'dan müzik çal - URL veya arama terimi"""
    
    # Kullanıcı sesli kanalda mı kontrol et
    if not ctx.author.voice:
        await ctx.send("❌ Önce bir sesli kanala katılmalısınız!")
        return
    
    player = get_player(ctx.guild.id)
    
    # Bota katıl
    if not player.voice_client or not player.voice_client.is_connected():
        channel = ctx.author.voice.channel
        player.voice_client = await channel.connect()
    
    await ctx.send("🔍 Aranıyor...")
    
    # Video bilgilerini al
    song_info = await get_video_info(query)
    
    if not song_info:
        await ctx.send("❌ Video bulunamadı veya indirilemedi!")
        return
    
    # Kuyruğa ekle
    player.add_to_queue(song_info)
    
    # Eğer şu anda bir şey çalmıyorsa, çalmaya başla
    if not player.voice_client.is_playing():
        await play_next(ctx, player)
    else:
        embed = discord.Embed(
            title="➕ Kuyruğa Eklendi",
            description=f"[{song_info['title']}]({song_info['webpage_url']})",
            color=discord.Color.blue()
        )
        embed.add_field(name="Süre", value=format_duration(song_info['duration']))
        embed.add_field(name="Sıradaki Pozisyon", value=len(player.queue))
        if song_info['thumbnail']:
            embed.set_thumbnail(url=song_info['thumbnail'])
        
        await ctx.send(embed=embed)

@bot.command(name='search', aliases=['ara'])
async def search(ctx, *, query):
    """YouTube'da arama yap ve sonuçları göster"""
    await ctx.send("🔍 Aranıyor...")
    
    results = await search_youtube(query)
    
    if not results:
        await ctx.send("❌ Sonuç bulunamadı!")
        return
    
    embed = discord.Embed(
        title=f"🔍 '{query}' için arama sonuçları",
        description="Çalmak için `!play <numara>` veya `!play <URL>` kullanın",
        color=discord.Color.purple()
    )
    
    for i, result in enumerate(results[:5], 1):
        title = result.get('title', 'Bilinmeyen')
        duration = result.get('duration', 0)
        url = result.get('url', '')
        
        embed.add_field(
            name=f"{i}. {title}",
            value=f"Süre: {format_duration(duration)}\n[Link](https://youtube.com/watch?v={result['id']})",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='skip', aliases=['s', 'geç'])
async def skip(ctx):
    """Şu anki şarkıyı atla"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client or not player.voice_client.is_playing():
        await ctx.send("❌ Şu anda çalan bir şarkı yok!")
        return
    
    player.skip()
    await ctx.send("⏭️ Şarkı atlandı!")

@bot.command(name='pause', aliases=['duraklat'])
async def pause(ctx):
    """Müziği duraklat"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.pause()
        await ctx.send("⏸️ Müzik duraklatıldı!")
    else:
        await ctx.send("❌ Şu anda çalan bir şarkı yok!")

@bot.command(name='resume', aliases=['devam'])
async def resume(ctx):
    """Müziği devam ettir"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client and player.voice_client.is_paused():
        player.voice_client.resume()
        await ctx.send("▶️ Müzik devam ediyor!")
    else:
        await ctx.send("❌ Müzik duraklatılmamış!")

@bot.command(name='stop', aliases=['durdur'])
async def stop(ctx):
    """Müziği durdur ve kuyruğu temizle"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        player.clear_queue()
        player.current = None
        player.voice_client.stop()
        await ctx.send("⏹️ Müzik durduruldu ve kuyruk temizlendi!")
    else:
        await ctx.send("❌ Bot sesli kanalda değil!")

@bot.command(name='queue', aliases=['q', 'kuyruk'])
async def queue(ctx):
    """Çalma listesini göster"""
    player = get_player(ctx.guild.id)
    
    if not player.current and len(player.queue) == 0:
        await ctx.send("📭 Kuyruk boş!")
        return
    
    embed = discord.Embed(
        title="📋 Çalma Listesi",
        color=discord.Color.orange()
    )
    
    if player.current:
        embed.add_field(
            name="🎵 Şimdi Çalıyor",
            value=f"[{player.current['title']}]({player.current['webpage_url']})\nSüre: {format_duration(player.current['duration'])}",
            inline=False
        )
    
    if len(player.queue) > 0:
        queue_text = ""
        for i, song in enumerate(list(player.queue)[:10], 1):
            queue_text += f"`{i}.` [{song['title']}]({song['webpage_url']}) - {format_duration(song['duration'])}\n"
        
        if len(player.queue) > 10:
            queue_text += f"\n... ve {len(player.queue) - 10} şarkı daha"
        
        embed.add_field(
            name=f"📝 Sırada ({len(player.queue)} şarkı)",
            value=queue_text,
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='clear', aliases=['temizle'])
async def clear(ctx):
    """Kuyruğu temizle (şu anki şarkı çalmaya devam eder)"""
    player = get_player(ctx.guild.id)
    
    if len(player.queue) == 0:
        await ctx.send("❌ Kuyruk zaten boş!")
        return
    
    cleared_count = len(player.queue)
    player.clear_queue()
    await ctx.send(f"🗑️ {cleared_count} şarkı kuyruktan temizlendi!")

@bot.command(name='volume', aliases=['vol', 'ses'])
async def volume(ctx, vol: int = None):
    """Ses seviyesini ayarla (0-100)"""
    player = get_player(ctx.guild.id)
    
    if vol is None:
        current_vol = int(player.volume * 100)
        await ctx.send(f"🔊 Mevcut ses seviyesi: {current_vol}%")
        return
    
    if vol < 0 or vol > 100:
        await ctx.send("❌ Ses seviyesi 0-100 arasında olmalı!")
        return
    
    player.volume = vol / 100
    
    if player.voice_client and player.voice_client.source:
        player.voice_client.source.volume = player.volume
    
    await ctx.send(f"🔊 Ses seviyesi {vol}% olarak ayarlandı!")

@bot.command(name='nowplaying', aliases=['np', 'şimdi'])
async def nowplaying(ctx):
    """Şu anda çalan şarkıyı göster"""
    player = get_player(ctx.guild.id)
    
    if not player.current:
        await ctx.send("❌ Şu anda çalan bir şarkı yok!")
        return
    
    embed = discord.Embed(
        title="🎵 Şimdi Çalıyor",
        description=f"[{player.current['title']}]({player.current['webpage_url']})",
        color=discord.Color.green()
    )
    embed.add_field(name="Süre", value=format_duration(player.current['duration']))
    embed.add_field(name="Ses Seviyesi", value=f"{int(player.volume * 100)}%")
    
    if player.current['thumbnail']:
        embed.set_thumbnail(url=player.current['thumbnail'])
    
    await ctx.send(embed=embed)

@bot.command(name='loop', aliases=['tekrar', 'repeat'])
async def loop(ctx, mode: str = None):
    """Loop modunu ayarla - off/song/queue"""
    player = get_player(ctx.guild.id)
    
    if mode is None:
        modes = {
            "off": "❌ Kapalı",
            "song": "🔂 Şarkı Tekrarı",
            "queue": "🔁 Kuyruk Tekrarı"
        }
        current = modes.get(player.loop_mode, "❌ Kapalı")
        
        embed = discord.Embed(
            title="🔁 Loop Modu",
            description=f"Şu anki mod: **{current}**",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Kullanım",
            value=(
                "`!loop off` - Loop kapalı\n"
                "`!loop song` - Şu anki şarkıyı tekrarla\n"
                "`!loop queue` - Tüm kuyruğu tekrarla"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    mode = mode.lower()
    
    if mode in ["off", "kapat", "none"]:
        player.loop_mode = "off"
        await ctx.send("❌ Loop modu kapatıldı!")
    elif mode in ["song", "şarkı", "track"]:
        player.loop_mode = "song"
        await ctx.send("🔂 Şarkı tekrarı aktif! (Şu anki şarkı sürekli çalacak)")
    elif mode in ["queue", "kuyruk", "all", "playlist"]:
        player.loop_mode = "queue"
        await ctx.send("🔁 Kuyruk tekrarı aktif! (Kuyruk bitince başa dönecek)")
    else:
        await ctx.send("❌ Geçersiz mod! Kullanım: `!loop off/song/queue`")

@bot.command(name='playlist', aliases=['pl', 'liste'])
async def playlist(ctx, action: str = None, name: str = None, *, query: str = None):
    """Çalma listesi yönetimi
    
    Komutlar:
    !playlist create <isim> - Yeni liste oluştur
    !playlist add <isim> <şarkı/URL> - Listeye şarkı ekle
    !playlist remove <isim> <numara> - Listeden şarkı çıkar
    !playlist delete <isim> - Listeyi sil
    !playlist show <isim> - Liste detayları
    !playlist list - Tüm listelerini göster
    !playlist play <isim> - Listeyi çal
    """
    
    user_id = str(ctx.author.id)
    
    # Kullanıcının listeleri yoksa oluştur
    if user_id not in user_playlists:
        user_playlists[user_id] = {}
    
    # Parametre kontrolü
    if action is None:
        embed = discord.Embed(
            title="📋 Çalma Listesi Komutları",
            description="Kendi çalma listelerinizi oluşturun ve yönetin!",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="📝 Oluşturma & Düzenleme",
            value=(
                "`!playlist create <isim>` - Yeni liste oluştur\n"
                "`!playlist add <isim> <şarkı>` - Şarkı ekle\n"
                "`!playlist remove <isim> <numara>` - Şarkı çıkar\n"
                "`!playlist delete <isim>` - Listeyi sil"
            ),
            inline=False
        )
        embed.add_field(
            name="▶️ Görüntüleme & Çalma",
            value=(
                "`!playlist list` - Tüm listelerinizi göster\n"
                "`!playlist show <isim>` - Liste detayları\n"
                "`!playlist play <isim>` - Listeyi çal"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Örnek",
            value=(
                "`!playlist create Favori`\n"
                "`!playlist add Favori despacito`\n"
                "`!playlist play Favori`"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    # CREATE - Yeni liste oluştur
    if action in ["create", "oluştur", "new"]:
        if not name:
            await ctx.send("❌ Liste ismi belirtmelisiniz! Örnek: `!playlist create Favorilerim`")
            return
        
        if name in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli bir listeniz zaten var!")
            return
        
        user_playlists[user_id][name] = {
            "songs": [],
            "created_at": str(asyncio.get_event_loop().time()),
            "description": ""
        }
        
        if save_playlists(user_playlists):
            embed = discord.Embed(
                title="✅ Liste Oluşturuldu!",
                description=f"**{name}** çalma listesi oluşturuldu.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Şarkı Eklemek İçin",
                value=f"`!playlist add {name} <şarkı ismi/URL>`"
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Liste kaydedilirken hata oluştu!")
    
    # ADD - Listeye şarkı ekle
    elif action in ["add", "ekle"]:
        if not name or not query:
            await ctx.send("❌ Kullanım: `!playlist add <liste_ismi> <şarkı/URL>`")
            return
        
        if name not in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli liste bulunamadı! `!playlist list` ile kontrol edin.")
            return
        
        await ctx.send(f"🔍 `{query}` aranıyor...")
        
        # Şarkı bilgilerini al
        song_info = await get_video_info(query)
        
        if not song_info:
            await ctx.send("❌ Şarkı bulunamadı!")
            return
        
        # Sadece gerekli bilgileri kaydet (URL'yi değil, sorguyu kaydet)
        song_data = {
            "title": song_info['title'],
            "query": query,
            "duration": song_info['duration'],
            "webpage_url": song_info['webpage_url']
        }
        
        user_playlists[user_id][name]["songs"].append(song_data)
        
        if save_playlists(user_playlists):
            total = len(user_playlists[user_id][name]["songs"])
            embed = discord.Embed(
                title="➕ Şarkı Eklendi!",
                description=f"**{song_info['title']}**\n`{name}` listesine eklendi.",
                color=discord.Color.green()
            )
            embed.add_field(name="Liste", value=name)
            embed.add_field(name="Toplam Şarkı", value=total)
            if song_info['thumbnail']:
                embed.set_thumbnail(url=song_info['thumbnail'])
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Şarkı eklenirken hata oluştu!")
    
    # REMOVE - Listeden şarkı çıkar
    elif action in ["remove", "delete", "çıkar", "sil"]:
        if not name or not query:
            await ctx.send("❌ Kullanım: `!playlist remove <liste_ismi> <şarkı_numarası>`")
            return
        
        if name not in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli liste bulunamadı!")
            return
        
        try:
            index = int(query) - 1
            playlist = user_playlists[user_id][name]["songs"]
            
            if index < 0 or index >= len(playlist):
                await ctx.send(f"❌ Geçersiz numara! Liste 1-{len(playlist)} arası şarkı içeriyor.")
                return
            
            removed_song = playlist.pop(index)
            
            if save_playlists(user_playlists):
                await ctx.send(f"✅ **{removed_song['title']}** `{name}` listesinden çıkarıldı!")
            else:
                await ctx.send("❌ Şarkı çıkarılırken hata oluştu!")
        except ValueError:
            await ctx.send("❌ Lütfen geçerli bir numara girin!")
    
    # LIST - Tüm listeleri göster
    elif action in ["list", "listele", "all"]:
        if not user_playlists[user_id]:
            await ctx.send("📭 Henüz hiç çalma listeniz yok! `!playlist create <isim>` ile oluşturun.")
            return
        
        embed = discord.Embed(
            title=f"📋 {ctx.author.name} Kullanıcısının Çalma Listeleri",
            color=discord.Color.blue()
        )
        
        for pl_name, pl_data in user_playlists[user_id].items():
            song_count = len(pl_data["songs"])
            total_duration = sum(s["duration"] for s in pl_data["songs"])
            
            embed.add_field(
                name=f"🎵 {pl_name}",
                value=f"{song_count} şarkı • {format_duration(total_duration)}",
                inline=True
            )
        
        embed.set_footer(text="!playlist show <isim> ile detayları görün")
        await ctx.send(embed=embed)
    
    # SHOW - Liste detaylarını göster
    elif action in ["show", "view", "göster"]:
        if not name:
            await ctx.send("❌ Liste ismi belirtmelisiniz! Örnek: `!playlist show Favorilerim`")
            return
        
        if name not in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli liste bulunamadı!")
            return
        
        playlist = user_playlists[user_id][name]["songs"]
        
        if not playlist:
            await ctx.send(f"📭 `{name}` listesi boş! `!playlist add {name} <şarkı>` ile şarkı ekleyin.")
            return
        
        embed = discord.Embed(
            title=f"🎵 {name}",
            description=f"Toplam {len(playlist)} şarkı",
            color=discord.Color.purple()
        )
        
        # İlk 10 şarkıyı göster
        for i, song in enumerate(playlist[:10], 1):
            embed.add_field(
                name=f"{i}. {song['title']}",
                value=f"[Link]({song['webpage_url']}) • {format_duration(song['duration'])}",
                inline=False
            )
        
        if len(playlist) > 10:
            embed.set_footer(text=f"... ve {len(playlist) - 10} şarkı daha • !playlist play {name} ile çal")
        else:
            embed.set_footer(text=f"!playlist play {name} ile tüm listeyi çal")
        
        await ctx.send(embed=embed)
    
    # PLAY - Listeyi çal
    elif action in ["play", "çal", "start"]:
        if not name:
            await ctx.send("❌ Liste ismi belirtmelisiniz! Örnek: `!playlist play Favorilerim`")
            return
        
        if name not in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli liste bulunamadı!")
            return
        
        playlist = user_playlists[user_id][name]["songs"]
        
        if not playlist:
            await ctx.send(f"📭 `{name}` listesi boş!")
            return
        
        # Kullanıcı sesli kanalda mı kontrol et
        if not ctx.author.voice:
            await ctx.send("❌ Önce bir sesli kanala katılmalısınız!")
            return
        
        player = get_player(ctx.guild.id)
        
        # Bota katıl
        if not player.voice_client or not player.voice_client.is_connected():
            channel = ctx.author.voice.channel
            player.voice_client = await channel.connect()
        
        await ctx.send(f"📋 `{name}` listesi yükleniyor... ({len(playlist)} şarkı)")
        
        # Tüm şarkıları kuyruğa ekle
        added = 0
        for song_data in playlist:
            # Her şarkının güncel bilgilerini al
            song_info = await get_video_info(song_data['query'])
            if song_info:
                player.add_to_queue(song_info)
                added += 1
        
        embed = discord.Embed(
            title="✅ Çalma Listesi Yüklendi!",
            description=f"**{name}** listesinden {added} şarkı kuyruğa eklendi.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Eğer şu anda bir şey çalmıyorsa, çalmaya başla
        if not player.voice_client.is_playing():
            await play_next(ctx, player)
    
    # DELETE - Listeyi sil
    elif action in ["deletelist", "removeplaylist", "listesil"]:
        if not name:
            await ctx.send("❌ Liste ismi belirtmelisiniz! Örnek: `!playlist deletelist Favorilerim`")
            return
        
        if name not in user_playlists[user_id]:
            await ctx.send(f"❌ `{name}` isimli liste bulunamadı!")
            return
        
        del user_playlists[user_id][name]
        
        if save_playlists(user_playlists):
            await ctx.send(f"✅ `{name}` listesi silindi!")
        else:
            await ctx.send("❌ Liste silinirken hata oluştu!")
    
    else:
        await ctx.send(f"❌ Bilinmeyen işlem: `{action}`. `!playlist` yazarak komutları görün.")

@bot.command(name='watch', aliases=['izle', 'klip'])
async def watch(ctx, *, query: str = None):
    """YouTube klibini Go Live ile izle (BETA)"""
    
    embed = discord.Embed(
        title="🎬 Video İzleme Özelliği",
        description=(
            "Discord'da video paylaşmak için **Go Live** özelliğini kullanabilirsiniz!\n\n"
            "**Nasıl yapılır:**\n"
            "1. Sesli kanala katılın\n"
            "2. Ekranınızı paylaşmak için **ekran paylaşım** butonuna tıklayın\n"
            "3. Tarayıcı pencerenizi seçin (YouTube açık olmalı)\n"
            "4. **Go Live** başlasın\n"
            "5. Diğer kullanıcılar sizin yayınınıza katılıp videoyu izleyebilir!\n\n"
            "**Alternatif:** Discord'un Activity özelliğini kullanabilirsiniz:\n"
            "• Sesli kanalda 🎮 **Watch Together** aktivitesini başlatın\n"
            "• Herkesle birlikte YouTube izleyin!"
        ),
        color=discord.Color.purple()
    )
    
    if query:
        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        embed.add_field(
            name="🔍 Arama Sonucu",
            value=f"[YouTube'da '{query}' ara]({search_url})",
            inline=False
        )
    
    embed.set_footer(text="Not: Discord botları direkt video akışı yapamaz, ancak Go Live ile siz yapabilirsiniz!")
    
    await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['disconnect', 'ayrıl'])
async def leave(ctx):
    """Botun sesli kanaldan ayrılmasını sağla"""
    player = get_player(ctx.guild.id)
    
    if player.voice_client:
        player.clear_queue()
        player.current = None
        await player.voice_client.disconnect()
        player.voice_client = None
        await ctx.send("👋 Sesli kanaldan ayrıldım!")
    else:
        await ctx.send("❌ Bot zaten sesli kanalda değil!")

@bot.command(name='help', aliases=['yardım'])
async def help_command(ctx):
    """Yardım menüsünü göster"""
    embed = discord.Embed(
        title="🎵 YouTube Müzik Botu Komutları",
        description="Tüm komutlar için ! öneki kullanın",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="▶️ Çalma Komutları",
        value=(
            "`!play <URL/arama>` - Müzik çal\n"
            "`!search <arama>` - YouTube'da ara\n"
            "`!pause` - Duraklat\n"
            "`!resume` - Devam ettir\n"
            "`!skip` - Atla\n"
            "`!stop` - Durdur ve temizle"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📋 Kuyruk & Listeler",
        value=(
            "`!queue` - Kuyruğu göster\n"
            "`!clear` - Kuyruğu temizle\n"
            "`!nowplaying` - Şu anki şarkı\n"
            "`!loop <off/song/queue>` - Tekrar modu\n"
            "`!playlist` - Çalma listesi komutları"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎵 Çalma Listeleri",
        value=(
            "`!playlist create <isim>` - Liste oluştur\n"
            "`!playlist add <isim> <şarkı>` - Şarkı ekle\n"
            "`!playlist play <isim>` - Listeyi çal\n"
            "`!playlist list` - Listelerini göster"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎬 Video",
        value=(
            "`!watch <arama>` - Video izleme rehberi"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔧 Diğer",
        value=(
            "`!volume <0-100>` - Ses seviyesi\n"
            "`!leave` - Kanaldan ayrıl\n"
            "`!help` - Bu menü"
        ),
        inline=False
    )
    
    embed.set_footer(text="Python ile geliştirildi 🐍 | Playlist özelliği!")
    
    await ctx.send(embed=embed)

# Hata yönetimi
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Komut bulunamadı! `!help` yazarak komutları görebilirsiniz.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Eksik argüman: {error.param.name}")
    else:
        await ctx.send(f"❌ Bir hata oluştu: {str(error)}")
        print(f"Hata: {error}")

# Botu çalıştır
if __name__ == "__main__":
    # Render'da environment variable'dan token al, yoksa dosyadakini kullan
    TOKEN = os.getenv('DISCORD_TOKEN', 'MTQ3MjYwMDU5MDg3NzE5NjM4MA.GWLO83.xC5pLwq1rdM7hJtO_SvGfVM8xM6yY-mvU2e2xk')
    
    if not TOKEN or TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ HATA: Discord bot token bulunamadı!")
        print("Lütfen DISCORD_TOKEN environment variable'ını ayarlayın.")
        exit(1)
    
    bot.run(TOKEN)
