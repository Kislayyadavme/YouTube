# YT Downloader Pro — Render Deployment Guide

## Files
```
ytdl-render/
├── app.py             ← Flask backend
├── templates/
│   └── index.html     ← Full web UI
├── requirements.txt   ← Python deps
├── render.yaml        ← Render config
├── build.sh           ← Build script (installs ffmpeg)
└── README.md
```

---

## Deploy to Render (Step-by-Step)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "YT Downloader Pro"
git remote add origin https://github.com/YOUR_USERNAME/yt-downloader-pro.git
git push -u origin main
```

### 2. Create Render Web Service
1. Go to https://render.com → **New → Web Service**
2. Connect your GitHub repo
3. Fill in:
   - **Name**: `yt-downloader-pro`
   - **Runtime**: `Python 3`
   - **Build Command**: `bash build.sh`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 600`
4. **Environment Variables** (under Advanced):
   - `DOWNLOAD_DIR` = `/tmp/ytdl_downloads`
5. Click **Create Web Service**

### 3. Done!
Your app will be live at `https://yt-downloader-pro.onrender.com`

---

## Features
- Download video (4K / 2K / 1080p / 720p / 480p / 360p / 144p)
- Download audio (MP3 / AAC / FLAC / WAV / OGG / OPUS / M4A)
- Download video clip (trim by start/end time)
- Embed subtitles & thumbnails
- YouTube search → pick result → download
- List all available formats for any URL
- Real-time progress bar with speed & ETA

---

## Notes
- Render free tier sleeps after 15 min inactivity (first request wakes it up)
- Downloaded files live in `/tmp` — they reset on restart (Render free tier)
- For permanent storage, upgrade to Render paid tier and use a Disk
- yt-dlp auto-updates via `pip install -r requirements.txt` on each deploy
