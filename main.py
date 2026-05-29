import os
os.environ['PATH'] = '/usr/bin:/usr/local/bin:/bin:' + os.environ.get('PATH', '')

import discord
from discord.ext import commands
import yt_dlp
import asyncio
import logging
import shutil
import time
import random
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
log = logging.getLogger('CrazyMusic')

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise RuntimeError('DISCORD_TOKEN not found — add it to your .env file.')

FFMPEG_EXECUTABLE = shutil.which('ffmpeg') or '/usr/bin/ffmpeg'
IDLE_TIMEOUT = 300

# ── Opus loading ──────────────────────────────────────────────────────────────
def _load_opus() -> None:
    if discord.opus.is_loaded():
        log.info('Opus already loaded')
        return
    candidates = [
        'libopus.so.0',
        'libopus.so',
        '/usr/lib/aarch64-linux-gnu/libopus.so.0',
        '/usr/lib/arm-linux-gnueabihf/libopus.so.0',
        'opus',
    ]
    for lib in candidates:
        try:
            discord.opus.load_opus(lib)
            log.info('Opus loaded from: %s', lib)
            return
        except Exception:
            continue
    log.error('Could not load opus — voice audio will NOT work. Run: sudo apt install libopus0')

_load_opus()

# ── JS runtime detection ──────────────────────────────────────────────────────
def _detect_js_runtime() -> Optional[dict]:
    for runtime in ('deno', 'node', 'bun'):
        path = shutil.which(runtime)
        if path:
            log.info('JS runtime detected: %s (%s)', runtime, path)
            return {runtime: {}}
    log.error(
        'No JS runtime (deno/node) found — YouTube extraction WILL fail. '
        'Install one:  sudo apt install nodejs'
    )
    return None

JS_RUNTIMES = _detect_js_runtime()

COOKIE_FILE = 'cookies.txt' if os.path.isfile('cookies.txt') else None
if COOKIE_FILE:
    log.info('Using cookies file: %s', COOKIE_FILE)
else:
    log.info('No cookies.txt found — running without cookies')

# ── yt-dlp options ────────────────────────────────────────────────────────────
YTDL_OPTIONS = {
    # Accept bestaudio, fall back to combined stream (format 18 = 360p+audio)
    # so SABR-only clients never leave us with zero matches.
    'format': 'bestaudio/best/bestaudio*[ext=m4a]/bestaudio*[ext=webm]/18',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'retries': 5,
    'extractor_retries': 3,
    # web  — standard browser client, respects cookies
    # tv   — reliable fallback, not SABR-gated
    # android_vr — returns clean audio formats without SABR restrictions
    'extractor_args': {'youtube': {'player_client': ['web', 'tv', 'android_vr']}},
}
if JS_RUNTIMES:
    YTDL_OPTIONS['js_runtimes'] = JS_RUNTIMES
if COOKIE_FILE:
    YTDL_OPTIONS['cookiefile'] = COOKIE_FILE

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

COLOR = 0x7289DA
LOOP_LABELS = {'off': '➡️ Off', 'one': '🔂 One', 'all': '🔁 All'}


# Shared instance — created on first use (after PATH patch is active)
_ytdl_client: Optional[yt_dlp.YoutubeDL] = None

def get_ytdl() -> yt_dlp.YoutubeDL:
    global _ytdl_client
    if _ytdl_client is None:
        _ytdl_client = yt_dlp.YoutubeDL(YTDL_OPTIONS)
    return _ytdl_client


# ── Data models ───────────────────────────────────────────────────────────────
@dataclass
class Song:
    stream_url: str
    title: str
    webpage_url: str
    duration: Optional[int]
    thumbnail: Optional[str]
    requester: str

    def duration_str(self) -> str:
        if not self.duration:
            return 'Live'
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


class GuildState:
    """All music state isolated per guild."""

    def __init__(self) -> None:
        self.queue: list[Song] = []
        self.current: Optional[Song] = None
        self.vc: Optional[discord.VoiceClient] = None
        self.volume: float = 0.5
        self.loop: str = 'off'
        self.idle_since: Optional[float] = None
        self._skip_flag: bool = False

    @property
    def is_playing(self) -> bool:
        return self.vc is not None and self.vc.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.vc is not None and self.vc.is_paused()

    @property
    def is_active(self) -> bool:
        return self.is_playing or self.is_paused

    def skip(self) -> None:
        if self.vc and self.is_active:
            self._skip_flag = True
            self.vc.stop()


# ── Globals ───────────────────────────────────────────────────────────────────
_states: dict[int, GuildState] = {}


def get_state(guild_id: int) -> GuildState:
    if guild_id not in _states:
        _states[guild_id] = GuildState()
    return _states[guild_id]


# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


# ── Audio helpers ─────────────────────────────────────────────────────────────
class ExtractError(Exception):
    """Raised when yt-dlp errors out."""


async def resolve_song(query: str, requester: str) -> Optional[Song]:
    """Fetch song metadata from YouTube in an executor (non-blocking)."""
    search = query if query.startswith('http') else f'ytsearch1:{query}'
    loop = asyncio.get_running_loop()
    log.info('🔎 Searching for: %s', search)
    try:
        data = await loop.run_in_executor(
            None,
            lambda: get_ytdl().extract_info(search, download=False)
        )
    except Exception as exc:
        log.error('yt-dlp error: %s', exc)
        raise ExtractError(str(exc)) from exc

    if not data:
        return None
    if 'entries' in data:
        entries = [e for e in data['entries'] if e]
        if not entries:
            return None
        data = entries[0]

    stream_url = data.get('url')
    if not stream_url and data.get('formats'):
        audio = [f for f in data['formats'] if f.get('acodec') not in (None, 'none') and f.get('url')]
        if audio:
            stream_url = audio[-1]['url']
    if not stream_url:
        raise ExtractError('No playable audio stream returned by YouTube.')

    return Song(
        stream_url=stream_url,
        title=data.get('title', 'Unknown'),
        webpage_url=data.get('webpage_url', ''),
        duration=data.get('duration'),
        thumbnail=data.get('thumbnail'),
        requester=requester,
    )


def build_source(song: Song, volume: float) -> discord.AudioSource:
    raw = discord.FFmpegPCMAudio(
        song.stream_url, executable=FFMPEG_EXECUTABLE, **FFMPEG_OPTIONS
    )
    return discord.PCMVolumeTransformer(raw, volume=volume)


def build_np_embed(song: Song, state: GuildState) -> discord.Embed:
    embed = discord.Embed(
        title='🎶 Now Playing',
        description=f'[{song.title}]({song.webpage_url})',
        color=COLOR,
    )
    embed.add_field(name='⏱ Duration', value=song.duration_str(), inline=True)
    embed.add_field(name='🔊 Volume',   value=f'{int(state.volume * 100)}%', inline=True)
    embed.add_field(name='🔁 Loop',     value=LOOP_LABELS[state.loop], inline=True)
    embed.add_field(name='📋 Queue',    value=f'{len(state.queue)} songs', inline=True)
    embed.set_footer(text=f'Requested by {song.requester}')
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    return embed


# ── Playback engine ───────────────────────────────────────────────────────────
def _after_song(guild_id: int, channel, error: Optional[Exception]) -> None:
    if error:
        log.error('Playback error guild %d: %s', guild_id, error)
    asyncio.run_coroutine_threadsafe(_play_next(guild_id, channel), bot.loop)


async def _play_next(guild_id: int, channel) -> None:
    state = get_state(guild_id)

    if state._skip_flag:
        state._skip_flag = False
    else:
        if state.loop == 'one' and state.current:
            state.queue.insert(0, state.current)
        elif state.loop == 'all' and state.current:
            state.queue.append(state.current)

    if not state.queue:
        state.current = None
        state.idle_since = time.monotonic()
        return

    if not state.vc or not state.vc.is_connected():
        state.current = None
        state.idle_since = time.monotonic()
        return

    song = state.queue.pop(0)
    state.current = song
    state.idle_since = None

    log.info('[guild %d] Attempting to play: %s', guild_id, song.title)
    log.info('[guild %d] Stream URL: %s…', guild_id, song.stream_url[:60])
    log.info('[guild %d] FFmpeg: %s  |  Opus: %s', guild_id, FFMPEG_EXECUTABLE, discord.opus.is_loaded())

    try:
        source = build_source(song, state.volume)
        state.vc.play(source, after=lambda e: _after_song(guild_id, channel, e))
        embed = build_np_embed(song, state)
        view = PlayerView(guild_id, channel)
        await channel.send(embed=embed, view=view)
        log.info('[guild %d] Now playing: %s', guild_id, song.title)
    except Exception as exc:
        log.error('[guild %d] _play_next error: %s', guild_id, exc)
        await channel.send(f'❌ Error playing **{song.title}**: {exc}')
        await _play_next(guild_id, channel)


# ── Idle watcher ──────────────────────────────────────────────────────────────
async def _idle_watcher() -> None:
    while True:
        await asyncio.sleep(30)
        for guild_id, state in list(_states.items()):
            if (
                state.vc
                and state.vc.is_connected()
                and not state.is_active
                and state.idle_since is not None
                and time.monotonic() - state.idle_since >= IDLE_TIMEOUT
            ):
                await state.vc.disconnect()
                state.vc = None
                state.idle_since = None
                log.info('[guild %d] Auto-disconnected (idle timeout)', guild_id)


# ── Player controls view ──────────────────────────────────────────────────────
class PlayerView(discord.ui.View):
    def __init__(self, guild_id: int, channel) -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel = channel

    @discord.ui.button(label='⏸ Pause', style=discord.ButtonStyle.primary, row=0)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_state(self.guild_id)
        if not state.vc:
            return await interaction.response.send_message('Not connected.', ephemeral=True)
        if state.is_playing:
            state.vc.pause()
            button.label = '▶️ Resume'
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
        elif state.is_paused:
            state.vc.resume()
            button.label = '⏸ Pause'
            button.style = discord.ButtonStyle.primary
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message('Nothing is playing.', ephemeral=True)

    @discord.ui.button(label='⏭ Skip', style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_state(self.guild_id)
        if not state.is_active:
            return await interaction.response.send_message('Nothing to skip.', ephemeral=True)
        state.skip()
        await interaction.response.send_message('⏭ Skipped!', ephemeral=True)

    @discord.ui.button(label='⏹ Stop', style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_state(self.guild_id)
        state.queue.clear()
        state.loop = 'off'
        if state.is_active:
            state._skip_flag = True
            state.vc.stop()
        await interaction.response.send_message('⏹ Stopped and queue cleared.', ephemeral=True)

    @discord.ui.button(label='🔁 Loop: Off', style=discord.ButtonStyle.secondary, row=1)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_state(self.guild_id)
        modes = ['off', 'one', 'all']
        state.loop = modes[(modes.index(state.loop) + 1) % 3]
        button.label = f'Loop: {state.loop.title()}'
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label='🔀 Shuffle', style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_state(self.guild_id)
        if len(state.queue) < 2:
            return await interaction.response.send_message('Not enough songs in queue.', ephemeral=True)
        random.shuffle(state.queue)
        await interaction.response.send_message(
            f'🔀 Shuffled **{len(state.queue)}** songs!', ephemeral=True
        )


# ── Slash commands ────────────────────────────────────────────────────────────
@bot.tree.command(name='play', description='Play a song or add it to the queue')
async def play_cmd(interaction: discord.Interaction, query: str):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    guild_id = interaction.guild.id
    state = get_state(guild_id)

    if not interaction.user.voice:
        return await interaction.followup.send('❌ Join a voice channel first!')

    if not state.vc or not state.vc.is_connected():
        try:
            state.vc = await interaction.user.voice.channel.connect()
            state.idle_since = None
        except Exception as exc:
            return await interaction.followup.send(f'❌ Cannot join voice channel: {exc}')
    elif state.vc.channel != interaction.user.voice.channel:
        await state.vc.move_to(interaction.user.voice.channel)

    try:
        song = await resolve_song(query, str(interaction.user))
    except ExtractError as exc:
        log.error('Extraction failed: %s', exc)
        return await interaction.followup.send(f'❌ Play Error: {str(exc)[:300]}')
    if not song:
        return await interaction.followup.send('❌ Could not find that song.')

    if state.is_active:
        state.queue.append(song)
        embed = discord.Embed(
            title='✅ Added to Queue',
            description=f'[{song.title}]({song.webpage_url})',
            color=COLOR,
        )
        embed.add_field(name='⏱ Duration', value=song.duration_str(), inline=True)
        embed.add_field(name='📋 Position', value=f'#{len(state.queue)}', inline=True)
        embed.set_footer(text=f'Requested by {interaction.user}')
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return await interaction.followup.send(embed=embed)

    state.queue.append(song)
    await interaction.followup.send(f'▶️ Starting **{song.title}**…', ephemeral=True)
    await _play_next(guild_id, interaction.channel)


@bot.tree.command(name='skip', description='Skip the current song')
async def skip_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if not state.is_active:
        return await interaction.response.send_message('❌ Nothing is playing.', ephemeral=True)
    state.skip()
    await interaction.response.send_message('⏭ Skipped!')


@bot.tree.command(name='stop', description='Stop playback and clear the queue')
async def stop_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    state.queue.clear()
    state.loop = 'off'
    if state.is_active:
        state._skip_flag = True
        state.vc.stop()
    await interaction.response.send_message('⏹ Stopped and queue cleared.')


@bot.tree.command(name='pause', description='Pause or resume the current song')
async def pause_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if state.is_playing:
        state.vc.pause()
        await interaction.response.send_message('⏸ Paused.')
    elif state.is_paused:
        state.vc.resume()
        await interaction.response.send_message('▶️ Resumed.')
    else:
        await interaction.response.send_message('❌ Nothing is playing.', ephemeral=True)


@bot.tree.command(name='volume', description='Set the volume (0 – 150)')
async def volume_cmd(interaction: discord.Interaction, level: int):
    if not 0 <= level <= 150:
        return await interaction.response.send_message('❌ Volume must be between 0 and 150.', ephemeral=True)
    state = get_state(interaction.guild.id)
    state.volume = level / 100
    if (
        state.vc
        and state.is_active
        and isinstance(state.vc.source, discord.PCMVolumeTransformer)
    ):
        state.vc.source.volume = state.volume
    await interaction.response.send_message(f'🔊 Volume set to **{level}%**.')


@bot.tree.command(name='loop', description='Set loop mode: off / one / all')
async def loop_cmd(interaction: discord.Interaction, mode: str):
    if mode not in ('off', 'one', 'all'):
        return await interaction.response.send_message(
            '❌ Mode must be `off`, `one`, or `all`.', ephemeral=True
        )
    state = get_state(interaction.guild.id)
    state.loop = mode
    await interaction.response.send_message(f'{LOOP_LABELS[mode]} Loop set to **{mode}**.')


@loop_cmd.autocomplete('mode')
async def loop_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    return [
        discord.app_commands.Choice(name=m, value=m)
        for m in ('off', 'one', 'all')
        if current.lower() in m
    ]


@bot.tree.command(name='shuffle', description='Shuffle the upcoming queue')
async def shuffle_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if len(state.queue) < 2:
        return await interaction.response.send_message('❌ Not enough songs in queue.', ephemeral=True)
    random.shuffle(state.queue)
    await interaction.response.send_message(f'🔀 Shuffled **{len(state.queue)}** songs!')


@bot.tree.command(name='queue', description='Show the current queue')
async def queue_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if not state.current and not state.queue:
        return await interaction.response.send_message('📋 The queue is empty.', ephemeral=True)

    embed = discord.Embed(title='📋 Queue', color=COLOR)

    if state.current:
        embed.add_field(
            name='🎶 Now Playing',
            value=f'[{state.current.title}]({state.current.webpage_url}) `{state.current.duration_str()}`',
            inline=False,
        )

    if state.queue:
        lines = [
            f'`{i + 1}.` [{s.title}]({s.webpage_url}) `{s.duration_str()}` — {s.requester}'
            for i, s in enumerate(state.queue[:10])
        ]
        if len(state.queue) > 10:
            lines.append(f'…and **{len(state.queue) - 10}** more')
        embed.add_field(name='Up Next', value='\n'.join(lines), inline=False)

    total_sec = sum(s.duration or 0 for s in state.queue)
    m, s = divmod(total_sec, 60)
    embed.set_footer(
        text=f'Loop: {state.loop}  •  Volume: {int(state.volume * 100)}%  •  Queue length: {m}m {s}s'
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name='nowplaying', description='Show what is currently playing')
async def np_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if not state.current:
        return await interaction.response.send_message('❌ Nothing is playing.', ephemeral=True)
    embed = build_np_embed(state.current, state)
    view = PlayerView(interaction.guild.id, interaction.channel)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name='disconnect', description='Disconnect the bot from voice')
async def disconnect_cmd(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    if not state.vc or not state.vc.is_connected():
        return await interaction.response.send_message('❌ Not connected.', ephemeral=True)
    state.queue.clear()
    state.current = None
    state.loop = 'off'
    await state.vc.disconnect()
    state.vc = None
    await interaction.response.send_message('👋 Disconnected.')


# ── Global error handler ──────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
) -> None:
    original = getattr(error, 'original', error)

    if isinstance(original, discord.errors.NotFound) and original.code == 10062:
        log.warning('Interaction expired (10062)')
        return

    log.error('App command error: %s', error)

    msg = f'❌ Something went wrong: {original}'
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


# ── Events ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    total = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            total += len(synced)
        except Exception as exc:
            log.warning('Guild sync failed for %s: %s', guild.id, exc)
    try:
        await bot.tree.sync()
    except Exception as exc:
        log.warning('Global sync failed: %s', exc)

    asyncio.create_task(_idle_watcher())
    log.info(
        '🎧 Online as %s | ffmpeg: %s | opus: %s | JS runtime: %s | cookies: %s | synced %d cmds across %d guild(s)',
        bot.user, FFMPEG_EXECUTABLE, discord.opus.is_loaded(),
        bool(JS_RUNTIMES), bool(COOKIE_FILE), total, len(bot.guilds),
    )


# ── Manual sync command ───────────────────────────────────────────────────────
@bot.command(name='sync')
@commands.is_owner()
async def sync_cmd(ctx: commands.Context):
    bot.tree.copy_global_to(guild=ctx.guild)
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f'✅ Synced **{len(synced)}** commands to this server.')
    log.info('Manual guild sync: %d commands → guild %d', len(synced), ctx.guild.id)


bot.run(TOKEN)