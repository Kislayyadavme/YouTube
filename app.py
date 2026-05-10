import os
import re
import json
import uuid
import threading
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()

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
                job["speed"]  = d.get("_speed_str",  "").strip()
                job["eta"]    = d.get("_eta_str",    "").strip()
                job["status"] = "downloading"
            elif d["status"] == "finished":
                job["progress"] = 99
                job["status"]   = "processing"
            elif d["status"] == "error":
                job["status"] = "error"
                job["error"]  = "Download error"
    return hook

QUALITY_MAP = {
    "4k"   : "bestvideo[height<=2160]+bestaudio/best",
    "2k"   : "bestvideo[height<=1440]+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best",
    "720p" : "bestvideo[height<=720]+bestaudio/best",
    "480p" : "bestvideo[height<=480]+bestaudio/best",
    "360p" : "bestvideo[height<=360]+bestaudio/best",
    "144p" : "bestvideo[height<=144]+bestaudio/best",
    "best" : "bestvideo+bestaudio/best",
}

AUDIO_CODEC_MAP = {
    "mp3":"mp3","aac":"aac","flac":"flac",
    "wav":"wav","ogg":"vorbis","opus":"opus","m4a":"m4a",
}

# ── Anti-bot options ──────────────────────────────────────────────
def get_base_opts():
    return {
        "quiet"       : True,
        "no_warnings" : True,
        "geo_bypass"  : True,
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android", "ios"],
                "player_skip"  : ["webpage", "configs"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "socket_timeout": 30,
        "retries"       : 10,
        "fragment_retries": 10,
    }

def safe_duration(duration):
    try:
        d = int(duration or 0)
        return f"{d//3600:02d}:{(d%3600)//60:02d}:{d%60:02d}"
    except:
        return "00:00:00"

def safe_int(val):
    try:
        return int(val or 0)
    except:
        return 0

# ── Background worker ─────────────────────────────────────────────
def run_download(job_id, url, mode, quality, audio_fmt, audio_quality,
                 subs, thumbnail, clip_start, clip_end):
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    opts = {
        **get_base_opts(),
        "outtmpl"    : os.path.join(job_dir, "%(title)s.%(ext)s"),
        "progress_hooks": [make_progress_hook(job_id)],
        "concurrent_fragment_downloads": 4,
        "quiet"      : False,
        "no_warnings": False,
    }

    try:
        if mode == "audio":
            codec = AUDIO_CODEC_MAP.get(audio_fmt, "mp3")
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": codec,
                 "preferredquality": audio_quality or "320"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
        else:
            fmt = QUALITY_MAP.get(quality, QUALITY_MAP["best"])
            pps = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
            opts["format"]              = fmt
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"]      = pps
            if subs:
                opts["writesubtitles"] = True
                opts["subtitleslangs"] = ["en", "auto"]
                opts["embedsubtitles"] = True
                pps.append({"key": "FFmpegEmbedSubtitle"})
            if thumbnail:
                opts["writethumbnail"] = True
                opts["embedthumbnail"] = True
                pps.append({"key": "EmbedThumbnail"})
            if clip_start and clip_end:
                def _ts(t):
                    parts = list(map(int, t.split(":")))
                    if len(parts)==3: return parts[0]*3600+parts[1]*60+parts[2]
                    if len(parts)==2: return parts[0]*60+parts[1]
                    return int(parts[0])
                opts["download_ranges"]         = lambda *_: [{"start_time":_ts(clip_start),"end_time":_ts(clip_end)}]
                opts["force_keyframes_at_cuts"] = True

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        files = [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
        if not files:
            raise Exception("No output file found.")
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

# ── Routes ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    url = request.json.get("url","").strip()
    if not url:
        return jsonify({"error":"No URL provided"}), 400
    try:
        opts = {**get_base_opts(), "quiet":True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return jsonify({
            "title"      : info.get("title","Unknown"),
            "channel"    : info.get("uploader","Unknown"),
            "thumbnail"  : info.get("thumbnail",""),
            "duration"   : safe_duration(info.get("duration",0)),
            "views"      : f"{safe_int(info.get('view_count',0)):,}",
            "likes"      : f"{safe_int(info.get('like_count',0)):,}",
            "upload_date": str(info.get("upload_date","")),
            "is_live"    : bool(info.get("is_live",False)),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url","").strip()
    if not url:
        return jsonify({"error":"No URL"}), 400
    try:
        opts = {**get_base_opts()}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        fmts = []
        for f in info.get("formats",[]):
            size = f.get("filesize") or f.get("filesize_approx")
            fmts.append({
                "id"    : str(f.get("format_id","?")),
                "ext"   : str(f.get("ext","?")),
                "res"   : str(f.get("resolution") or f"{f.get('width','?')}x{f.get('height','?')}"),
                "fps"   : str(f.get("fps","?")),
                "size"  : f"{size/1024/1024:.1f}MB" if size else "N/A",
                "note"  : str(f.get("format_note","")),
                "vcodec": str(f.get("vcodec","?")),
                "acodec": str(f.get("acodec","?")),
            })
        return jsonify({"formats": fmts})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/search", methods=["POST"])
def search():
    query = request.json.get("query","").strip()
    count = request.json.get("count", 6)
    if not query:
        return jsonify({"error":"No query"}), 400
    try:
        opts = {**get_base_opts(), "extract_flat":True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
        entries = []
        for e in results.get("entries",[]):
            # Fix: safely convert duration to int first
            dur = 0
            try:
                dur = int(float(e.get("duration") or 0))
            except:
                dur = 0
            entries.append({
                "id"       : str(e.get("id","")),
                "title"    : str(e.get("title","?")),
                "channel"  : str(e.get("uploader") or e.get("channel") or "?"),
                "duration" : f"{dur//60}:{dur%60:02d}",
                "thumbnail": str(e.get("thumbnail","")),
                "url"      : f"https://www.youtube.com/watch?v={e.get('id','')}",
            })
        return jsonify({"results": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data          = request.json
    url           = data.get("url","").strip()
    mode          = data.get("mode","video")
    quality       = data.get("quality","best")
    audio_fmt     = data.get("audio_fmt","mp3")
    audio_quality = data.get("audio_quality","320")
    subs          = data.get("subs", False)
    thumbnail     = data.get("thumbnail", False)
    clip_start    = data.get("clip_start","").strip()
    clip_end      = data.get("clip_end","").strip()

    if not url:
        return jsonify({"error":"No URL"}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status":"queued","progress":0,"speed":"","eta":"","filename":"","error":""}

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
        return jsonify({"error":"Job not found"}), 404
    return jsonify(job)

@app.route("/api/file/<job_id>")
def serve_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if job.get("status") != "done":
        return jsonify({"error":"Not ready"}), 400
    filepath = job.get("filepath","")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error":"File not found"}), 404
    return send_file(filepath, as_attachment=True, download_name=job["filename"])

@app.route("/health")
def health():
    return jsonify({"status":"ok","time":datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
