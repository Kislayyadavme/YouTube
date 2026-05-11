import os, re, uuid, threading, subprocess, json
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()

def has_cookies():
    return os.path.exists(COOKIES_FILE)

def base_cmd():
    cmd = ["yt-dlp"]
    if has_cookies():
        cmd += ["--cookies", COOKIES_FILE]
    cmd += [
        "--geo-bypass",
        "--retries", "10",
        "--fragment-retries", "10",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=ios,android,web",
    ]
    return cmd

def ytdlp_info(url):
    cmd = base_cmd() + ["--dump-json", "--no-playlist", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise Exception(r.stderr.strip() or r.stdout.strip())
    return json.loads(r.stdout.strip().split("\n")[0])

def ytdlp_formats(url):
    cmd = base_cmd() + ["--dump-json", "--no-playlist", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise Exception(r.stderr.strip() or r.stdout.strip())
    info = json.loads(r.stdout.strip().split("\n")[0])
    fmts = []
    for f in info.get("formats", []):
        fmts.append({
            "id"     : str(f.get("format_id","?")),
            "ext"    : f.get("ext","?"),
            "quality": f.get("format_note") or f.get("quality","?"),
            "res"    : f.get("resolution") or f"{f.get('width','?')}x{f.get('height','?')}",
            "fps"    : str(f.get("fps","?")),
            "size"   : _fmt_size(f.get("filesize") or f.get("filesize_approx") or 0),
            "type"   : "video" if f.get("vcodec","none") != "none" else "audio",
            "vcodec" : f.get("vcodec","?"),
            "acodec" : f.get("acodec","?"),
        })
    return fmts

def _fmt_size(b):
    if not b: return "N/A"
    if b > 1e9: return f"{b/1e9:.2f} GB"
    if b > 1e6: return f"{b/1e6:.1f} MB"
    return f"{b/1024:.0f} KB"

def run_download(job_id, url, mode, quality, audio_fmt):
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with jobs_lock:
        jobs[job_id]["status"] = "starting"

    try:
        cmd = base_cmd() + [
            "--no-playlist",
            "-o", f"{job_dir}/%(title)s.%(ext)s",
            "--newline",
        ]

        if mode == "audio":
            cmd += [
                "-f", "bestaudio/best",
                "-x",
                "--audio-format", audio_fmt or "mp3",
                "--audio-quality", "0",
            ]
        else:
            # KEY FIX: use simple fallback format that always works
            qmap = {
                "4k"   : "bestvideo[height<=2160]+bestaudio/bestvideo+bestaudio/best",
                "2k"   : "bestvideo[height<=1440]+bestaudio/bestvideo+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
                "720p" : "bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best",
                "480p" : "bestvideo[height<=480]+bestaudio/bestvideo+bestaudio/best",
                "360p" : "bestvideo[height<=360]+bestaudio/bestvideo+bestaudio/best",
                "144p" : "bestvideo[height<=144]+bestaudio/bestvideo+bestaudio/best",
                "best" : "bestvideo+bestaudio/best",
            }
            fmt = qmap.get(quality, "bestvideo+bestaudio/best")
            cmd += [
                "-f", fmt,
                "--merge-output-format", "mp4",
            ]

        cmd.append(url)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        for line in proc.stdout:
            line = line.strip()
            if not line: continue
            if "[download]" in line and "%" in line:
                try:
                    pct = float(re.search(r'(\d+\.?\d*)%', line).group(1))
                    spd = re.search(r'at\s+(\S+/s)', line)
                    eta = re.search(r'ETA\s+(\S+)', line)
                    siz = re.search(r'of\s+~?(\S+)', line)
                    with jobs_lock:
                        jobs[job_id]["progress"] = round(pct, 1)
                        jobs[job_id]["status"]   = "downloading"
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
            raise Exception("Download failed. Please re-export and upload cookies.txt")

        files = [
            f for f in os.listdir(job_dir)
            if os.path.isfile(os.path.join(job_dir, f))
            and not f.endswith((".part", ".ytdl", ".tmp"))
        ]
        if not files:
            raise Exception("No file found after download.")
        files.sort(key=lambda f: os.path.getmtime(os.path.join(job_dir, f)), reverse=True)

        with jobs_lock:
            jobs[job_id].update({
                "status"  : "done",
                "progress": 100,
                "filename": files[0],
                "filepath": os.path.join(job_dir, files[0]),
                "speed"   : "",
                "eta"     : "",
            })

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = str(e)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    try:
        info = ytdlp_info(url)
        d = int(info.get("duration") or 0)
        return jsonify({
            "success"    : True,
            "title"      : info.get("title","Unknown"),
            "channel"    : info.get("uploader","Unknown"),
            "thumbnail"  : info.get("thumbnail",""),
            "duration"   : f"{d//3600:02d}:{(d%3600)//60:02d}:{d%60:02d}",
            "views"      : int(info.get("view_count") or 0),
            "likes"      : int(info.get("like_count") or 0),
            "upload_date": info.get("upload_date",""),
            "is_live"    : bool(info.get("is_live", False)),
            "source"     : "yt-dlp + cookies ✅" if has_cookies() else "yt-dlp ⚠️ no cookies",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    try:
        fmts = ytdlp_formats(url)
        return jsonify({"formats": fmts})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/search", methods=["POST"])
def search():
    query = request.json.get("query","").strip()
    count = int(request.json.get("count", 6))
    if not query: return jsonify({"error":"No query"}), 400
    try:
        cmd = base_cmd() + [
            "--dump-json", "--flat-playlist",
            "--no-warnings", f"ytsearch{count}:{query}"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        results = []
        for line in r.stdout.strip().split("\n"):
            if not line.strip(): continue
            try:
                v   = json.loads(line)
                dur = int(v.get("duration") or 0)
                results.append({
                    "id"       : v.get("id",""),
                    "title"    : v.get("title","?"),
                    "channel"  : v.get("uploader") or v.get("channel","?"),
                    "duration" : f"{dur//60}:{dur%60:02d}",
                    "views"    : int(v.get("view_count") or 0),
                    "thumbnail": v.get("thumbnail",""),
                    "url"      : f"https://www.youtube.com/watch?v={v.get('id','')}",
                })
            except: pass
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

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
        target=run_download,
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
        job = jobs.get(job_id, {})
    if job.get("status") != "done":
        return jsonify({"error":"Not ready"}), 400
    fp = job.get("filepath","")
    if not fp or not os.path.exists(fp):
        return jsonify({"error":"File missing"}), 404
    return send_file(fp, as_attachment=True, download_name=job["filename"])

@app.route("/api/cookies-status")
def cookies_status():
    return jsonify({
        "has_cookies": has_cookies(),
        "message": "✅ Cookies active" if has_cookies() else "❌ No cookies found on server",
    })

@app.route("/health")
def health():
    return jsonify({
        "status" : "ok",
        "cookies": has_cookies(),
        "cookies_path": COOKIES_FILE,
        "time"   : datetime.utcnow().isoformat(),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
