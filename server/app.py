"""Tiny yt-dlp download server for the ShareDL iOS app.

Flow: POST /jobs {"url": ...} -> {"id": ...}
      GET  /jobs/{id}         -> {"status", "progress", "error", "title"}
      GET  /jobs/{id}/file    -> the finished MP4 (H.264/HEVC + AAC, Photos-safe)
"""

from __future__ import annotations

import errno
import importlib.util
import ipaddress
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

log = logging.getLogger("sharedl")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("SHAREDL_WORK_DIR", ROOT / "downloads"))
TOKEN = os.environ.get("SHAREDL_TOKEN", "")
COOKIES_FILE = os.environ.get("SHAREDL_COOKIES")  # optional Netscape cookies.txt
JOB_TTL_SECONDS = 60 * 60
MAX_ACTIVE_JOBS = int(os.environ.get("SHAREDL_MAX_ACTIVE_JOBS", "6"))
MAX_FILESIZE = int(os.environ.get("SHAREDL_MAX_FILESIZE_MB", "2048")) * 1024 * 1024
MAX_DURATION = int(os.environ.get("SHAREDL_MAX_DURATION_MIN", "180")) * 60
SUBPROCESS_TIMEOUT = 15 * 60

if len(TOKEN) < 32:
    raise SystemExit("SHAREDL_TOKEN must be set (32+ chars). Run server/scripts/install.sh to generate one.")


# --- Outbound connection guard -------------------------------------------------
# Every outbound TCP connection this process makes (yt-dlp's urllib/requests/
# websockets handlers, redirects, embedded URLs, manifests, fragments) goes through
# socket.socket.connect. Checking the address actually being connected to blocks
# redirects to private IPs and DNS rebinding, which a check of the submitted URL alone can't.

class BlockedDestination(OSError):
    pass


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _vetted_address(sock: socket.socket, address):
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return address  # unix sockets etc.
    host, port, *_ = address
    try:
        ip = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        # A hostname: resolve it here and connect to the exact address we checked.
        infos = socket.getaddrinfo(host, port, sock.family, socket.SOCK_STREAM)
        if not infos:
            raise BlockedDestination(errno.EHOSTUNREACH, f"cannot resolve {host}")
        address = infos[0][4]
        ip = ipaddress.ip_address(address[0].split("%")[0])
    if not _is_public(ip):
        raise BlockedDestination(errno.EACCES, f"blocked connection to non-public address {ip}")
    return address


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _guarded_connect(self, address):
    return _real_connect(self, _vetted_address(self, address))


def _guarded_connect_ex(self, address):
    return _real_connect_ex(self, _vetted_address(self, address))


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex

# curl_cffi does its networking in C, out of reach of the guard above.
if importlib.util.find_spec("curl_cffi"):
    raise SystemExit("curl_cffi is installed in the server venv; it bypasses the connection guard. Uninstall it.")

# Some downloaders run an external program (ffmpeg, rtmpdump, curl, wget, aria2c,
# axel, httpie) that opens its own sockets, out of reach of the guard above.
# yt-dlp's subprocess downloaders all live in downloader/external.py (ExternalFD
# and its subclasses) and downloader/rtmp.py, so refuse every one of them.
from yt_dlp.downloader.external import ExternalFD  # noqa: E402
from yt_dlp.downloader.rtmp import RtmpFD  # noqa: E402


def _refuse_external_download(self, filename, info_dict):
    raise yt_dlp.utils.DownloadError(
        "this stream needs an external program to download it, which ShareDL disables for safety"
    )


ExternalFD.real_download = _refuse_external_download
RtmpFD.real_download = _refuse_external_download

# Prefer streams Photos can play natively so we rarely need to re-encode.
FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/"
    "b[vcodec^=avc1][acodec^=mp4a]/"
    "bv*[height<=1080]+ba/b"
)

WORK_DIR.mkdir(parents=True, exist_ok=True)
# No interactive docs or schema: nothing about the API is visible without the token.
app = FastAPI(title="ShareDL", docs_url=None, redoc_url=None, openapi_url=None)
executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class Job:
    id: str
    url: str
    status: str = "queued"  # queued | downloading | processing | done | error
    progress: float = 0.0
    title: str | None = None
    error: str | None = None
    file: Path | None = None
    created: float = field(default_factory=time.time)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


def token_ok(authorization: str) -> bool:
    return secrets.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode())


def require_token(authorization: Annotated[str, Header()] = "") -> None:
    if not token_ok(authorization):
        raise HTTPException(status_code=401, detail="bad token")


def check_public_url(url: str) -> None:
    """Fail fast on URLs that obviously point at private addresses.

    This is only an early, friendly error. The real enforcement is the
    connection guard above, which also covers redirects and DNS rebinding.
    """
    if len(url) > 2048:
        raise HTTPException(status_code=400, detail="URL too long")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=400, detail="not an http(s) URL")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise HTTPException(status_code=400, detail="host does not resolve")
    for info in infos:
        if not _is_public(ipaddress.ip_address(info[4][0].split("%")[0])):
            raise HTTPException(status_code=400, detail="private or local addresses are not allowed")


class JobRequest(BaseModel):
    url: str


def probe_codecs(path: Path) -> tuple[str | None, str | None]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    video = audio = None
    for s in json.loads(out).get("streams", []):
        if s.get("codec_type") == "video" and video is None:
            video = s.get("codec_name")
        elif s.get("codec_type") == "audio" and audio is None:
            audio = s.get("codec_name")
    return video, audio


def make_photos_safe(src: Path, dst: Path) -> None:
    """Remux (or re-encode only when needed) into an MP4 the iOS Photos app accepts."""
    video, audio = probe_codecs(src)
    cmd = ["ffmpeg", "-y", "-v", "error", "-protocol_whitelist", "file", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    if video == "h264":
        cmd += ["-c:v", "copy"]
    elif video == "hevc":
        cmd += ["-c:v", "copy", "-tag:v", "hvc1"]
    else:  # vp9 / av1 / anything else -> hardware H.264
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if audio == "aac" else ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", str(dst)]
    log.info("ffmpeg video=%s audio=%s", video, audio)
    subprocess.run(cmd, check=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT)


def run_job(job: Job) -> None:
    job_dir = WORK_DIR / job.id
    job_dir.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                job.progress = min(0.95, d.get("downloaded_bytes", 0) / total)

    opts = {
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(job_dir / "source.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",  # a playlist/channel URL downloads one video, not hundreds
        "max_filesize": MAX_FILESIZE,
        "match_filter": yt_dlp.utils.match_filter_func(f"!is_live & duration <=? {MAX_DURATION}"),
        "external_downloader": {"default": "native"},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "restrictfilenames": True,
    }
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    try:
        job.status = "downloading"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(job.url, download=True) or {}
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next((e for e in info["entries"] if e), {})
            job.title = info.get("title")
        sources = [p for p in job_dir.iterdir() if p.name.startswith("source.") and p.suffix != ".part"]
        if not sources:
            raise RuntimeError(
                f"No video downloaded. Live streams, videos over {MAX_DURATION // 60} min "
                f"and files over {MAX_FILESIZE // 2**20} MB are skipped."
            )
        job.status = "processing"
        job.progress = 0.97
        final = job_dir / "video.mp4"
        make_photos_safe(sources[0], final)
        job.file = final
        job.progress = 1.0
        job.status = "done"
        log.info("job %s done: %s (%s)", job.id, job.url, job.title)
    except subprocess.TimeoutExpired:
        fail_job(job, "conversion timed out")
    except subprocess.CalledProcessError as e:
        fail_job(job, f"ffmpeg failed: {e.stderr.decode(errors='ignore')[-300:]}")
    except Exception as e:  # yt-dlp raises DownloadError with a useful message
        fail_job(job, str(e).removeprefix("ERROR: ")[:500])


def fail_job(job: Job, error: str) -> None:
    job.status, job.error = "error", error
    log.error("job %s: %s", job.id, error)


def cleanup_loop() -> None:
    while True:
        time.sleep(300)
        cutoff = time.time() - JOB_TTL_SECONDS
        with jobs_lock:
            for job_id in [j.id for j in jobs.values() if j.created < cutoff]:
                jobs.pop(job_id, None)
        # Sweep by age on disk too, so folders left over from a restart get removed.
        for d in WORK_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


threading.Thread(target=cleanup_loop, daemon=True).start()


@app.get("/health")
def health(authorization: Annotated[str, Header()] = "") -> dict:
    if not token_ok(authorization):
        return {"ok": True}  # liveness only; version details need the token
    return {"ok": True, "yt_dlp": yt_dlp.version.__version__}


AUTH_ERROR = {401: {"description": "Missing or wrong bearer token"}}
NOT_FOUND = {404: {"description": "Unknown job"}}


@app.post(
    "/jobs",
    dependencies=[Depends(require_token)],
    responses={
        **AUTH_ERROR,
        400: {"description": "URL is not public http(s), too long, or does not resolve"},
        429: {"description": "Too many downloads in progress"},
    },
)
def create_job(req: JobRequest) -> dict:
    check_public_url(req.url)
    job = Job(id=uuid.uuid4().hex, url=req.url)
    with jobs_lock:
        active = sum(j.status in ("queued", "downloading", "processing") for j in jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="too many downloads in progress, try again shortly")
        jobs[job.id] = job
    executor.submit(run_job, job)
    log.info("job %s queued", job.id)  # the URL is logged by run_job, not echoed from the request
    return {"id": job.id}


def get_job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    return job


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)], responses={**AUTH_ERROR, **NOT_FOUND})
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    return {"id": job.id, "status": job.status, "progress": job.progress, "title": job.title, "error": job.error}


@app.get(
    "/jobs/{job_id}/file",
    dependencies=[Depends(require_token)],
    responses={**AUTH_ERROR, **NOT_FOUND, 409: {"description": "Job has not finished"}},
)
def job_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job.status != "done" or not job.file:
        raise HTTPException(status_code=409, detail="not ready")
    return FileResponse(job.file, media_type="video/mp4", filename="video.mp4")
