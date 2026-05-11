import os, re, uuid, threading, requests
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

WORKER_URL = "https://alpha.kislayyadav02.workers.dev"

jobs = {}
jobs_lock = threading.Lock()

def worker_get(path, params={}):
    try:
        r = requests.get(f"{WORKER_URL}{path}", params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# ── Download job ──────────────────────────────────────────────────
def run_download(job_id, stream_url, audio_url, filename, video_only):
    job_dir  = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    filepath = os.path.join(job_dir, filename)

    HEADERS = {
        "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer"        : "https://www.youtube.com/",
        "Accept-Encoding": "identity",
        "Accept"         : "*/*",
    }

    try:
        if video_only and audio_url:
            # Download video part
            v_path = filepath + ".vtmp"
            a_path = filepath + ".atmp"

            with jobs_lock:
                jobs[job_id]["status"] = "downloading video"

            _stream_to_file(stream_url, v_path, HEADERS, job_id, 0, 50)

            with jobs_lock:
                jobs[job_id]["status"] = "downloading audio"

            _stream_to_file(audio_url, a_path, HEADERS, job_id, 50, 95)

            with jobs_lock:
                jobs[job_id]["status"]   = "merging"
                jobs[job_id]["progress"] = 96

            ret = os.system(f'ffmpeg -y -i "{v_path}" -i "{a_path}" -c copy "{filepath}" -loglevel quiet')
            try:
                os.remove(v_path)
                os.remove(a_path)
            except:
                pass

            if ret != 0:
                raise Exception("ffmpeg merge failed. Is ffmpeg installed on Render?")

        else:
            with jobs_lock:
                jobs[job_id]["status"] = "downloading"

            _stream_to_file(stream_url, filepath, HEADERS, job_id, 0, 99)

        # Find final file
        files = [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
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

def _stream_to_file(url, path, headers, job_id, prog_start, prog_end):
    with requests.get(url, stream=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        total      = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=512 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = prog_start + (downloaded / total) * (prog_end - prog_start)
                        with jobs_lock:
                            jobs[job_id]["progress"] = round(pct, 1)
                            jobs[job_id]["downloaded"] = _fmt_size(downloaded)
                            jobs[job_id]["total"]      = _fmt_size(total)

def _fmt_size(b):
    if b > 1073741824: return f"{b/1073741824:.2f} GB"
    if b > 1048576:    return f"{b/1048576:.1f} MB"
    return f"{b/1024:.0f} KB"

# ── Routes ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    data = worker_get("/info", {"url": url})
    if not data.get("success"):
        return jsonify({"error": data.get("error","Failed")}), 400
    return jsonify(data)

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    data = worker_get("/formats", {"url": url})
    if not data.get("success"):
        return jsonify({"error": data.get("error","Failed")}), 400
    fmts = []
    for v in data.get("formats",{}).get("video",[]):
        fmts.append({**v, "type":"video"})
    for a in data.get("formats",{}).get("audio",[]):
        fmts.append({**a, "type":"audio"})
    return jsonify({"formats": fmts})

@app.route("/api/search", methods=["POST"])
def search():
    query = request.json.get("query","").strip()
    count = request.json.get("count", 6)
    if not query: return jsonify({"error":"No query"}), 400
    data = worker_get("/search", {"q": query, "limit": count})
    if not data.get("success"):
        return jsonify({"error": data.get("error","Search failed")}), 400
    return jsonify({"results": data.get("results", [])})

@app.route("/api/download", methods=["POST"])
def start_download():
    body    = request.json
    url     = body.get("url","").strip()
    mode    = body.get("mode","video")
    quality = body.get("quality","720p")

    if not url: return jsonify({"error":"No URL"}), 400

    # Get stream URLs from Worker
    if mode == "audio":
        data = worker_get("/audio", {"url": url})
    else:
        data = worker_get("/download", {"url": url, "quality": quality, "type": "video"})

    if not data.get("success"):
        return jsonify({"error": data.get("error","Could not get stream")}), 400

    stream_url = data.get("stream_url") or data.get("download_url")
    audio_url  = data.get("audio_url")
    video_only = data.get("video_only", False)
    filename   = re.sub(r'[\\/*?:"<>|]', "_", data.get("filename","video.mp4"))

    if not stream_url:
        return jsonify({"error":"No stream URL in response"}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status"    : "queued",
            "progress"  : 0,
            "filename"  : filename,
            "downloaded": "0 KB",
            "total"     : "?",
            "error"     : "",
        }

    threading.Thread(
        target=run_download,
        args=(job_id, stream_url, audio_url, filename, video_only),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id, "filename": filename})

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
        return jsonify({"error":"File missing on server"}), 404
    return send_file(fp, as_attachment=True, download_name=job["filename"])

@app.route("/health")
def health():
    return jsonify({"status":"ok","worker":WORKER_URL,"time":datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
