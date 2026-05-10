import os
import re
import json
import uuid
import threading
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file, Response
from datetime import datetime

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory job store  {job_id: {status, progress, filename, error, ...}}
jobs = {}
jobs_lock = threading.Lock()

# ─── Helpers ──────────────────────────────────────────────────────
def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def make_progress_hook(job_id):
    def hook(d):
        with jobs_lock:
            job = jobs.get(job_id, {})
            if d["status"] == "downloading":
                pct = d.get("_percent_str", "0%").strip().replace("%", "")
                try:
                    job["progress"] = float(pct)
                except:
                    job["progress"] = 0
                job["speed"]    = d.get("_speed_str",   "").strip()
                job["eta"]      = d.get("_eta_str",     "").strip()
                job["size"]     = d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str", "")
                if hasattr(job["size"], "strip"):
                    job["size"] = job["size"].strip()
                job["status"]   = "downloading"
            elif d["status"] == "finished":
                job["progress"] = 99
                job["status"]   = "processing"
            elif d["status"] == "error":
                job["status"]   = "error"
                job["error"]    = "Download error"
    return hook

QUALITY_MAP = {
    "4k"   : "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best",
    "2k"   : "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best",
    "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best",
    "720p" : "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best",
    "480p" : "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best",
    "360p" : "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best",
    "144p" : "bestvideo[height<=144][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=144]+bestaudio/best",
    "best" : "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
}

AUDIO_CODEC_MAP = {
    "mp3" : "mp3",  "aac": "aac", "flac": "flac",
    "wav" : "wav",  "ogg": "vorbis", "opus": "opus", "m4a": "m4a",
}

# ─── Background worker ────────────────────────────────────────────
def run_download(job_id, url, mode, quality, audio_fmt, audio_quality,
                 subs, thumbnail, clip_start, clip_end):
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    base_opts = {
        "outtmpl"                    : os.path.join(job_dir, "%(title)s.%(ext)s"),
        "progress_hooks"             : [make_progress_hook(job_id)],
        "retries"                    : 5,
        "fragment_retries"           : 5,
        "concurrent_fragment_downloads": 4,
        "geo_bypass"                 : True,
        "quiet"                      : True,
        "no_warnings"                : True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    }

    try:
        if mode == "audio":
            codec = AUDIO_CODEC_MAP.get(audio_fmt, "mp3")
            opts  = {
                **base_opts,
                "format"        : "bestaudio/best",
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": codec,
                     "preferredquality": audio_quality or "320"},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                ],
            }
        else:
            fmt  = QUALITY_MAP.get(quality, QUALITY_MAP["best"])
            pps  = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
            opts = {
                **base_opts,
                "format"              : fmt,
                "merge_output_format" : "mp4",
                "postprocessors"      : pps,
            }
            if subs:
                opts["writesubtitles"]   = True
                opts["subtitleslangs"]   = ["en", "auto"]
                opts["embedsubtitles"]   = True
                pps.append({"key": "FFmpegEmbedSubtitle"})
            if thumbnail:
                opts["writethumbnail"]  = True
                opts["embedthumbnail"]  = True
                pps.append({"key": "EmbedThumbnail"})
            if clip_start and clip_end:
                def _ts(t):
                    parts = list(map(int, t.split(":")))
                    if len(parts) == 3: return parts[0]*3600+parts[1]*60+parts[2]
                    if len(parts) == 2: return parts[0]*60+parts[1]
                    return int(parts[0])
                opts["download_ranges"]          = lambda *_: [{"start_time": _ts(clip_start), "end_time": _ts(clip_end)}]
                opts["force_keyframes_at_cuts"]  = True

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # Find the downloaded file
        files = [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
        if not files:
            raise Exception("No output file found after download.")
        files.sort(key=lambda f: os.path.getmtime(os.path.join(job_dir, f)), reverse=True)
        filename = files[0]

        with jobs_lock:
            jobs[job_id]["status"]   = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["filename"] = filename
            jobs[job_id]["filepath"] = os.path.join(job_dir, filename)

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = str(e)

# ─── Routes ───────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0) or 0
        return jsonify({
            "title"      : info.get("title",    "Unknown"),
            "channel"    : info.get("uploader", "Unknown"),
            "thumbnail"  : info.get("thumbnail",""),
            "duration"   : f"{duration//3600:02d}:{(duration%3600)//60:02d}:{duration%60:02d}",
            "views"      : f"{info.get('view_count',0):,}",
            "likes"      : f"{info.get('like_count',0):,}",
            "upload_date": info.get("upload_date",""),
            "is_live"    : info.get("is_live", False),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL"}), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        fmts = []
        for f in info.get("formats", []):
            fmts.append({
                "id"    : f.get("format_id","?"),
                "ext"   : f.get("ext","?"),
                "res"   : f.get("resolution") or f"{f.get('width','?')}x{f.get('height','?')}",
                "fps"   : f.get("fps","?"),
                "size"  : f"{f['filesize']/1024/1024:.1f}MB" if f.get("filesize") else "N/A",
                "note"  : f.get("format_note",""),
                "vcodec": f.get("vcodec","?"),
                "acodec": f.get("acodec","?"),
            })
        return jsonify({"formats": fmts})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/search", methods=["POST"])
def search():
    query = request.json.get("query","").strip()
    count = request.json.get("count", 6)
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        with yt_dlp.YoutubeDL({"quiet":True,"no_warnings":True,"extract_flat":True}) as ydl:
            results = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
        entries = []
        for e in results.get("entries", []):
            dur = e.get("duration", 0) or 0
            entries.append({
                "id"       : e.get("id",""),
                "title"    : e.get("title","?"),
                "channel"  : e.get("uploader","?"),
                "duration" : f"{dur//60}:{dur%60:02d}",
                "thumbnail": e.get("thumbnail",""),
                "url"      : f"https://www.youtube.com/watch?v={e.get('id','')}",
            })
        return jsonify({"results": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data          = request.json
    url           = data.get("url","").strip()
    mode          = data.get("mode","video")           # video | audio
    quality       = data.get("quality","best")
    audio_fmt     = data.get("audio_fmt","mp3")
    audio_quality = data.get("audio_quality","320")
    subs          = data.get("subs", False)
    thumbnail     = data.get("thumbnail", False)
    clip_start    = data.get("clip_start","").strip()
    clip_end      = data.get("clip_end","").strip()

    if not url:
        return jsonify({"error": "No URL"}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status":"queued","progress":0,"speed":"","eta":"","size":"","filename":"","error":""}

    t = threading.Thread(
        target=run_download,
        args=(job_id, url, mode, quality, audio_fmt, audio_quality,
              subs, thumbnail, clip_start, clip_end),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route("/api/file/<job_id>")
def serve_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if job.get("status") != "done":
        return jsonify({"error": "Not ready"}), 400
    filepath = job.get("filepath","")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath, as_attachment=True, download_name=job["filename"])

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
