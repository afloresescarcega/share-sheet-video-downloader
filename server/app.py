"""Tiny yt-dlp download server for the ShareDL iOS app.

Flow: POST /jobs {"url": ...} -> {"id": ...}
      GET  /jobs/{id}         -> {"status", "progress", "error", "title"}
      GET  /jobs/{id}/file    -> the finished MP4 (H.264/HEVC + AAC, Photos-safe)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

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

# Prefer streams Photos can play natively so we rarely need to re-encode.
FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/"
    "b[vcodec^=avc1][acodec^=mp4a]/"
    "bv*[height<=1080]+ba/b"
)

WORK_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="ShareDL")
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


def require_token(authorization: str = Header(default="")) -> None:
    if not TOKEN:
        return
    if not secrets.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="bad token")


class JobRequest(BaseModel):
    url: str


def probe_codecs(path: Path) -> tuple[str | None, str | None]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
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
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    if video == "h264":
        cmd += ["-c:v", "copy"]
    elif video == "hevc":
        cmd += ["-c:v", "copy", "-tag:v", "hvc1"]
    else:  # vp9 / av1 / anything else -> hardware H.264
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if audio == "aac" else ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", str(dst)]
    log.info("ffmpeg video=%s audio=%s", video, audio)
    subprocess.run(cmd, check=True, capture_output=True)


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
            info = ydl.extract_info(job.url, download=True)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next(e for e in info["entries"] if e)
            job.title = info.get("title")
        sources = [p for p in job_dir.iterdir() if p.name.startswith("source.") and p.suffix != ".part"]
        if not sources:
            raise RuntimeError("yt-dlp finished but produced no file")
        job.status = "processing"
        job.progress = 0.97
        final = job_dir / "video.mp4"
        make_photos_safe(sources[0], final)
        job.file = final
        job.progress = 1.0
        job.status = "done"
        log.info("done %s (%s)", job.url, job.title)
    except subprocess.CalledProcessError as e:
        job.status, job.error = "error", f"ffmpeg failed: {e.stderr.decode(errors='ignore')[-300:]}"
        log.error("job %s: %s", job.id, job.error)
    except Exception as e:  # yt-dlp raises DownloadError with a useful message
        job.status, job.error = "error", str(e).removeprefix("ERROR: ")[:500]
        log.error("job %s: %s", job.id, job.error)


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
def health() -> dict:
    return {"ok": True, "yt_dlp": yt_dlp.version.__version__}


@app.post("/jobs", dependencies=[Depends(require_token)])
def create_job(req: JobRequest) -> dict:
    if not req.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="not a URL")
    job = Job(id=uuid.uuid4().hex, url=req.url)
    with jobs_lock:
        jobs[job.id] = job
    executor.submit(run_job, job)
    log.info("queued %s", req.url)
    return {"id": job.id}


def get_job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    return job


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    return {"id": job.id, "status": job.status, "progress": job.progress, "title": job.title, "error": job.error}


@app.get("/jobs/{job_id}/file", dependencies=[Depends(require_token)])
def job_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job.status != "done" or not job.file:
        raise HTTPException(status_code=409, detail="not ready")
    return FileResponse(job.file, media_type="video/mp4", filename="video.mp4")
