# 🎧 CrazyMusic Bot

Ο απόλυτος DJ για τον Discord Server σου! Παίζει μουσική σε υψηλή ποιότητα από
το YouTube με εύχρηστα κουμπιά ελέγχου και slash commands.

🔗 **[Κάντε κλικ εδώ για Invite](https://discord.com/oauth2/authorize?client_id=1453361575665864754&permissions=3145728&scope=bot+applications.commands)**

---

## 🎵 Δυνατότητες (Features)

* **High Quality Audio:** Χρήση του `yt-dlp` και `ffmpeg` για καθαρό ήχο.
* **Smart Controls:** Κουμπιά κάτω από το τραγούδι (Pause/Resume, Skip, Stop, Loop, Shuffle).
* **Queue System:** Ουρά τραγουδιών με `/queue`, `/shuffle` και loop modes.
* **Slash Commands:** Μοντέρνο περιβάλλον με `/play`, `/skip`, `/volume` κ.ά.
* **Auto-disconnect:** Αποσυνδέεται αυτόματα μετά από αδράνεια.

---

## ⚡ Commands

| Command | Περιγραφή |
| :-- | :-- |
| `/play <query/url>` | Παίζει ή προσθέτει τραγούδι στην ουρά |
| `/skip` | Επόμενο τραγούδι |
| `/pause` | Pause / Resume |
| `/stop` | Σταματάει και καθαρίζει την ουρά |
| `/volume <0-150>` | Ένταση |
| `/loop <off/one/all>` | Loop mode |
| `/shuffle` | Ανακατεύει την ουρά |
| `/queue` | Δείχνει την ουρά |
| `/nowplaying` | Τι παίζει τώρα |
| `/disconnect` | Αποσύνδεση από το voice |

---

## 🛠️ Εγκατάσταση (Installation)

### 1. Απαραίτητα (Pre-requisites)

Χρειάζεσαι **FFmpeg** και έναν **JS runtime** (Node.js) για το yt-dlp:

```bash
sudo apt update
sudo apt install ffmpeg nodejs -y
```

### 2. Λήψη & Setup

```bash
git clone https://github.com/CrazyAlex15/CrazyMusic.git
cd CrazyMusic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Ρύθμιση (.env)

Φτιάξε ένα αρχείο `.env`:

```ini
DISCORD_TOKEN=your_bot_token_here
```

### 4. Εκκίνηση

```bash
python main.py
```

### 24/7 Hosting (PM2)

```bash
pm2 start main.py --name crazymusic --interpreter ./venv/bin/python3
pm2 save
```

---

<sub>Developed with ❤️ by <a href="https://github.com/CrazyAlex15">CrazyAlex</a></sub>
