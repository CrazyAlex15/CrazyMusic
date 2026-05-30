# CrazyMusic — What was fixed (2026)

Your bot stopped working because **YouTube extraction broke**, not because of your code.
Three changes in `main.py` plus one thing to install on the Pi.

## What changed in `main.py`
1. **JS runtime is now required.** yt-dlp can no longer extract YouTube audio without a
   JavaScript engine (deno/node) to solve YouTube's signature challenge. The bot now
   auto-detects `deno`/`node`/`bun` and tells yt-dlp to use it. If none is found it logs a
   loud error instead of silently failing.
2. **Player clients swapped.** Old: `['ios','android','web']` — these now return HTTP 403,
   and `ios` silently *ignores your cookies.txt*. New: `['web','mweb','tv']`, which work and
   respect cookies.
3. **Smarter errors + small hardening.** `cookies.txt` is now optional, the stream URL is
   resolved more robustly, retries were added, slash commands sync per-guild so they appear
   instantly, and `/play` now tells you exactly what to fix if extraction fails.

## On the Pi — run once
```bash
cd CrazyMusic
bash setup.sh        # installs ffmpeg, libopus0, nodejs, upgrades yt-dlp
```
Or manually:
```bash
sudo apt install -y ffmpeg libopus0 nodejs
source venv/bin/activate
pip install --upgrade yt-dlp
```

## Keep it working long-term
YouTube breaks yt-dlp every few weeks. When playback dies again, 99% of the time the fix is:
```bash
source venv/bin/activate && pip install --upgrade yt-dlp
```
then restart the bot. (You can even add `pip install -U yt-dlp` to your service's start script.)

## Discord portal reminder
The bot uses the **Message Content Intent** (for the `!sync` command). If login crashes with
`PrivilegedIntentsRequired`, enable it: Developer Portal → your app → Bot → Privileged Gateway
Intents → toggle **Message Content Intent** ON.
