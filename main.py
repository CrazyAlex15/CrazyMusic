import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

# Load Token
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Setup Bot
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="!", intents=intents)

# --- MUSIC SETTINGS ---
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0', 
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# --- GLOBAL VARIABLES ---
queues = {} 
voice_clients = {} 

# --- BUTTONS VIEW ---
class MusicControls(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = voice_clients.get(interaction.guild.id)
        if not vc:
            return await interaction.response.send_message("❌ Δεν παίζω μουσική!", ephemeral=True)
        
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Μουσική σε παύση.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Συνέχιση μουσικής.", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = voice_clients.get(interaction.guild.id)
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Δεν υπάρχει τραγούδι για skip.", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = voice_clients.get(interaction.guild.id)
        guild_id = interaction.guild.id
        
        if guild_id in queues:
            queues[guild_id].clear()
            
        if vc:
            await vc.disconnect()
            del voice_clients[guild_id]
            await interaction.response.send_message("⏹️ Σταμάτησα και βγήκα.", ephemeral=True)

# --- HELPER FUNCTIONS ---
def play_next(guild_id, ctx):
    if guild_id in queues and len(queues[guild_id]) > 0:
        url, title = queues[guild_id].pop(0)
        vc = voice_clients[guild_id]
        
        def after_playing(error):
            if error: print(f"Error: {error}")
            play_next(guild_id, ctx)

        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        
        coro = ctx.channel.send(f"🎶 Τώρα παίζει: **{title}**")
        asyncio.run_coroutine_threadsafe(coro, client.loop)

# --- COMMANDS ---
@client.tree.command(name="play", description="Παίζει μουσική από YouTube (Link ή Αναζήτηση)")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ Πρέπει να είσαι σε Voice Channel πρώτα!")
    
    guild_id = interaction.guild.id
    channel = interaction.user.voice.channel

    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        vc = await channel.connect()
        voice_clients[guild_id] = vc
    else:
        vc = voice_clients[guild_id]
        if vc.channel != channel:
            await vc.move_to(channel)

    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        
        if 'entries' in data:
            data = data['entries'][0]
            
        song_url = data['url']
        title = data['title']
        thumbnail = data.get('thumbnail', None)
        duration = data.get('duration_string', "Unknown")

        if guild_id not in queues:
            queues[guild_id] = []

        if vc.is_playing() or vc.is_paused():
            queues[guild_id].append((song_url, title))
            embed = discord.Embed(title="✅ Προστέθηκε στην ουρά", description=f"**{title}**", color=0x3498db)
            embed.set_thumbnail(url=thumbnail)
            await interaction.followup.send(embed=embed)
        else:
            source = discord.FFmpegPCMAudio(song_url, **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: play_next(guild_id, interaction))
            
            embed = discord.Embed(title="🎶 Τώρα Παίζει", description=f"**{title}**", color=0x1abc9c)
            embed.add_field(name="Διάρκεια", value=duration, inline=True)
            embed.add_field(name="Ζητήθηκε από", value=interaction.user.mention, inline=True)
            if thumbnail: embed.set_image(url=thumbnail)
            
            view = MusicControls(interaction)
            await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(e)
        await interaction.followup.send("❌ Πρόβλημα με το τραγούδι (Ίσως έχει περιορισμό).")

@client.event
async def on_ready():
    await client.tree.sync()
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/play Music"))
    print(f"🎧 CrazyMusic is Online as {client.user}")

client.run(TOKEN)