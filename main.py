import yt_dlp
import os
import sys
import json
import time
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
#                    CONFIGURATION & KEYS
# ═══════════════════════════════════════════════════════════════════

CONFIG = {
    "api_key"        : "AIzaSyDtGetp4ZbZ4YT3pWiCMHx4m65LhUTW1IE",
    "oauth_client_id": "141690089698-9nb4a8enm8vciu317bd92dlpb2aj1m07.apps.googleusercontent.com",
    "download_path"  : "downloads",
    "ffmpeg_path"    : None,   # Set to your ffmpeg path if not in system PATH e.g. "C:/ffmpeg/bin"
    "max_retries"    : 5,
    "concurrent_frags": 8,     # Parallel fragment downloads for speed
}

os.makedirs(CONFIG["download_path"], exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/videos",    exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/audio",     exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/playlists", exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/thumbnails",exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/subtitles", exist_ok=True)
os.makedirs(f"{CONFIG['download_path']}/shorts",    exist_ok=True)

# ═══════════════════════════════════════════════════════════════════
#                    COLORS & UI HELPERS
# ═══════════════════════════════════════════════════════════════════

class Colors:
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN    = '\033[96m'
    WHITE   = '\033[97m'
    BOLD    = '\033[1m'
    RESET   = '\033[0m'

def banner():
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║         🎬  YOUTUBE ULTIMATE DOWNLOADER  🎬                 ║
║              Full Featured • High Quality                    ║
╚══════════════════════════════════════════════════════════════╝
{Colors.RESET}""")

def print_success(msg): print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")
def print_error(msg):   print(f"{Colors.RED}❌ {msg}{Colors.RESET}")
def print_info(msg):    print(f"{Colors.CYAN}ℹ️  {msg}{Colors.RESET}")
def print_warn(msg):    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")
def print_header(msg):  print(f"\n{Colors.MAGENTA}{Colors.BOLD}{'═'*60}\n   {msg}\n{'═'*60}{Colors.RESET}")

def separator():
    print(f"{Colors.BLUE}{'─'*60}{Colors.RESET}")

# ═══════════════════════════════════════════════════════════════════
#                    PROGRESS HOOK
# ═══════════════════════════════════════════════════════════════════

download_start_time = None

def progress_hook(d):
    global download_start_time
    if d['status'] == 'downloading':
        if download_start_time is None:
            download_start_time = time.time()
        percent    = d.get('_percent_str', '?%').strip()
        speed      = d.get('_speed_str',   '?').strip()
        eta        = d.get('_eta_str',     '?').strip()
        downloaded = d.get('_downloaded_bytes_str', '?').strip()
        total      = d.get('_total_bytes_str') or d.get('_total_bytes_estimate_str', '?')
        if hasattr(total, 'strip'):
            total = total.strip()
        bar_len  = 30
        try:
            pct_val  = float(percent.replace('%',''))
            filled   = int(bar_len * pct_val / 100)
            bar      = '█' * filled + '░' * (bar_len - filled)
            bar_str  = f"[{bar}] {percent}"
        except:
            bar_str  = f"[{'░'*bar_len}] {percent}"
        print(f"\r{Colors.CYAN}⬇️  {bar_str} | {downloaded}/{total} | 🚀 {speed} | ⏱ ETA: {eta}   {Colors.RESET}", end="", flush=True)

    elif d['status'] == 'finished':
        elapsed = time.time() - download_start_time if download_start_time else 0
        download_start_time = None
        filename = os.path.basename(d.get('filename', ''))
        print(f"\n{Colors.GREEN}✅ Done in {elapsed:.1f}s → {filename}{Colors.RESET}")
        print_info("Merging / post-processing...")

    elif d['status'] == 'error':
        print_error("A download error occurred.")

# ═══════════════════════════════════════════════════════════════════
#                    GET VIDEO INFO
# ═══════════════════════════════════════════════════════════════════

def get_video_info(url, quiet=False):
    ydl_opts = {
        'quiet'           : True,
        'no_warnings'     : True,
        'extract_flat'    : False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not quiet:
                print_header("📋 VIDEO INFORMATION")
                print(f"  {Colors.BOLD}Title      :{Colors.RESET} {info.get('title','N/A')}")
                print(f"  {Colors.BOLD}Channel    :{Colors.RESET} {info.get('uploader','N/A')}")
                duration = info.get('duration', 0)
                print(f"  {Colors.BOLD}Duration   :{Colors.RESET} {duration//3600:02d}:{(duration%3600)//60:02d}:{duration%60:02d}")
                views = info.get('view_count', 0)
                print(f"  {Colors.BOLD}Views      :{Colors.RESET} {views:,}")
                likes = info.get('like_count', 0)
                print(f"  {Colors.BOLD}Likes      :{Colors.RESET} {likes:,}")
                print(f"  {Colors.BOLD}Upload Date:{Colors.RESET} {info.get('upload_date','N/A')}")
                print(f"  {Colors.BOLD}Description:{Colors.RESET} {str(info.get('description',''))[:120]}...")
                tags = info.get('tags', [])
                print(f"  {Colors.BOLD}Tags       :{Colors.RESET} {', '.join(tags[:5]) if tags else 'N/A'}")
                print(f"  {Colors.BOLD}URL        :{Colors.RESET} {url}")
            return info
    except Exception as e:
        print_error(f"Could not fetch video info: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════
#                    LIST AVAILABLE FORMATS
# ═══════════════════════════════════════════════════════════════════

def list_formats(url):
    print_header("📊 AVAILABLE FORMATS")
    ydl_opts = {'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            print(f"\n{'ID':<10} {'EXT':<6} {'RESOLUTION':<14} {'FPS':<6} {'SIZE':<12} {'CODEC':<20} {'NOTE'}")
            separator()
            for f in formats:
                fid   = f.get('format_id','?')
                ext   = f.get('ext','?')
                res   = f.get('resolution') or f'{f.get("width","?")}x{f.get("height","?")}'
                fps   = str(f.get('fps','?'))
                size  = f.get('filesize') or f.get('filesize_approx')
                size  = f"{size/1024/1024:.1f}MB" if size else "N/A"
                vcodec= f.get('vcodec','?')
                acodec= f.get('acodec','?')
                codec = f"{vcodec}/{acodec}"[:20]
                note  = f.get('format_note','')
                print(f"{fid:<10} {ext:<6} {res:<14} {fps:<6} {size:<12} {codec:<20} {note}")
    except Exception as e:
        print_error(f"Failed to list formats: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    BUILD YDL OPTIONS
# ═══════════════════════════════════════════════════════════════════

def build_ydl_opts(fmt, output_dir, filename_tmpl, extra_opts=None):
    opts = {
        'format'              : fmt,
        'outtmpl'             : f"{output_dir}/{filename_tmpl}",
        'merge_output_format' : 'mp4',
        'progress_hooks'      : [progress_hook],
        'retries'             : CONFIG['max_retries'],
        'fragment_retries'    : CONFIG['max_retries'],
        'concurrent_fragment_downloads': CONFIG['concurrent_frags'],
        'ignoreerrors'        : False,
        'no_warnings'         : False,
        'quiet'               : False,
        'verbose'             : False,
        'geo_bypass'          : True,
        'age_limit'           : 21,
        'http_headers'        : {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        },
    }
    if CONFIG['ffmpeg_path']:
        opts['ffmpeg_location'] = CONFIG['ffmpeg_path']
    if extra_opts:
        opts.update(extra_opts)
    return opts

# ═══════════════════════════════════════════════════════════════════
#                    QUALITY SELECTOR
# ═══════════════════════════════════════════════════════════════════

def choose_video_quality():
    print_header("🎯 SELECT VIDEO QUALITY")
    options = [
        ("1",  "4K  Ultra HD  (2160p)",  "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best"),
        ("2",  "2K  Quad HD   (1440p)",  "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best"),
        ("3",  "Full HD       (1080p)",  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best"),
        ("4",  "HD            (720p)",   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best"),
        ("5",  "SD            (480p)",   "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best"),
        ("6",  "Low           (360p)",   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best"),
        ("7",  "Lowest        (144p)",   "bestvideo[height<=144][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=144]+bestaudio/best"),
        ("8",  "Best Available (Auto)",  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"),
        ("9",  "Custom Format ID",       None),
    ]
    for opt in options:
        print(f"  {Colors.YELLOW}[{opt[0]}]{Colors.RESET} {opt[1]}")
    choice = input(f"\n{Colors.BOLD}Select quality [1-9]: {Colors.RESET}").strip()
    for opt in options:
        if choice == opt[0]:
            if opt[2] is None:
                fmt = input("Enter format ID (from list formats): ").strip()
                return fmt
            return opt[2]
    print_warn("Invalid choice, using best available.")
    return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

def choose_audio_quality():
    print_header("🎵 SELECT AUDIO QUALITY")
    options = [
        ("1", "320 kbps (Best)",   "320"),
        ("2", "256 kbps",          "256"),
        ("3", "192 kbps",          "192"),
        ("4", "128 kbps",          "128"),
        ("5", "96  kbps",          "96"),
        ("6", "64  kbps (Lowest)", "64"),
    ]
    for opt in options:
        print(f"  {Colors.YELLOW}[{opt[0]}]{Colors.RESET} {opt[1]}")
    choice = input(f"\n{Colors.BOLD}Select quality [1-6]: {Colors.RESET}").strip()
    for opt in options:
        if choice == opt[0]:
            return opt[2]
    return "320"

def choose_audio_format():
    print_header("🎵 SELECT AUDIO FORMAT")
    options = [
        ("1", "MP3  (Universal)"),
        ("2", "AAC  (Apple)"),
        ("3", "FLAC (Lossless)"),
        ("4", "WAV  (Uncompressed)"),
        ("5", "OGG  (Open Source)"),
        ("6", "OPUS (Best Compression)"),
        ("7", "M4A  (iTunes)"),
    ]
    codecs = {"1":"mp3","2":"aac","3":"flac","4":"wav","5":"vorbis","6":"opus","7":"m4a"}
    for opt in options:
        print(f"  {Colors.YELLOW}[{opt[0]}]{Colors.RESET} {opt[1]}")
    choice = input(f"\n{Colors.BOLD}Select format [1-7]: {Colors.RESET}").strip()
    return codecs.get(choice, "mp3")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD VIDEO
# ═══════════════════════════════════════════════════════════════════

def download_video(url):
    print_header("🎬 DOWNLOAD VIDEO")
    info = get_video_info(url, quiet=True)
    if not info:
        return
    print_info(f"Title: {info.get('title','Unknown')}")
    fmt     = choose_video_quality()
    out_dir = f"{CONFIG['download_path']}/videos"
    tmpl    = "%(title)s [%(height)sp] [%(id)s].%(ext)s"

    ask_subs = input(f"\n{Colors.BOLD}Download subtitles? (y/n): {Colors.RESET}").strip().lower()
    ask_thumb= input(f"{Colors.BOLD}Embed thumbnail?    (y/n): {Colors.RESET}").strip().lower()
    ask_chap = input(f"{Colors.BOLD}Embed chapters?     (y/n): {Colors.RESET}").strip().lower()

    extra = {
        'writethumbnail'    : ask_thumb == 'y',
        'embedthumbnail'    : ask_thumb == 'y',
        'addchapters'       : ask_chap  == 'y',
        'writesubtitles'    : ask_subs  == 'y',
        'subtitleslangs'    : ['en','auto'],
        'embedsubtitles'    : ask_subs  == 'y',
        'postprocessors'    : [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
        ],
    }
    if ask_thumb == 'y':
        extra['postprocessors'].append({'key': 'EmbedThumbnail'})
    if ask_subs == 'y':
        extra['postprocessors'].append({'key': 'FFmpegEmbedSubtitle'})
    if ask_chap == 'y':
        extra['postprocessors'].append({'key': 'FFmpegMetadata', 'add_chapters': True})

    opts = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Video saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD AUDIO
# ═══════════════════════════════════════════════════════════════════

def download_audio(url):
    print_header("🎵 DOWNLOAD AUDIO")
    info = get_video_info(url, quiet=True)
    if not info:
        return
    print_info(f"Title: {info.get('title','Unknown')}")
    codec   = choose_audio_format()
    quality = choose_audio_quality()
    out_dir = f"{CONFIG['download_path']}/audio"
    tmpl    = f"%(title)s [%(id)s].%(ext)s"

    extra = {
        'format'         : 'bestaudio/best',
        'postprocessors' : [{
            'key'             : 'FFmpegExtractAudio',
            'preferredcodec'  : codec,
            'preferredquality': quality,
        }, {
            'key'             : 'FFmpegMetadata',
            'add_metadata'    : True,
        }],
        'writethumbnail' : True,
        'embedthumbnail' : True if codec in ['mp3','m4a','aac'] else False,
    }
    if codec in ['mp3','m4a','aac']:
        extra['postprocessors'].append({'key': 'EmbedThumbnail'})

    opts = build_ydl_opts('bestaudio/best', out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Audio saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Audio download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD PLAYLIST
# ═══════════════════════════════════════════════════════════════════

def download_playlist(url):
    print_header("📋 DOWNLOAD PLAYLIST")
    ydl_flat = {'quiet': True, 'extract_flat': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_flat) as ydl:
            info = ydl.extract_info(url, download=False)
            total = len(info.get('entries', []))
            print_info(f"Playlist: {info.get('title','Unknown')} ({total} videos)")
    except Exception as e:
        print_error(f"Could not read playlist: {e}")
        return

    fmt     = choose_video_quality()
    out_dir = f"{CONFIG['download_path']}/playlists"
    tmpl    = "%(playlist_title)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s"

    start = input(f"\n{Colors.BOLD}Start from video # (default 1): {Colors.RESET}").strip()
    end   = input(f"{Colors.BOLD}End at video   # (default all): {Colors.RESET}").strip()
    extra = {
        'noplaylist'      : False,
        'playliststart'   : int(start) if start.isdigit() else 1,
        'playlistend'     : int(end)   if end.isdigit()   else None,
        'postprocessors'  : [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
            {'key': 'FFmpegMetadata', 'add_chapters': True},
        ],
        'ignoreerrors'    : True,
    }
    opts = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Playlist saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Playlist download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD SHORTS
# ═══════════════════════════════════════════════════════════════════

def download_shorts(url):
    print_header("📱 DOWNLOAD YOUTUBE SHORT")
    out_dir = f"{CONFIG['download_path']}/shorts"
    tmpl    = "%(title)s [%(id)s].%(ext)s"
    extra   = {
        'postprocessors': [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
        ],
    }
    opts = build_ydl_opts(
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        out_dir, tmpl, extra
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Short saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Short download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD THUMBNAIL
# ═══════════════════════════════════════════════════════════════════

def download_thumbnail(url):
    print_header("🖼️  DOWNLOAD THUMBNAIL")
    out_dir = f"{CONFIG['download_path']}/thumbnails"
    tmpl    = "%(title)s [%(id)s].%(ext)s"
    opts    = {
        'skip_download'  : True,
        'writethumbnail' : True,
        'outtmpl'        : f"{out_dir}/{tmpl}",
        'quiet'          : False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Thumbnail saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Thumbnail download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD SUBTITLES
# ═══════════════════════════════════════════════════════════════════

def download_subtitles(url):
    print_header("💬 DOWNLOAD SUBTITLES")
    print("  [1] English only")
    print("  [2] All languages")
    print("  [3] Auto-generated captions")
    print("  [4] Custom language code (e.g. fr, de, hi)")
    choice = input(f"\n{Colors.BOLD}Select [1-4]: {Colors.RESET}").strip()
    lang_map = {"1": ['en'], "2": ['all'], "3": ['en'], "4": None}
    langs = lang_map.get(choice, ['en'])
    if choice == "4":
        code  = input("Enter language code: ").strip()
        langs = [code]

    out_dir = f"{CONFIG['download_path']}/subtitles"
    tmpl    = "%(title)s [%(id)s].%(ext)s"
    opts    = {
        'skip_download'        : True,
        'writesubtitles'       : True,
        'writeautomaticsub'    : choice == '3',
        'subtitleslangs'       : langs,
        'subtitlesformat'      : 'srt',
        'outtmpl'              : f"{out_dir}/{tmpl}",
        'quiet'                : False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Subtitles saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Subtitle download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    BATCH / MULTI URL DOWNLOAD
# ═══════════════════════════════════════════════════════════════════

def batch_download():
    print_header("📦 BATCH DOWNLOAD")
    print_info("Enter URLs one per line. Press ENTER twice when done.")
    urls = []
    while True:
        line = input().strip()
        if line == "":
            break
        urls.append(line)
    if not urls:
        print_warn("No URLs entered.")
        return
    print_info(f"{len(urls)} URLs found.")
    fmt     = choose_video_quality()
    out_dir = f"{CONFIG['download_path']}/videos"
    tmpl    = "%(title)s [%(id)s].%(ext)s"
    extra   = {
        'ignoreerrors'  : True,
        'postprocessors': [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
        ],
    }
    opts = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download(urls)
        print_success(f"Batch download complete → {out_dir}/")
    except Exception as e:
        print_error(f"Batch download error: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    DOWNLOAD FROM TXT FILE
# ═══════════════════════════════════════════════════════════════════

def download_from_file():
    print_header("📄 DOWNLOAD FROM URL FILE")
    filepath = input(f"{Colors.BOLD}Enter path to .txt file (one URL per line): {Colors.RESET}").strip()
    if not os.path.exists(filepath):
        print_error("File not found.")
        return
    with open(filepath, 'r') as f:
        urls = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if not urls:
        print_warn("No URLs found in file.")
        return
    print_info(f"Found {len(urls)} URLs.")
    fmt     = choose_video_quality()
    out_dir = f"{CONFIG['download_path']}/videos"
    tmpl    = "%(title)s [%(id)s].%(ext)s"
    extra   = {'ignoreerrors': True}
    opts    = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download(urls)
        print_success("All downloads complete.")
    except Exception as e:
        print_error(f"Error: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    TRIM VIDEO / CLIP
# ═══════════════════════════════════════════════════════════════════

def download_clip(url):
    print_header("✂️  DOWNLOAD VIDEO CLIP (Trim)")
    print_info("Format: HH:MM:SS  e.g.  00:01:30")
    start = input(f"{Colors.BOLD}Start time: {Colors.RESET}").strip()
    end   = input(f"{Colors.BOLD}End time  : {Colors.RESET}").strip()
    out_dir = f"{CONFIG['download_path']}/videos"
    tmpl    = "%(title)s [CLIP %(id)s].%(ext)s"
    extra   = {
        'postprocessors': [{
            'key'            : 'FFmpegVideoRemuxer',
            'preferedformat' : 'mp4',
        }],
        'download_ranges'   : lambda _, __: [{'start_time': _ts(start), 'end_time': _ts(end)}],
        'force_keyframes_at_cuts': True,
    }
    fmt  = choose_video_quality()
    opts = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Clip saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Clip download failed: {e}")

def _ts(t):
    """Convert HH:MM:SS to seconds"""
    parts = list(map(int, t.split(':')))
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    elif len(parts) == 2:
        return parts[0]*60 + parts[1]
    return int(parts[0])

# ═══════════════════════════════════════════════════════════════════
#                    CHANNEL / USER ALL VIDEOS
# ═══════════════════════════════════════════════════════════════════

def download_channel(url):
    print_header("📺 DOWNLOAD ENTIRE CHANNEL")
    print_warn("This downloads ALL videos from a channel. May take very long!")
    confirm = input(f"{Colors.BOLD}Proceed? (yes/no): {Colors.RESET}").strip().lower()
    if confirm != 'yes':
        return
    fmt     = choose_video_quality()
    out_dir = f"{CONFIG['download_path']}/channels"
    os.makedirs(out_dir, exist_ok=True)
    tmpl    = "%(uploader)s/%(upload_date)s - %(title)s [%(id)s].%(ext)s"
    extra   = {
        'noplaylist'    : False,
        'ignoreerrors'  : True,
        'postprocessors': [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
            {'key': 'FFmpegMetadata'},
        ],
    }
    opts = build_ydl_opts(fmt, out_dir, tmpl, extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success(f"Channel saved to → {out_dir}/")
    except Exception as e:
        print_error(f"Channel download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    SAVE VIDEO INFO TO JSON
# ═══════════════════════════════════════════════════════════════════

def save_info_json(url):
    print_header("💾 SAVE VIDEO INFO TO JSON")
    info = get_video_info(url, quiet=True)
    if not info:
        return
    vid_id   = info.get('id', 'unknown')
    filename = f"{CONFIG['download_path']}/{vid_id}_info.json"
    safe     = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(safe, f, indent=2, ensure_ascii=False)
    print_success(f"Info saved to → {filename}")

# ═══════════════════════════════════════════════════════════════════
#                    LIVE STREAM DOWNLOAD
# ═══════════════════════════════════════════════════════════════════

def download_live(url):
    print_header("🔴 DOWNLOAD LIVE STREAM / ONGOING STREAM")
    print_warn("For live streams — this records the stream from now.")
    out_dir = f"{CONFIG['download_path']}/videos"
    tmpl    = "%(title)s [LIVE %(id)s].%(ext)s"
    extra   = {
        'live_from_start' : True,
        'wait_for_video'  : (5, 300),
        'postprocessors'  : [
            {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
        ],
    }
    opts = build_ydl_opts(
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        out_dir, tmpl, extra
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        print_success("Live stream recorded.")
    except Exception as e:
        print_error(f"Live download failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    SEARCH & DOWNLOAD
# ═══════════════════════════════════════════════════════════════════

def search_and_download():
    print_header("🔍 SEARCH YOUTUBE & DOWNLOAD")
    query   = input(f"{Colors.BOLD}Search query: {Colors.RESET}").strip()
    count   = input(f"{Colors.BOLD}How many results to show (default 5): {Colors.RESET}").strip()
    count   = int(count) if count.isdigit() else 5
    search_url = f"ytsearch{count}:{query}"

    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(search_url, download=False)
            entries = results.get('entries', [])
        if not entries:
            print_warn("No results found.")
            return
        print(f"\n{'#':<4} {'Title':<55} {'Duration':<12} {'Channel'}")
        separator()
        for i, e in enumerate(entries, 1):
            dur   = e.get('duration', 0)
            title = (e.get('title','?'))[:53]
            chan  = (e.get('uploader','?'))[:20]
            print(f"{i:<4} {title:<55} {dur//60}:{dur%60:02d}{'':<6} {chan}")
        choice = input(f"\n{Colors.BOLD}Select video number (or 0 to cancel): {Colors.RESET}").strip()
        if not choice.isdigit() or int(choice) == 0:
            return
        idx = int(choice) - 1
        if 0 <= idx < len(entries):
            vid_url = f"https://www.youtube.com/watch?v={entries[idx]['id']}"
            print_info(f"Selected: {entries[idx].get('title','?')}")
            download_video(vid_url)
    except Exception as e:
        print_error(f"Search failed: {e}")

# ═══════════════════════════════════════════════════════════════════
#                    CHECK DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════

def check_dependencies():
    print_header("🔧 CHECKING DEPENDENCIES")
    # yt-dlp
    try:
        import yt_dlp
        print_success(f"yt-dlp      version: {yt_dlp.version.__version__}")
    except ImportError:
        print_error("yt-dlp not installed. Run: pip install yt-dlp")

    # ffmpeg
    import shutil
    ffmpeg = shutil.which("ffmpeg") or (CONFIG['ffmpeg_path'] and os.path.exists(os.path.join(CONFIG['ffmpeg_path'],'ffmpeg.exe')))
    if ffmpeg:
        print_success(f"ffmpeg      found ✔")
    else:
        print_error("ffmpeg NOT found. Install from https://ffmpeg.org")
        print_info("Windows: choco install ffmpeg  OR  winget install ffmpeg")
        print_info("Mac:     brew install ffmpeg")
        print_info("Linux:   sudo apt install ffmpeg")

    # Python version
    pv = sys.version_info
    print_success(f"Python      {pv.major}.{pv.minor}.{pv.micro}")

# ═══════════════════════════════════════════════════════════════════
#                         MAIN MENU
# ═══════════════════════════════════════════════════════════════════

def main_menu():
    while True:
        banner()
        print(f"  {Colors.YELLOW}[1]{Colors.RESET}  📹  Download Video (Choose Quality)")
        print(f"  {Colors.YELLOW}[2]{Colors.RESET}  🎵  Download Audio Only (MP3/AAC/FLAC etc.)")
        print(f"  {Colors.YELLOW}[3]{Colors.RESET}  📋  Download Playlist")
        print(f"  {Colors.YELLOW}[4]{Colors.RESET}  📱  Download YouTube Short")
        print(f"  {Colors.YELLOW}[5]{Colors.RESET}  🖼️   Download Thumbnail")
        print(f"  {Colors.YELLOW}[6]{Colors.RESET}  💬  Download Subtitles / Captions")
        print(f"  {Colors.YELLOW}[7]{Colors.RESET}  📦  Batch Download (Multiple URLs)")
        print(f"  {Colors.YELLOW}[8]{Colors.RESET}  📄  Download from URL .txt File")
        print(f"  {Colors.YELLOW}[9]{Colors.RESET}  ✂️   Download Video Clip (Trim by time)")
        print(f"  {Colors.YELLOW}[10]{Colors.RESET} 📺  Download Entire Channel")
        print(f"  {Colors.YELLOW}[11]{Colors.RESET} 🔴  Download Live Stream")
        print(f"  {Colors.YELLOW}[12]{Colors.RESET} 🔍  Search YouTube & Download")
        print(f"  {Colors.YELLOW}[13]{Colors.RESET} 📊  List Available Formats")
        print(f"  {Colors.YELLOW}[14]{Colors.RESET} 📋  Get Video Info")
        print(f"  {Colors.YELLOW}[15]{Colors.RESET} 💾  Save Video Info to JSON")
        print(f"  {Colors.YELLOW}[16]{Colors.RESET} 🔧  Check Dependencies")
        print(f"  {Colors.YELLOW}[0]{Colors.RESET}  ❌  Exit")
        separator()
        choice = input(f"\n{Colors.BOLD}Select option: {Colors.RESET}").strip()

        url = None
        if choice in [str(i) for i in range(1, 16)] and choice not in ['7','8','12','16']:
            url = input(f"\n{Colors.BOLD}Enter YouTube URL: {Colors.RESET}").strip()
            if not url:
                print_warn("No URL entered.")
                continue

        actions = {
            "1" : lambda: download_video(url),
            "2" : lambda: download_audio(url),
            "3" : lambda: download_playlist(url),
            "4" : lambda: download_shorts(url),
            "5" : lambda: download_thumbnail(url),
            "6" : lambda: download_subtitles(url),
            "7" : lambda: batch_download(),
            "8" : lambda: download_from_file(),
            "9" : lambda: download_clip(url),
            "10": lambda: download_channel(url),
            "11": lambda: download_live(url),
            "12": lambda: search_and_download(),
            "13": lambda: list_formats(url),
            "14": lambda: get_video_info(url),
            "15": lambda: save_info_json(url),
            "16": lambda: check_dependencies(),
            "0" : lambda: sys.exit(print_info("Goodbye! 👋")),
        }

        action = actions.get(choice)
        if action:
            try:
                action()
            except KeyboardInterrupt:
                print_warn("\nCancelled by user.")
        else:
            print_error("Invalid option, try again.")

        input(f"\n{Colors.CYAN}Press ENTER to return to menu...{Colors.RESET}")

# ═══════════════════════════════════════════════════════════════════
#                    ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print_warn("\n\nExiting...")
        sys.exit(0)
