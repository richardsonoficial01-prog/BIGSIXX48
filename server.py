"""BIGSIXX48 local media service. Run with: python server.py."""
from __future__ import annotations

import concurrent.futures
import copy
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CLIPPER_DATA_DIR", str(ROOT / ".data"))).resolve()
MEDIA_DIR, EXPORT_DIR, WORK_DIR = (DATA / name for name in ("media", "exports", "work"))
for directory in (MEDIA_DIR, EXPORT_DIR, WORK_DIR):
    directory.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD = int(os.environ.get("CLIPPER_MAX_UPLOAD_BYTES", 2 * 1024**3))
FFMPEG = os.environ.get("CLIPPER_FFMPEG") or shutil.which("ffmpeg")
FFPROBE = os.environ.get("CLIPPER_FFPROBE") or shutil.which("ffprobe")
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="clipper")
JOBS: dict[str, dict[str, Any]] = {}
MEDIA: dict[str, dict[str, Any]] = {}
LOCK = threading.RLock()
LOG = logging.getLogger("bigsixx48")

app = FastAPI(title="BIGSIXX48 AI Clipper", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def prevent_stale_jobs(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def extract_youtube_id(raw: str) -> str | None:
    """Accept real YouTube share/watch/shorts/live URLs, never lookalike hosts."""
    value = (raw or "").strip()
    # Pasted mobile share text may contain explanatory text around the URL.
    match = re.search(r"https?://[^\s<>\"']+", value, re.IGNORECASE)
    if match:
        value = match.group(0).rstrip(".,;!)]}")
    if not re.match(r"https?://", value, re.IGNORECASE):
        value = "https://" + value
    try:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower().rstrip(".")
        path = parsed.path.strip("/").split("/")
        video_id = None
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = path[0] if path else None
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "gaming.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
            if path[0] in {"shorts", "live", "embed", "v"} and len(path) > 1:
                video_id = path[1]
            elif path[0] == "watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            elif path[0] in {"attribution_link", "redirect"}:
                nested = parse_qs(parsed.query).get("u", parse_qs(parsed.query).get("q", [None]))[0]
                if nested and nested != raw:
                    return extract_youtube_id("https://www.youtube.com" + nested if nested.startswith("/") else nested)
        return video_id if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) else None
    except (ValueError, IndexError, RecursionError):
        return None


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in job.items() if not k.startswith("_")}


def update_job(job_id: str, progress: float, message: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        if job["_cancel"].is_set():
            raise RuntimeError("Operação cancelada.")
        job.update(status="running", progress=round(max(0, min(99, progress)), 1), message=message)


def create_job(task: Callable[[str], dict[str, Any]]) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    with LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "queued", "progress": 0,
            "message": "Aguardando processamento...", "_cancel": threading.Event(),
        }

    def run() -> None:
        try:
            result = task(job_id)
            with LOCK:
                if JOBS[job_id]["_cancel"].is_set():
                    raise RuntimeError("Operação cancelada.")
                JOBS[job_id].update(status="completed", progress=100, message="Pronto!", result=result)
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                LOG.warning("Processamento %s: %s", job_id, exc)
            else:
                LOG.exception("Falha no processamento %s", job_id)
            with LOCK:
                JOBS[job_id].update(status="failed", error=str(exc) or "Não foi possível processar o vídeo.", message="Processamento interrompido.")

    POOL.submit(run)
    return {"jobId": job_id}


def require_media_tools() -> None:
    if not FFMPEG or not FFPROBE:
        raise RuntimeError("FFmpeg não foi encontrado. Instale o FFmpeg e abra o app pelo iniciador novamente.")


def probe_media(path: Path, require_duration: bool = True) -> dict[str, Any]:
    require_media_tools()
    try:
        proc = subprocess.run(
            [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RuntimeError("Arquivo de vídeo inválido ou formato não reconhecido pelo FFmpeg.") from exc
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video or not video.get("width") or not video.get("height"):
        raise RuntimeError("O arquivo não contém uma faixa de vídeo válida.")
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if not math.isfinite(duration) or duration < 0:
        duration = 0
    if require_duration and duration <= 0:
        raise RuntimeError("Não foi possível determinar a duração real do vídeo.")
    return {"duration": duration, "width": int(video["width"]), "height": int(video["height"]), "video": video, "audio": audio}


def run_ffmpeg(args: list[str], job_id: str, duration: float, start: float, end: float, message: str) -> None:
    require_media_tools()
    proc = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-y", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errors: list[str] = []

    def drain_errors() -> None:
        for line in proc.stderr:
            errors.append(line)
            if len(errors) > 40:
                del errors[0]

    reader = threading.Thread(target=drain_errors, daemon=True)
    reader.start()
    try:
        update_job(job_id, start, message)
        for line in proc.stdout:
            if JOBS[job_id]["_cancel"].is_set():
                raise RuntimeError("Operação cancelada.")
            if line.startswith("out_time_us=") and duration > 0:
                try:
                    fraction = min(1.0, float(line.split("=", 1)[1]) / 1_000_000 / duration)
                    update_job(job_id, start + fraction * (end - start), message)
                except ValueError:
                    pass
        code = proc.wait(timeout=15)
        reader.join(timeout=2)
        if code:
            LOG.error("FFmpeg: %s", "".join(errors)[-4000:])
            raise RuntimeError("O FFmpeg não conseguiu converter o vídeo. Verifique se o arquivo original pode ser reproduzido.")
        update_job(job_id, end, message)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def save_media(metadata: dict[str, Any]) -> None:
    temp = MEDIA_DIR / f"{metadata['id']}.json.tmp"
    temp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    temp.replace(MEDIA_DIR / f"{metadata['id']}.json")
    with LOCK:
        MEDIA[metadata["id"]] = copy.deepcopy(metadata)


def normalize_media(path: Path, job_id: str, *, title: str, author: str, transcript: list | None = None, youtube_id: str = "") -> dict[str, Any]:
    update_job(job_id, 72, "Preparando vídeo para o editor...")
    info = probe_media(path, require_duration=False)
    media_id = uuid.uuid4().hex
    output = MEDIA_DIR / f"{media_id}.mp4"
    video, audio = info["video"], info["audio"]
    copy_codecs = video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p" and (audio is None or audio.get("codec_name") == "aac")
    args = ["-i", str(path), "-map", "0:v:0", "-map", "0:a:0?"]
    if copy_codecs:
        args += ["-c", "copy"]
    else:
        args += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    args += ["-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", str(output)]
    try:
        run_ffmpeg(args, job_id, info["duration"], 74, 97, "Convertendo vídeo para MP4 compatível...")
        ready = probe_media(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    metadata = {
        "id": media_id, "url": f"/media/{media_id}.mp4", "title": title,
        "author": author, "duration": ready["duration"], "width": ready["width"],
        "height": ready["height"], "transcript": transcript or [], "youtubeId": youtube_id,
    }
    save_media(metadata)
    return metadata


def fetch_subtitles(downloader: Any, info: dict[str, Any]) -> list[dict[str, Any]]:
    """Caption availability must never decide whether video import succeeds."""
    candidates = []
    for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for language in ("pt-BR", "pt", "pt-PT", "en-orig", "en", "es"):
            candidates.extend(item for item in tracks.get(language, []) if item.get("ext") == "json3" and item.get("url"))
    for candidate in candidates[:2]:
        try:
            with downloader.urlopen(candidate["url"]) as response:
                data = json.loads(response.read(8 * 1024 * 1024))
            segments = []
            for event in data.get("events", []):
                text = " ".join("".join(s.get("utf8", "") for s in event.get("segs", [])).split())
                if text:
                    start = event.get("tStartMs", 0) / 1000
                    segments.append({"start": start, "end": start + max(0.1, event.get("dDurationMs", 2500) / 1000), "text": text})
            if segments:
                return segments
        except Exception:
            continue
    return []


def import_youtube(url: str, job_id: str) -> dict[str, Any]:
    video_id = extract_youtube_id(url)
    if not video_id:
        raise RuntimeError("Link do YouTube inválido. Cole um link watch, youtu.be, Shorts ou transmissão já encerrada.")
    if not importlib.util.find_spec("yt_dlp"):
        raise RuntimeError("O componente yt-dlp não está instalado. Execute o instalador do app novamente.")
    require_media_tools()
    import yt_dlp

    folder = WORK_DIR / job_id
    folder.mkdir(exist_ok=True)

    class QuietLogger:
        def debug(self, message: str) -> None:
            LOG.debug("yt-dlp: %s", message)
        def warning(self, message: str) -> None:
            LOG.warning("yt-dlp: %s", message)
        def error(self, message: str) -> None:
            LOG.error("yt-dlp: %s", message)

    def progress(data: dict[str, Any]) -> None:
        if JOBS[job_id]["_cancel"].is_set():
            raise RuntimeError("Operação cancelada.")
        if data.get("status") == "downloading":
            size = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            fraction = data.get("downloaded_bytes", 0) / size if size else 0
            update_job(job_id, 10 + min(1, fraction) * 55, "Baixando o vídeo original do YouTube...")

    def reject_live(info: dict[str, Any], *, incomplete: bool = False) -> None:
        if info.get("is_live") or info.get("live_status") == "is_upcoming":
            raise RuntimeError("A transmissão ainda está ao vivo ou não começou. Use um vídeo já publicado ou uma transmissão encerrada.")

    options = {
        "format": "bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b[height<=1080]/best",
        "outtmpl": str(folder / "source.%(ext)s"), "noplaylist": True,
        "merge_output_format": "mp4", "quiet": True, "no_warnings": True,
        "logger": QuietLogger(), "socket_timeout": 25, "retries": 2, "fragment_retries": 2,
        "max_filesize": MAX_UPLOAD, "progress_hooks": [progress], "match_filter": reject_live,
        "ffmpeg_location": FFMPEG,
    }
    if shutil.which("node"):
        options["js_runtimes"] = {"node": {"path": shutil.which("node")}}
    secret_cookies = Path("/etc/secrets/cookies.txt")
    if secret_cookies.is_file():
        local_cookies = folder / "cookies.txt"
        shutil.copyfile(secret_cookies, local_cookies)
        options["cookiefile"] = str(local_cookies)
    try:
        update_job(job_id, 4, "Conectando ao YouTube...")
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            if info:
                update_job(job_id, 68, "Carregando legendas disponíveis...")
                transcript = fetch_subtitles(downloader, info)
        if not info:
            raise RuntimeError("O YouTube não retornou um vídeo disponível para baixar.")
        if info.get("is_live") or info.get("live_status") == "is_upcoming":
            raise RuntimeError("A transmissão ainda está ao vivo ou não começou. Use um vídeo já publicado ou uma transmissão encerrada.")
        sources = [p for p in folder.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
        if not sources:
            raise RuntimeError("O YouTube não disponibilizou o arquivo de vídeo para este link.")
        source = max(sources, key=lambda p: p.stat().st_size)
        return normalize_media(source, job_id, title=info.get("title") or f"YouTube {video_id}", author=info.get("channel") or info.get("uploader") or "YouTube", transcript=transcript, youtube_id=video_id)
    except yt_dlp.utils.DownloadError as exc:
        text = str(exc).lower()
        if JOBS[job_id]["_cancel"].is_set():
            raise RuntimeError("Operação cancelada.") from exc
        if "proxy" in text or "tunnel" in text or "403 forbidden" in text and "connect" in text:
            reason = "A hospedagem bloqueou a conexão com o YouTube (proxy/HTTP 403). O link foi reconhecido, mas o servidor não recebeu acesso ao vídeo. Use uma hospedagem com acesso ao YouTube ou envie o arquivo original."
        elif "sign in" in text or "bot" in text or "confirm" in text or "429" in text:
            reason = "O YouTube exigiu verificação de acesso ou limitou o download neste servidor. Tente outro vídeo público ou envie o arquivo original na aba MP4 / MOV."
        elif any(s in text for s in ("private", "unavailable", "removed", "not available", "age-restricted", "members-only")):
            reason = "Este vídeo está privado, indisponível ou tem restrições de acesso. Use um vídeo público disponível ou envie o arquivo original."
        else:
            reason = "Não foi possível baixar este vídeo do YouTube. Verifique a conexão e atualize o yt-dlp pelo instalador; você também pode enviar o arquivo original."
        raise RuntimeError(reason) from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class AnalyzeRequest(BaseModel):
    mediaId: str = Field(pattern=r"^[a-f0-9]{32}$")
    count: int = Field(default=5, ge=1, le=20)
    minDuration: float = Field(default=30, gt=0, le=600)
    maxDuration: float = Field(default=60, gt=0, le=600)
    focus: str = Field(default="", max_length=2000)


@app.get("/api/health")
def health() -> dict[str, Any]:
    capabilities = {"ffmpeg": bool(FFMPEG), "ffprobe": bool(FFPROBE), "youtube": bool(importlib.util.find_spec("yt_dlp")), "transcription": bool(importlib.util.find_spec("faster_whisper"))}
    return {"ok": all(capabilities.values()), "version": "2.0.0", **capabilities}


@app.post("/api/import")
def begin_import(body: ImportRequest) -> dict[str, str]:
    if not extract_youtube_id(body.url):
        raise HTTPException(status_code=400, detail="Link do YouTube inválido. Cole o endereço completo do vídeo.")
    return create_job(lambda job_id: import_youtube(body.url, job_id))


async def receive_file(request: Request, suffix: str) -> Path:
    try:
        if int(request.headers.get("content-length", "0")) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="O vídeo excede o limite de 2 GB desta instalação.")
    except ValueError:
        pass
    path = WORK_DIR / f"upload-{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with path.open("wb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(status_code=413, detail="O vídeo excede o limite de 2 GB desta instalação.")
                target.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="O arquivo de vídeo está vazio.")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def safe_name(name: str, fallback: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", name).strip(" .")
    return value[:180] or fallback


@app.post("/api/upload")
async def upload(request: Request, filename: str = "video.mp4") -> dict[str, str]:
    title = safe_name(filename, "Vídeo local")
    suffix = Path(title).suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mpeg", ".mpg", ".ts"}:
        suffix = ".video"
    path = await receive_file(request, suffix)

    def task(job_id: str) -> dict[str, Any]:
        try:
            return normalize_media(path, job_id, title=title, author="Arquivo Local")
        finally:
            path.unlink(missing_ok=True)
    return create_job(task)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(status_code=404, detail="Operação não encontrada. Inicie o processamento novamente.")
        return public_job(JOBS[job_id])


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, bool]:
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(status_code=404, detail="Operação não encontrada.")
        JOBS[job_id]["_cancel"].set()
    return {"cancelled": True}


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest) -> dict[str, str]:
    with LOCK:
        metadata = copy.deepcopy(MEDIA.get(body.mediaId))
    if not metadata or not (MEDIA_DIR / f"{body.mediaId}.mp4").is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado. Importe o vídeo novamente.")
    if body.maxDuration < body.minDuration:
        raise HTTPException(status_code=400, detail="A duração máxima deve ser maior ou igual à duração mínima.")

    def task(job_id: str) -> dict[str, Any]:
        import analysis
        result = analysis.analyze_media(
            MEDIA_DIR / f"{body.mediaId}.mp4", metadata, body.model_dump(),
            lambda percent, message: update_job(job_id, percent, message),
        )
        if not isinstance(result, dict) or not result.get("clips"):
            raise RuntimeError("A análise não encontrou um trecho válido para cortar neste vídeo.")
        if result.get("transcript"):
            metadata["transcript"] = result["transcript"]
            save_media(metadata)
        return result
    return create_job(task)


@app.post("/api/finalize")
async def finalize(request: Request, filename: str = "bigsixx48_corte_1080x1920.mp4") -> dict[str, str]:
    name = safe_name(filename, "bigsixx48_corte_1080x1920.mp4")
    name = str(Path(name).with_suffix(".mp4"))
    path = await receive_file(request, ".recording")

    def task(job_id: str) -> dict[str, Any]:
        export_id = uuid.uuid4().hex
        target = EXPORT_DIR / f"{export_id}.mp4"
        try:
            info = probe_media(path, require_duration=False)
            run_ffmpeg([
                "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-map_metadata", "-1",
                "-map_chapters", "-1", "-movflags", "+faststart", str(target),
            ], job_id, info["duration"], 5, 96, "Finalizando MP4 H.264 com áudio AAC...")
            ready = probe_media(target)
            return {"url": f"/exports/{export_id}.mp4", "filename": name, "type": "video/mp4", "duration": ready["duration"], "size": target.stat().st_size}
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            path.unlink(missing_ok=True)
    return create_job(task)


def known_file(directory: Path, file_name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}\.mp4", file_name):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    path = directory / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return path


@app.get("/media/{file_name}")
def media_file(file_name: str) -> FileResponse:
    return FileResponse(known_file(MEDIA_DIR, file_name), media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/exports/{file_name}")
def export_file(file_name: str, download: bool = False) -> FileResponse:
    return FileResponse(known_file(EXPORT_DIR, file_name), media_type="video/mp4", filename="bigsixx48_corte_1080x1920.mp4" if download else None)


@app.get("/")
def index() -> FileResponse:
    path = ROOT / "static" / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Interface ainda não instalada.")
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-store"})


if (ROOT / "static").is_dir():
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

for record in MEDIA_DIR.glob("*.json"):
    try:
        metadata = json.loads(record.read_text(encoding="utf-8"))
        media_id = metadata["id"]
        if re.fullmatch(r"[a-f0-9]{32}", media_id) and (MEDIA_DIR / f"{media_id}.mp4").is_file():
            MEDIA[media_id] = metadata
    except (OSError, ValueError, KeyError, TypeError):
        LOG.warning("Ignorando registro de mídia inválido: %s", record.name)


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=os.environ.get("CLIPPER_HOST", "127.0.0.1"), port=int(os.environ.get("PORT") or os.environ.get("CLIPPER_PORT", "8000")))
