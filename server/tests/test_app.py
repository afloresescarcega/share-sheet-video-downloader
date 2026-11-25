import socket
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

import app

AUTH = f"Bearer {app.TOKEN}"


@pytest.fixture(autouse=True)
def clean_jobs(monkeypatch):
    app.jobs.clear()
    submitted = []
    monkeypatch.setattr(app.executor, "submit", lambda fn, *args: submitted.append((fn, args)))
    yield submitted
    app.jobs.clear()


def add_job(**fields) -> app.Job:
    job = app.Job(id=fields.pop("id", "job1"), url="https://example.com/v", **fields)
    app.jobs[job.id] = job
    return job


# --- auth & health -------------------------------------------------------------

def test_token_ok():
    assert app.token_ok(AUTH)
    assert not app.token_ok("Bearer wrong")
    assert not app.token_ok("")


def test_require_token_rejects_bad_token():
    app.require_token(AUTH)
    with pytest.raises(HTTPException) as e:
        app.require_token("Bearer nope")
    assert e.value.status_code == 401


def test_health_hides_version_without_token():
    assert app.health("") == {"ok": True}
    assert set(app.health(AUTH)) == {"ok", "yt_dlp"}


# --- URL checks ------------------------------------------------------------------

@pytest.mark.parametrize(
    "url, detail",
    [
        ("https://example.com/" + "a" * 2048, "URL too long"),
        ("ftp://example.com/x", "not an http(s) URL"),
        ("https:///nohost", "not an http(s) URL"),
        ("http://127.0.0.1/x", "private or local addresses are not allowed"),
        ("http://[::1]/x", "private or local addresses are not allowed"),
        ("http://10.0.0.5:8080/x", "private or local addresses are not allowed"),
    ],
)
def test_check_public_url_rejects(url, detail):
    with pytest.raises(HTTPException) as e:
        app.check_public_url(url)
    assert e.value.status_code == 400
    assert e.value.detail == detail


def test_check_public_url_unresolvable(monkeypatch):
    def fail(*_args, **_kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(app.socket, "getaddrinfo", fail)
    with pytest.raises(HTTPException) as e:
        app.check_public_url("https://does-not-exist.invalid/")
    assert e.value.detail == "host does not resolve"


def test_check_public_url_accepts_public_ip():
    app.check_public_url("https://93.184.215.14/video")


# --- connection guard ------------------------------------------------------------

def test_is_public():
    from ipaddress import ip_address

    assert app._is_public(ip_address("93.184.215.14"))
    assert not app._is_public(ip_address("192.168.1.1"))
    assert not app._is_public(ip_address("::ffff:127.0.0.1"))


def test_vetted_address_blocks_private_ip():
    with socket.socket(socket.AF_INET) as s, pytest.raises(app.BlockedDestination):
        app._vetted_address(s, ("127.0.0.1", 80))


def test_vetted_address_resolves_hostnames(monkeypatch):
    monkeypatch.setattr(app.socket, "getaddrinfo", lambda *a: [(0, 0, 0, "", ("93.184.215.14", 443))])
    with socket.socket(socket.AF_INET) as s:
        assert app._vetted_address(s, ("example.com", 443)) == ("93.184.215.14", 443)


def test_vetted_address_unresolvable(monkeypatch):
    monkeypatch.setattr(app.socket, "getaddrinfo", lambda *a: [])
    with socket.socket(socket.AF_INET) as s, pytest.raises(app.BlockedDestination):
        app._vetted_address(s, ("example.com", 443))


def test_vetted_address_ignores_unix_sockets():
    with socket.socket(socket.AF_UNIX) as s:
        assert app._vetted_address(s, "/tmp/x.sock") == "/tmp/x.sock"


def test_guarded_connect_blocks_loopback():
    with socket.socket(socket.AF_INET) as s:
        with pytest.raises(app.BlockedDestination):
            s.connect(("127.0.0.1", 9))
        with pytest.raises(app.BlockedDestination):
            s.connect_ex(("127.0.0.1", 9))


def test_external_downloaders_are_refused():
    with pytest.raises(app.yt_dlp.utils.DownloadError):
        app._refuse_external_download(None, "f", {})


# --- routes ----------------------------------------------------------------------

def test_create_job_queues_work(clean_jobs):
    result = app.create_job(app.JobRequest(url="https://93.184.215.14/v"))
    assert result["id"] in app.jobs
    assert clean_jobs == [(app.run_job, (app.jobs[result["id"]],))]


def test_create_job_limits_active_jobs(monkeypatch):
    monkeypatch.setattr(app, "MAX_ACTIVE_JOBS", 1)
    add_job(status="downloading")
    with pytest.raises(HTTPException) as e:
        app.create_job(app.JobRequest(url="https://93.184.215.14/v"))
    assert e.value.status_code == 429


def test_job_status_and_unknown_job():
    add_job(status="processing", progress=0.5, title="t")
    assert app.job_status("job1") == {
        "id": "job1", "status": "processing", "progress": 0.5, "title": "t", "error": None,
    }
    with pytest.raises(HTTPException) as e:
        app.job_status("missing")
    assert e.value.status_code == 404


def test_job_file(tmp_path):
    job = add_job()
    with pytest.raises(HTTPException) as e:
        app.job_file("job1")
    assert e.value.status_code == 409
    job.status, job.file = "done", tmp_path / "video.mp4"
    assert isinstance(app.job_file("job1"), FileResponse)


def test_routes_document_their_errors():
    documented = {r.path: set(r.responses) for r in app.app.routes if hasattr(r, "responses")}
    assert documented["/jobs"] >= {400, 401, 429}
    assert documented["/jobs/{job_id}"] >= {401, 404}
    assert documented["/jobs/{job_id}/file"] >= {401, 404, 409}


# --- run_job ---------------------------------------------------------------------

class FakeYDL:
    info: dict = {"title": "A video"}
    writes_file = True

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        hook = self.opts["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        hook({"status": "finished"})
        if self.writes_file:
            Path(self.opts["outtmpl"].replace("%(ext)s", "webm")).write_bytes(b"x")
        return self.info


@pytest.fixture
def fake_ydl(monkeypatch):
    monkeypatch.setattr(app.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(FakeYDL, "info", {"title": "A video"})
    monkeypatch.setattr(FakeYDL, "writes_file", True)
    return FakeYDL


def test_run_job_success(fake_ydl, monkeypatch):
    monkeypatch.setattr(app, "make_photos_safe", lambda src, dst: dst.write_bytes(b"mp4"))
    monkeypatch.setattr(app, "COOKIES_FILE", "cookies.txt")
    fake_ydl.info = {"_type": "playlist", "entries": [None, {"title": "First"}]}
    job = add_job()
    app.run_job(job)
    assert (job.status, job.title, job.progress) == ("done", "First", 1.0)
    assert job.file.read_bytes() == b"mp4"


def test_run_job_nothing_downloaded(fake_ydl):
    fake_ydl.writes_file = False
    job = add_job(id="empty")
    app.run_job(job)
    assert job.status == "error"
    assert job.error.startswith("No video downloaded")


@pytest.mark.parametrize(
    "exc, error",
    [
        (subprocess.TimeoutExpired("ffmpeg", 1), "conversion timed out"),
        (subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad codec"), "ffmpeg failed: bad codec"),
    ],
)
def test_run_job_ffmpeg_failures(fake_ydl, monkeypatch, exc, error):
    def boom(src, dst):
        raise exc

    monkeypatch.setattr(app, "make_photos_safe", boom)
    job = add_job(id=f"ff{id(exc)}")
    app.run_job(job)
    assert (job.status, job.error) == ("error", error)


def test_run_job_download_error(monkeypatch, caplog):
    class Failing(FakeYDL):
        def extract_info(self, url, download):
            raise app.yt_dlp.utils.DownloadError("ERROR: unsupported URL")

    monkeypatch.setattr(app.yt_dlp, "YoutubeDL", Failing)
    job = add_job(id="dl")
    app.run_job(job)
    assert (job.status, job.error) == ("error", "unsupported URL")
    assert "'https://example.com/v'" in caplog.text  # failures name the URL, escaped via %r


def test_fail_job_escapes_newlines_in_log(caplog):
    job = add_job(id="crlf")
    job.url = "https://example.com/a\r\nFAKE LOG LINE"
    app.fail_job(job, f"Unsupported URL: {job.url}")
    assert job.error == f"Unsupported URL: {job.url}"  # the API still returns the raw error
    assert "\n" not in caplog.text.rstrip("\n")
    assert caplog.text.count("FAKE LOG LINE") == 2  # URL and error text, each escaped


# --- ffmpeg helpers ----------------------------------------------------------------

def fake_run(probe_json: str, calls: list):
    def run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=probe_json)

    return run


@pytest.mark.parametrize(
    "video, audio, expect",
    [
        ("h264", "aac", ["-c:v", "copy", "-c:a", "copy"]),
        ("hevc", "opus", ["-c:v", "copy", "-tag:v", "hvc1", "-c:a", "aac"]),
        ("vp9", "aac", ["-c:v", "h264_videotoolbox"]),
    ],
)
def test_make_photos_safe_picks_codecs(monkeypatch, tmp_path, video, audio, expect):
    probe = (
        '{"streams": [{"codec_type": "video", "codec_name": "%s"}, '
        '{"codec_type": "video", "codec_name": "other"}, '
        '{"codec_type": "audio", "codec_name": "%s"}]}' % (video, audio)
    )
    calls = []
    monkeypatch.setattr(app.subprocess, "run", fake_run(probe, calls))
    app.make_photos_safe(tmp_path / "in.webm", tmp_path / "out.mp4")
    assert all(part in calls[-1] for part in expect)
