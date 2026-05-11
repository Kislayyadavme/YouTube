import os, re, uuid, threading, requests, subprocess
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

DOWNLOAD_DIR  = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
COOKIES_FILE  = os.path.join(os.path.dirname(__file__), "cookies.txt")
WORKER_URL    = "https://alpha.kislayyadav02.workers.dev"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs      = {}
jobs_lock = threading.Lock()

# ── Use yt-dlp with cookies directly (most reliable) ─────────────
def run_ytdlp(job_id, url, mode, quality, audio_fmt):
    job_dir  = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with jobs_lock:
        jobs[job_id]["status"] = "downloading"

    try:
        # Build yt-dlp command
        cmd = ["yt-dlp", "--no-playlist", "-o", f"{job_dir}/%(title)s.%(ext)s"]

        # Add cookies if file exists
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]

        # Add format
        if mode == "audio":
            cmd += [
                "-f", "bestaudio/best",
                "-x", "--audio-format", audio_fmt or "mp3",
                "--audio-quality", "0",
            ]
        else:
            qmap = {
                "4k"   :"bestvideo[height<=2160]+bestaudio/best",
                "2k"   :"bestvideo[height<=1440]+bestaudio/best",
                "1080p":"bestvideo[height<=1080]+bestaudio/best",
                "720p" :"bestvideo[height<=720]+bestaudio/best",
                "480p" :"bestvideo[height<=480]+bestaudio/best",
                "360p" :"bestvideo[height<=360]+bestaudio/best",
                "144p" :"bestvideo[height<=144]+bestaudio/best",
                "best" :"bestvideo+bestaudio/best",
            }
            fmt = qmap.get(quality, qmap["720p"])
            cmd += ["-f", fmt, "--merge-output-format", "mp4"]

        # Extra reliability options
        cmd += [
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", "4",
            "--no-warnings",
            "--geo-bypass",
            "--extractor-args", "youtube:player_client=ios,android,tv_embedded",
            url
        ]

        # Run yt-dlp
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines = []
        for line in proc.stdout:
            line = line.strip()
            output_lines.append(line)
            # Parse progress
            if "[download]" in line and "%" in line:
                try:
                    pct = float(re.search(r'(\d+\.?\d*)%', line).group(1))
                    with jobs_lock:
                        jobs[job_id]["progress"] = pct
                        # Parse speed and size
                        spd = re.search(r'at\s+(\S+)', line)
                        eta = re.search(r'ETA\s+(\S+)', line)
                        siz = re.search(r'of\s+(\S+)', line)
                        if spd: jobs[job_id]["speed"] = spd.group(1)
                        if eta: jobs[job_id]["eta"]   = eta.group(1)
                        if siz: jobs[job_id]["total"] = siz.group(1)
                except: pass
            elif "[Merger]" in line or "Merging" in line:
                with jobs_lock:
                    jobs[job_id]["status"]   = "merging"
                    jobs[job_id]["progress"] = 98
            elif "[ExtractAudio]" in line:
                with jobs_lock:
                    jobs[job_id]["status"]   = "converting"
                    jobs[job_id]["progress"] = 98

        proc.wait()

        if proc.returncode != 0:
            full_output = "\n".join(output_lines[-10:])
            raise Exception(f"yt-dlp failed: {full_output}")

        # Find downloaded file
        files = [
            f for f in os.listdir(job_dir)
            if os.path.isfile(os.path.join(job_dir, f))
            and not f.endswith(('.part', '.ytdl', '.tmp'))
        ]
        if not files:
            raise Exception("No output file found after download.")
        files.sort(key=lambda f: os.path.getmtime(os.path.join(job_dir, f)), reverse=True)

        with jobs_lock:
            jobs[job_id].update({
                "status"  : "done",
                "progress": 100,
                "filename": files[0],
                "filepath": os.path.join(job_dir, files[0]),
            })

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = str(e)

def worker_get(path, params={}):
    try:
        r = requests.get(f"{WORKER_URL}{path}", params=params, timeout=20)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def fmt_size(b):
    if b>1e9: return f"{b/1e9:.2f} GB"
    if b>1e6: return f"{b/1e6:.1f} MB"
    return f"{b/1024:.0f} KB"

# ── Routes ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    # Try Worker first (fast, no download needed)
    data = worker_get("/info", {"url": url})
    if data.get("success"):
        return jsonify(data)
    # Fallback: use yt-dlp locally
    try:
        import yt_dlp
        opts = {"quiet":True,"no_warnings":True}
        if os.path.exists(COOKIES_FILE):
            opts["cookiefile"] = COOKIES_FILE
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        d = int(info.get("duration",0))
        return jsonify({
            "success"    : True,
            "title"      : info.get("title","Unknown"),
            "channel"    : info.get("uploader","Unknown"),
            "thumbnail"  : info.get("thumbnail",""),
            "duration"   : f"{d//3600:02d}:{(d%3600)//60:02d}:{d%60:02d}",
            "views"      : info.get("view_count",0),
            "is_live"    : info.get("is_live",False),
            "source"     : "yt-dlp+cookies",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/search", methods=["POST"])
def search():
    query = request.json.get("query","").strip()
    count = request.json.get("count", 6)
    if not query: return jsonify({"error":"No query"}), 400
    data = worker_get("/search", {"q": query, "limit": count})
    if data.get("success"):
        return jsonify({"results": data.get("results",[])})
    return jsonify({"error": data.get("error","Search failed")}), 400

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    data = worker_get("/formats", {"url": url})
    if data.get("success"):
        fmts = []
        for v in data.get("formats",{}).get("video",[]): fmts.append({**v,"type":"video"})
        for a in data.get("formats",{}).get("audio",[]): fmts.append({**a,"type":"audio"})
        return jsonify({"formats": fmts})
    return jsonify({"error": data.get("error","Failed")}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    body      = request.json
    url       = body.get("url","").strip()
    mode      = body.get("mode","video")
    quality   = body.get("quality","720p")
    audio_fmt = body.get("audio_fmt","mp3")
    if not url: return jsonify({"error":"No URL"}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status":"queued","progress":0,
            "speed":"","eta":"","total":"",
            "filename":"","filepath":"","error":"",
        }

    threading.Thread(
        target=run_ytdlp,
        args=(job_id, url, mode, quality, audio_fmt),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job: return jsonify({"error":"Job not found"}), 404
    return jsonify(job)

@app.route("/api/file/<job_id>")
def serve_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id,{})
    if job.get("status") != "done":
        return jsonify({"error":"Not ready"}), 400
    fp = job.get("filepath","")
    if not fp or not os.path.exists(fp):
        return jsonify({"error":"File missing"}), 404
    return send_file(fp, as_attachment=True, download_name=job["filename"])

@app.route("/api/cookies-status")
def cookies_status():
    exists = os.path.exists(COOKIES_FILE)
    return jsonify({
        "has_cookies": exists,
        "message": "Cookies active ✅" if exists else "No cookies ❌ — bot errors may occur"
    })

@app.route("/health")
def health():
    return jsonify({"status":"ok","cookies":os.path.exists(COOKIES_FILE),"time":datetime.utcnow().isoformat()})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
