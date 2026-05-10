import os, re, uuid, threading, requests
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/ytdl_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ── Your Cloudflare Worker URL ────────────────────────────────────
WORKER_URL = "https://alpha.kislayyadav02.workers.dev"

jobs = {}
jobs_lock = threading.Lock()

def worker_get(path, params={}):
    try:
        r = requests.get(f"{WORKER_URL}{path}", params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def run_download(job_id, stream_url, audio_url, filename, video_only):
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    filepath = os.path.join(job_dir, filename)

    with jobs_lock:
        jobs[job_id]["status"] = "downloading"

    try:
        if video_only and audio_url:
            # Download video + audio separately then merge with ffmpeg
            v_path = filepath + ".video.tmp"
            a_path = filepath + ".audio.tmp"

            for url, path, label in [(stream_url, v_path, "video"), (audio_url, a_path, "audio")]:
                with jobs_lock:
                    jobs[job_id]["status"] = f"downloading {label}"
                with requests.get(url, stream=True, timeout=60,
                    headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.youtube.com/"}) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    downloaded = 0
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total:
                                    with jobs_lock:
                                        jobs[job_id]["progress"] = round((downloaded/total)*50 if label=="video" else 50+round((downloaded/total)*45), 1)

            # Merge with ffmpeg
            with jobs_lock:
                jobs[job_id]["status"] = "processing"
                jobs[job_id]["progress"] = 95
            ret = os.system(f'ffmpeg -y -i "{v_path}" -i "{a_path}" -c copy "{filepath}" -loglevel quiet')
            os.remove(v_path)
            os.remove(a_path)
            if ret != 0:
                raise Exception("ffmpeg merge failed")

        else:
            # Direct stream download
            with requests.get(stream_url, stream=True, timeout=60,
                headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.youtube.com/"}) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                with jobs_lock:
                                    jobs[job_id]["progress"] = round((downloaded/total)*99, 1)

        with jobs_lock:
            jobs[job_id].update({
                "status"  : "done",
                "progress": 100,
                "filename": filename,
                "filepath": filepath,
            })

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
    if not url: return jsonify({"error":"No URL"}), 400
    data = worker_get("/info", {"url": url})
    if data.get("error"): return jsonify({"error": data["error"]}), 400
    return jsonify(data)

@app.route("/api/formats", methods=["POST"])
def get_formats():
    url = request.json.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    data = worker_get("/formats", {"url": url})
    if data.get("error"): return jsonify({"error": data["error"]}), 400
    # Flatten for table display
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
    if data.get("error"): return jsonify({"error": data["error"]}), 400
    return jsonify({"results": data.get("results", [])})

@app.route("/api/download", methods=["POST"])
def start_download():
    body      = request.json
    url       = body.get("url","").strip()
    mode      = body.get("mode","video")
    quality   = body.get("quality","720p")
    audio_fmt = body.get("audio_fmt","mp3")

    if not url: return jsonify({"error":"No URL"}), 400

    # Get stream info from Worker
    if mode == "audio":
        data = worker_get("/audio", {"url": url})
    else:
        data = worker_get("/download", {"url": url, "quality": quality, "type": "video"})

    if not data.get("success"):
        return jsonify({"error": data.get("error","Failed to get stream info")}), 400

    stream_url = data.get("stream_url") or data.get("download_url")
    audio_url  = data.get("audio_url")
    video_only = data.get("video_only", False)
    filename   = data.get("filename", f"video_{uuid.uuid4().hex[:8]}.mp4")

    # Clean filename
    filename = re.sub(r'[\\/*?:"<>|]', "_", filename)

    if not stream_url:
        return jsonify({"error":"No stream URL returned"}), 400

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status"  : "queued",
            "progress": 0,
            "speed"   : "",
            "eta"     : "",
            "filename": filename,
            "error"   : "",
        }

    threading.Thread(
        target=run_download,
        args=(job_id, stream_url, audio_url, filename, video_only),
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
        return jsonify({"error":"File not found"}), 404
    return send_file(fp, as_attachment=True, download_name=job["filename"])

@app.route("/health")
def health():
    return jsonify({"status":"ok","time":datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
