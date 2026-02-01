import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import logging
from dotenv import load_dotenv

# Logging
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="!", intents=intents)

# --- MUSIC SETTINGS (ANDROID CLIENT FIX) ---
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch', # Αλλαγή σε ytsearch για να βρίσκει πάντα κάτι
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'cookiefile': 'cookies.txt', 
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

queues = {} 
voice_clients = {} 

class MusicControls(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = voice_clients.get(interaction.guild.id)
        if vc:
            if vc.is_playing():
                vc.pause()
                await interaction.response.send_message("⏸️ Παύση", ephemeral=True)
            elif vc.is_paused():
                vc.resume()
                await interaction.response.send_message("▶️ Συνέχιση", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = voice_clients.get(interaction.guild.id)
        if vc:
            vc.stop()
            await interaction.response.send_message("⏭️ Skip!", ephemeral=True)

def play_next(guild_id, interaction):
    if guild_id in queues and len(queues[guild_id]) > 0:
        url, title = queues[guild_id].pop(0)
        vc = voice_clients.get(guild_id)
        if vc:
            try:
                # Προσοχή: Εδώ είναι το path για το ffmpeg στο Raspberry Pi
                source = discord.FFmpegPCMAudio(url, executable="/usr/bin/ffmpeg", **FFMPEG_OPTIONS)
                vc.play(source, after=lambda e: play_next(guild_id, interaction))
                coro = interaction.channel.send(f"🎶 Τώρα παίζει: **{title}**")
                asyncio.run_coroutine_threadsafe(coro, client.loop)
            except Exception as e:
                print(f"Error in play_next: {e}")

@client.tree.command(name="play", description="Παίζει μουσική")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    guild_id = interaction.guild.id
    if not interaction.user.voice:
        return await interaction.followup.send("❌ Μπες σε ένα voice channel!")

    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        try:
            vc = await interaction.user.voice.channel.connect()
            voice_clients[guild_id] = vc
        except Exception as e:
            return await interaction.followup.send("❌ Δεν μπορώ να μπω στο κανάλι. Τσέκαρε τα permissions.")
    else:
        vc = voice_clients[guild_id]

    try:
        # Αναζήτηση με ασφάλεια
        data = await asyncio.get_event_loop().run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        
        # ΕΛΕΓΧΟΣ ΓΙΑ ΤΟ CRASH (List index out of range)
        if 'entries' in data:
            if len(data['entries']) > 0:
                data = data['entries'][0]
            else:
                return await interaction.followup.send("❌ Δεν βρέθηκαν αποτελέσματα. Δοκίμασε άλλο όνομα.")
        
        song_url = data['url']
        title = data['title']

        if vc.is_playing() or vc.is_paused():
            if guild_id not in queues: queues[guild_id] = []
            queues[guild_id].append((song_url, title))
            await interaction.followup.send(f"✅ Προστέθηκε: **{title}**")
        else:
            # Έλεγχος εκτύπωσης URL για debugging (θα φανεί στα logs αν αποτύχει το ffmpeg)
            print(f"Trying to play: {title} | URL: {song_url}")
            
            source = discord.FFmpegPCMAudio(song_url, executable="/usr/bin/ffmpeg", **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(guild_id, interaction))
            view = MusicControls(interaction)
            await interaction.followup.send(f"🎶 Τώρα παίζει: **{title}**", view=view)

    except Exception as e:
        print(f"Play Error: {e}")
        try:
            await interaction.followup.send(f"❌ Σφάλμα: {e}")
        except:
            pass

@client.event
async def on_ready():
    await client.tree.sync()
    print(f"🎧 Online as {client.user}")

client.run(TOKEN)