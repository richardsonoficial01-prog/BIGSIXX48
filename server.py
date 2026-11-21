import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("BIGSIXX48_DATA_DIR", str(BASE_DIR / "data")))
UPLOADS_DIR = DATA_DIR / "uploads"
LIBRARY_DIR = DATA_DIR / "library"
TMP_DIR = DATA_DIR / "tmp"
LIBRARY_INDEX_FILE = LIBRARY_DIR / "library.json"
UPLOADS_INDEX_FILE = UPLOADS_DIR / "uploads.json"

for d in (STATIC_DIR, DATA_DIR, UPLOADS_DIR, LIBRARY_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

if not LIBRARY_INDEX_FILE.exists():
    LIBRARY_INDEX_FILE.write_text("[]", encoding="utf-8")
if not UPLOADS_INDEX_FILE.exists():
    UPLOADS_INDEX_FILE.write_text("{}", encoding="utf-8")

app = FastAPI(title="BIGSIXX48 AI Clipper", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict[str, Any]] = {}
MEDIA_REGISTRY: Dict[str, Dict[str, Any]] = {}

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ImportRequest(BaseModel):
    url: str


class AnalyzeRequest(BaseModel):
    mediaId: str
    count: int = 5
    minDuration: int = 15
    maxDuration: int = 35
    focus: str = ""


def load_uploads_index() -> Dict[str, Any]:
    try:
        data = json.loads(UPLOADS_INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_uploads_index(data: Dict[str, Any]) -> None:
    try:
        UPLOADS_INDEX_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def recover_upload_if_missing(media_id: str) -> Optional[Path]:
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", media_id)
    target = UPLOADS_DIR / f"{safe_id}.mp4"
    if target.exists() and target.stat().st_size > 10_000:
        return target
    idx = load_uploads_index()
    meta = idx.get(safe_id) or MEDIA_REGISTRY.get(safe_id)
    if not meta or not meta.get("sourceUrl"):
        return None
    tmp_sub = TMP_DIR / f"rec_{safe_id}_{uuid.uuid4().hex[:6]}"
    tmp_sub.mkdir(parents=True, exist_ok=True)
    try:
        src_url = meta["sourceUrl"]
        resolved = resolve_redirects(src_url)
        dl = download_via_ytdlp(resolved, tmp_sub)
        if not dl and resolved != src_url:
            dl = download_via_ytdlp(src_url, tmp_sub)
        if not dl:
            dl = download_via_html_fallback(resolved, tmp_sub)
        if not dl:
            return None
        normalize_to_clean_mp4(dl["file"], target, crf="18")
        return target if target.exists() else None
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_sub, ignore_errors=True)


def load_library_index() -> List[Dict[str, Any]]:
    try:
        items = json.loads(LIBRARY_INDEX_FILE.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            return []
        valid = []
        for item in items:
            stored = item.get("storedFilename", "")
            if stored and (LIBRARY_DIR / stored).exists():
                valid.append(item)
        return valid
    except Exception:
        return []


def save_library_index(items: List[Dict[str, Any]]) -> None:
    LIBRARY_INDEX_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_job() -> str:
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "progress": 0,
        "message": "Iniciando...",
        "result": None,
        "error": None,
        "cancelled": False,
        "createdAt": time.time(),
    }
    return job_id


def update_job(job_id: str, progress: int, message: str) -> None:
    job = JOBS.get(job_id)
    if job and not job.get("cancelled"):
        job["progress"] = max(0, min(100, int(progress)))
        job["message"] = message


def complete_job(job_id: str, result: Dict[str, Any]) -> None:
    job = JOBS.get(job_id)
    if job:
        job["status"] = "completed"
        job["progress"] = 100
        job["message"] = "Concluído"
        job["result"] = result


def fail_job(job_id: str, error_msg: str) -> None:
    job = JOBS.get(job_id)
    if job:
        job["status"] = "failed"
        job["error"] = error_msg
        job["message"] = error_msg


def is_cancelled(job_id: str) -> bool:
    job = JOBS.get(job_id)
    return bool(job and job.get("cancelled"))


def detect_social_platform(raw_url: str) -> Optional[str]:
    s = (raw_url or "").strip()
    m = re.search(r"https?://[^\s<>]+", s, re.IGNORECASE)
    if m:
        s = m.group(0).rstrip(".,;)")
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "https://" + s
    try:
        parsed = urllib.parse.urlparse(s)
        host = (parsed.hostname or "").lower().replace("www.", "")
        if not host or "." not in host:
            return None
    except Exception:
        return None

    if "youtube.com" in host or host == "youtu.be":
        return "YouTube"
    if "instagram.com" in host or "instagr.am" in host:
        return "Instagram"
    if "tiktok.com" in host or "tiktokv.com" in host:
        return "TikTok"
    if "kwai.com" in host or "kwai-video.com" in host or "kwai.net" in host:
        return "Kwai"
    if "facebook.com" in host or host in ("fb.watch", "fb.com"):
        return "Facebook"
    if host in ("x.com", "twitter.com") or host.endswith(".twitter.com"):
        return "X (Twitter)"
    if "twitch.tv" in host:
        return "Twitch"
    if "reddit.com" in host or host == "redd.it":
        return "Reddit"
    if "pinterest." in host or host == "pin.it":
        return "Pinterest"
    if "vimeo.com" in host:
        return "Vimeo"
    return host.split(".")[0].capitalize()


def extract_clean_url(raw_url: str) -> str:
    s = (raw_url or "").strip()
    m = re.search(r"https?://[^\s<>]+", s, re.IGNORECASE)
    if m:
        s = m.group(0).rstrip(".,;)")
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "https://" + s
    return s


def resolve_redirects(url: str) -> str:
    current = url
    for ua in (MOBILE_UA, DESKTOP_UA):
        try:
            req = urllib.request.Request(
                current,
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                final_url = resp.geturl()
                if final_url:
                    return final_url
        except Exception:
            continue
    return current


def probe_media(path: Path) -> Dict[str, Any]:
    duration = 0.0
    width = 1280
    height = 720
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,codec_type",
            "-of",
            "json",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=25)
        info = json.loads(out.decode("utf-8", errors="ignore"))
        fmt = info.get("format") or {}
        if fmt.get("duration"):
            duration = float(fmt["duration"])
        for stream in info.get("streams") or []:
            if stream.get("codec_type") == "video":
                width = int(stream.get("width") or width)
                height = int(stream.get("height") or height)
                break
    except Exception:
        pass
    return {"duration": max(0.0, duration), "width": width, "height": height}


def has_audio_stream(path: Path) -> bool:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15)
        info = json.loads(out.decode("utf-8", errors="ignore"))
        return bool(info.get("streams"))
    except Exception:
        return False


def normalize_to_clean_mp4(src_path: Path, dst_path: Path, crf: str = "19") -> None:
    """Re-codifica em H.264/AAC na melhor qualidade e apaga 100% dos metadados."""
    if has_audio_stream(src_path):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src_path),
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "ultrafast",
            "-x264-params",
            "rc-lookahead=5:ref=1:bframes=0:sync-lookahead=0",
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dst_path),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "ultrafast",
            "-x264-params",
            "rc-lookahead=5:ref=1:bframes=0:sync-lookahead=0",
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dst_path),
        ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=360)
    if proc.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0:
        raise RuntimeError("Falha ao processar o arquivo de vídeo no servidor.")


def download_via_ytdlp(url: str, out_dir: Path) -> Optional[Dict[str, Any]]:
    ytdlp_bin = shutil.which("yt-dlp")
    if not ytdlp_bin:
        return None
    out_tpl = str(out_dir / "raw_%(id)s.%(ext)s")
    cmd = [
        ytdlp_bin,
        "--no-playlist",
        "--geo-bypass",
        "--no-warnings",
        "--write-info-json",
        "--user-agent",
        DESKTOP_UA,
        "--extractor-args",
        "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b",
        "--merge-output-format",
        "mp4",
        "-o",
        out_tpl,
        url,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    if proc.returncode != 0:
        cmd_retry = [
            ytdlp_bin,
            "--no-playlist",
            "--geo-bypass",
            "--no-warnings",
            "--write-info-json",
            "--user-agent",
            MOBILE_UA,
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "-o",
            out_tpl,
            url,
        ]
        proc2 = subprocess.run(cmd_retry, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
        if proc2.returncode != 0:
            return None

    media_files = [
        p
        for p in out_dir.iterdir()
        if p.is_file() and not p.name.endswith(".json") and p.stat().st_size > 10_000
    ]
    if not media_files:
        return None

    media_files.sort(key=lambda p: p.stat().st_size, reverse=True)
    chosen = media_files[0]

    title = ""
    author = ""
    for jf in out_dir.glob("*.info.json"):
        try:
            meta = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            title = (meta.get("title") or meta.get("description") or "").strip()
            author = (meta.get("uploader") or meta.get("channel") or meta.get("creator") or "").strip()
            break
        except Exception:
            pass

    return {"file": chosen, "title": title, "author": author}


def download_via_html_fallback(url: str, out_dir: Path) -> Optional[Dict[str, Any]]:
    html_text = ""
    final_url = url
    for ua in (MOBILE_UA, DESKTOP_UA):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=18) as resp:
                final_url = resp.geturl() or url
                html_text = resp.read().decode("utf-8", errors="ignore")
                if html_text:
                    break
        except Exception:
            continue

    if not html_text:
        return None

    title_match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE,
    )
    title = title_match.group(1).strip() if title_match else ""

    patterns = [
        r'"srcNoMark"\s*:\s*"([^"]+)"',
        r'"playAddr"\s*:\s*"([^"]+)"',
        r'"downloadAddr"\s*:\s*"([^"]+)"',
        r'<meta[^>]+property=["\']og:video:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:video["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)["\']',
        r'"video_url"\s*:\s*"([^"]+)"',
        r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
        r'"hd_src"\s*:\s*"([^"]+)"',
        r'"sd_src"\s*:\s*"([^"]+)"',
        r'<video[^>]+src=["\']([^"\']+)["\']',
    ]

    candidates: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, html_text, re.IGNORECASE):
            raw_v = m.group(1)
            cleaned = (
                raw_v.replace("\\u002F", "/")
                .replace("\\u0026", "&")
                .replace("\\/", "/")
                .replace("&amp;", "&")
                .strip()
            )
            if cleaned.startswith("//"):
                cleaned = "https:" + cleaned
            if cleaned.startswith("http") and cleaned not in candidates:
                candidates.append(cleaned)

    for cand in candidates:
        try:
            dl_req = urllib.request.Request(
                cand,
                headers={
                    "User-Agent": MOBILE_UA,
                    "Referer": final_url,
                    "Accept": "*/*",
                },
            )
            target_file = out_dir / "fallback_video.mp4"
            with urllib.request.urlopen(dl_req, timeout=30) as resp:
                with open(target_file, "wb") as fp:
                    shutil.copyfileobj(resp, fp)
            if target_file.exists() and target_file.stat().st_size > 25_000:
                return {"file": target_file, "title": title, "author": ""}
        except Exception:
            continue

    return None


def run_import_job(job_id: str, raw_url: str) -> None:
    tmp_sub = TMP_DIR / f"imp_{job_id}"
    tmp_sub.mkdir(parents=True, exist_ok=True)
    try:
        platform = detect_social_platform(raw_url)
        if not platform:
            fail_job(
                job_id,
                "Link inválido. Cole o endereço completo do vídeo.",
            )
            return

        clean_url = extract_clean_url(raw_url)
        update_job(job_id, 12, f"Conectando ao {platform}...")
        resolved_url = resolve_redirects(clean_url)
        if is_cancelled(job_id):
            return

        update_job(job_id, 28, f"Baixando na melhor qualidade sem marca d'água ({platform})...")
        dl = download_via_ytdlp(resolved_url, tmp_sub)
        if not dl and resolved_url != clean_url:
            dl = download_via_ytdlp(clean_url, tmp_sub)
        if not dl:
            update_job(job_id, 52, f"Extraindo stream direto sem marca d'água ({platform})...")
            dl = download_via_html_fallback(resolved_url, tmp_sub)
        if not dl:
            fail_job(
                job_id,
                f"Não foi possível baixar este vídeo do {platform}. Verifique se o link é público ou tente outro.",
            )
            return

        if is_cancelled(job_id):
            return

        update_job(job_id, 78, "Removendo metadados e preparando MP4 em alta definição...")
        media_id = uuid.uuid4().hex[:16]
        final_path = UPLOADS_DIR / f"{media_id}.mp4"
        normalize_to_clean_mp4(dl["file"], final_path, crf="18")

        info = probe_media(final_path)
        if info["duration"] <= 0.2:
            fail_job(job_id, "O vídeo baixado está vazio ou corrompido.")
            return

        title = (dl.get("title") or "").strip()[:90] or f"Vídeo {platform} • {media_id[:6]}"
        author = (dl.get("author") or "").strip() or platform

        media_obj = {
            "id": media_id,
            "title": title,
            "author": author,
            "platform": platform,
            "sourceUrl": clean_url,
            "duration": round(info["duration"], 2),
            "width": info["width"],
            "height": info["height"],
            "url": f"/media/uploads/{media_id}.mp4",
            "cleanDownloadUrl": f"/api/uploads/{media_id}/download",
            "transcript": [],
        }
        MEDIA_REGISTRY[media_id] = media_obj
        u_idx = load_uploads_index()
        u_idx[media_id] = media_obj
        save_uploads_index(u_idx)
        complete_job(job_id, media_obj)
    except Exception as exc:
        fail_job(job_id, f"Erro ao importar vídeo: {exc}")
    finally:
        shutil.rmtree(tmp_sub, ignore_errors=True)


def run_upload_job(job_id: str, raw_file: Path, original_name: str) -> None:
    try:
        update_job(job_id, 25, "Recebendo arquivo de vídeo...")
        media_id = uuid.uuid4().hex[:16]
        final_path = UPLOADS_DIR / f"{media_id}.mp4"
        update_job(job_id, 60, "Limpando metadados e convertendo para MP4 H.264/AAC...")
        normalize_to_clean_mp4(raw_file, final_path, crf="19")
        info = probe_media(final_path)
        if info["duration"] <= 0.2:
            fail_job(job_id, "Não foi possível ler a duração do arquivo enviado.")
            return

        clean_title = Path(original_name or "video.mp4").stem[:80] or "Vídeo Local"
        media_obj = {
            "id": media_id,
            "title": clean_title,
            "author": "Arquivo Local",
            "platform": "Arquivo Local",
            "duration": round(info["duration"], 2),
            "width": info["width"],
            "height": info["height"],
            "url": f"/media/uploads/{media_id}.mp4",
            "cleanDownloadUrl": f"/api/uploads/{media_id}/download",
            "transcript": [],
        }
        MEDIA_REGISTRY[media_id] = media_obj
        complete_job(job_id, media_obj)
    except Exception as exc:
        fail_job(job_id, f"Erro ao processar arquivo: {exc}")
    finally:
        if raw_file.exists():
            raw_file.unlink(missing_ok=True)


def detect_audio_peaks(wav_path: Path, total_duration: float) -> List[float]:
    try:
        import array
        import wave

        with wave.open(str(wav_path), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            samples = array.array("h", frames)
            if not samples:
                return []
            step = max(1, rate)
            energies = []
            for idx in range(0, len(samples), step):
                chunk = samples[idx : idx + step]
                if not chunk:
                    continue
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                energies.append((idx / rate, rms))
            energies.sort(key=lambda x: x[1], reverse=True)
            return [t for t, _ in energies[:20]]
    except Exception:
        return []


def try_whisper_transcribe(wav_path: Path) -> Dict[str, Any]:
    try:
        import gc
        # Evita OOM Kill no container de 512MB RAM do Render Free
        try:
            with open("/sys/fs/cgroup/memory.max", "r") as mf:
                lim = mf.read().strip()
                if lim.isdigit() and int(lim) <= 600 * 1024 * 1024:
                    return {"transcript": [], "words": []}
        except Exception:
            pass
        try:
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as mf:
                lim = mf.read().strip()
                if lim.isdigit() and int(lim) <= 600 * 1024 * 1024:
                    return {"transcript": [], "words": []}
        except Exception:
            pass
        from faster_whisper import WhisperModel

        model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1, num_workers=1)
        segments, _ = model.transcribe(str(wav_path), word_timestamps=True, beam_size=1)
        transcript = []
        words = []
        for seg in segments:
            if seg.start > 120:
                break
            txt = (seg.text or "").strip()
            if txt:
                transcript.append(
                    {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": txt}
                )
            for w in getattr(seg, "words", None) or []:
                wt = (w.word or "").strip()
                if wt:
                    words.append(
                        {"start": round(w.start, 2), "end": round(w.end, 2), "text": wt}
                    )
        del model
        gc.collect()
        return {"transcript": transcript, "words": words}
    except Exception:
        return {"transcript": [], "words": []}


def build_captions_for_window(
    start: float,
    end: float,
    words: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if words:
        win_words = [w for w in words if w["end"] > start and w["start"] < end]
        captions = []
        grp: List[Dict[str, Any]] = []

        def flush():
            if not grp:
                return
            a = max(0.0, grp[0]["start"] - start)
            b = min(end - start, grp[-1]["end"] - start)
            if b > a:
                captions.append(
                    {
                        "start": round(a, 2),
                        "end": round(b, 2),
                        "text": " ".join(x["text"] for x in grp).upper(),
                    }
                )
            grp.clear()

        for w in win_words:
            if grp and (len(grp) >= 4 or (w["start"] - grp[-1]["end"]) > 0.7):
                flush()
            grp.append(w)
            if re.search(r"[.!?]$", w["text"]):
                flush()
        flush()
        return captions

    out = []
    for seg in transcript:
        if seg["end"] > start and seg["start"] < end:
            a = max(0.0, seg["start"] - start)
            b = min(end - start, seg["end"] - start)
            if b > a:
                out.append(
                    {"start": round(a, 2), "end": round(b, 2), "text": seg["text"].upper()}
                )
    return out


def run_analyze_job(job_id: str, req: AnalyzeRequest) -> None:
    tmp_wav = TMP_DIR / f"aud_{job_id}.wav"
    try:
        video_path = recover_upload_if_missing(req.mediaId)
        if not video_path or not video_path.exists():
            fail_job(job_id, "Vídeo não encontrado no servidor. Cole o link e clique em Preparar cortes virais novamente.")
            return

        media_meta = MEDIA_REGISTRY.get(req.mediaId) or {}
        info = probe_media(video_path)
        total_dur = max(2.0, info["duration"] or media_meta.get("duration") or 15.0)
        platform = media_meta.get("platform") or "Social"
        base_title = media_meta.get("title") or "Corte Viral"

        update_job(job_id, 20, "Extraindo áudio para análise de picos e fala...")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(tmp_wav),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )

        update_job(job_id, 45, "Detectando momentos de maior retenção...")
        peaks = detect_audio_peaks(tmp_wav, total_dur) if tmp_wav.exists() else []
        speech = try_whisper_transcribe(tmp_wav) if tmp_wav.exists() else {"transcript": [], "words": []}
        transcript = speech["transcript"]
        words = speech["words"]

        update_job(job_id, 80, "Montando cortes verticais 9:16...")
        count = max(1, min(10, int(req.count or 5)))
        min_d = max(3.0, float(req.minDuration or 15))
        max_d = max(min_d, float(req.maxDuration or 35))
        target_d = min(total_dur, max(min_d, min(max_d, (min_d + max_d) / 2.0)))

        anchors: List[float] = []
        for pk in peaks:
            st = max(0.0, min(max(0.0, total_dur - target_d), pk - target_d * 0.25))
            if all(abs(st - existing) >= max(3.0, target_d * 0.45) for existing in anchors):
                anchors.append(st)
            if len(anchors) >= count:
                break

        if len(anchors) < count:
            step = max(1.0, (total_dur - target_d) / max(1, count))
            for i in range(count):
                st = max(0.0, min(max(0.0, total_dur - target_d), i * step))
                if all(abs(st - existing) >= 2.5 for existing in anchors):
                    anchors.append(st)
                if len(anchors) >= count:
                    break

        if not anchors:
            anchors = [0.0]

        anchors.sort()
        clips = []
        for idx, st in enumerate(anchors[:count]):
            en = min(total_dur, st + target_d)
            if en - st < 2.0:
                st = max(0.0, en - min(total_dur, 5.0))
            dur = round(max(1.5, en - st), 1)
            caps = build_captions_for_window(st, en, words, transcript)
            score = max(82, min(99, 97 - idx * 2))
            clips.append(
                {
                    "id": idx + 1,
                    "rank": idx + 1,
                    "title": f"{base_title[:45]} — Corte #{idx + 1}",
                    "hookReason": f"Pico de retenção ({platform}) com alto impacto visual e sonoro.",
                    "category": platform,
                    "viralScore": score,
                    "startTime": round(st, 1),
                    "endTime": round(en, 1),
                    "duration": dur,
                    "description": f"Melhor momento extraído de {platform}! 🔥 #bigsixx48",
                    "hashtags": ["#bigsixx48", f"#{platform.lower().replace(' ', '')}", "#cortesvirais", "#reels", "#fyp"],
                    "captions": caps,
                }
            )

        tracking = [
            {"time": round(t, 2), "x": 0.5}
            for t in [i * 0.5 for i in range(int(total_dur * 2) + 1)]
        ]

        complete_job(
            job_id,
            {
                "clips": clips,
                "transcript": transcript,
                "words": words,
                "tracking": tracking,
                "hasSpeech": len(transcript) > 0,
            },
        )
    except Exception as exc:
        fail_job(job_id, f"Erro na análise: {exc}")
    finally:
        if tmp_wav.exists():
            tmp_wav.unlink(missing_ok=True)


def run_finalize_job(
    job_id: str,
    raw_file: Path,
    filename: str,
    title: str,
    platform: str,
    duration_hint: float,
) -> None:
    try:
        update_job(job_id, 25, "Codificando corte editado 1080×1920 e apagando 100% dos metadados...")
        item_id = uuid.uuid4().hex[:12]
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename or f"bigsixx48_{item_id}.mp4")
        if not safe_name.lower().endswith(".mp4"):
            safe_name += ".mp4"
        stored_filename = f"{item_id}_{safe_name}"
        final_path = LIBRARY_DIR / stored_filename

        vf = (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        )
        if has_audio_stream(raw_file):
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_file),
                "-vf",
                vf,
                "-r",
                "30",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-fflags",
                "+bitexact",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                "-x264-params",
                "rc-lookahead=5:ref=1:bframes=0:sync-lookahead=0",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(final_path),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_file),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-shortest",
                "-vf",
                vf,
                "-r",
                "30",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-fflags",
                "+bitexact",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                "-x264-params",
                "rc-lookahead=5:ref=1:bframes=0:sync-lookahead=0",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(final_path),
            ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=360)
        if proc.returncode != 0 or not final_path.exists() or final_path.stat().st_size == 0:
            fail_job(job_id, "Falha ao finalizar o arquivo MP4 no servidor.")
            return

        update_job(job_id, 85, "Salvando corte limpo na biblioteca...")
        info = probe_media(final_path)
        size_bytes = final_path.stat().st_size
        dur = round(info["duration"] or duration_hint or 0.0, 1)

        library_item = {
            "id": item_id,
            "filename": safe_name,
            "storedFilename": stored_filename,
            "title": (title or safe_name).strip()[:90],
            "platform": (platform or "BIGSIXX48").strip(),
            "duration": dur,
            "sizeBytes": size_bytes,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "url": f"/media/library/{stored_filename}",
            "downloadUrl": f"/api/library/{item_id}/download",
        }

        items = load_library_index()
        items.insert(0, library_item)
        save_library_index(items[:100])

        complete_job(
            job_id,
            {
                "url": f"/media/library/{stored_filename}",
                "downloadUrl": f"/api/library/{item_id}/download",
                "libraryItem": library_item,
            },
        )
    except Exception as exc:
        fail_job(job_id, f"Erro ao finalizar MP4: {exc}")
    finally:
        if raw_file.exists():
            raw_file.unlink(missing_ok=True)


@app.get("/api/health")
async def api_health():
    return {
        "ok": True,
        "service": "BIGSIXX48",
        "platforms": ["YouTube", "Instagram", "TikTok", "Kwai", "Facebook", "X", "Qualquer Rede"],
    }


@app.post("/api/import")
async def api_import(req: ImportRequest):
    if not detect_social_platform(req.url):
        raise HTTPException(
            status_code=400,
            detail="Link inválido. Cole o endereço completo do vídeo.",
        )
    job_id = create_job()
    asyncio.get_event_loop().run_in_executor(None, run_import_job, job_id, req.url)
    return {"jobId": job_id}


@app.get("/media/uploads/{filename}")
async def serve_upload_with_recovery(filename: str):
    safe_name = os.path.basename(filename)
    file_path = UPLOADS_DIR / safe_name
    if not file_path.exists() and safe_name.endswith(".mp4"):
        media_id = safe_name[:-4]
        recovered = await asyncio.get_event_loop().run_in_executor(
            None, recover_upload_if_missing, media_id
        )
        if recovered and recovered.exists():
            file_path = recovered
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Vídeo expirado após reinicialização do servidor. Reimporte o link.")
    return FileResponse(path=str(file_path), media_type="video/mp4")


@app.get("/api/uploads/{media_id}/download")
async def api_download_clean_source(media_id: str):
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", media_id)
    file_path = await asyncio.get_event_loop().run_in_executor(
        None, recover_upload_if_missing, safe_id
    )
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Vídeo original não encontrado.")
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=f"bigsixx48_original_limpo_{safe_id[:8]}.mp4",
        headers={"Content-Disposition": f'attachment; filename="bigsixx48_original_limpo_{safe_id[:8]}.mp4"'},
    )


@app.post("/api/upload")
async def api_upload(request: Request, filename: str = Query("video.mp4")):
    job_id = create_job()
    raw_path = TMP_DIR / f"up_{job_id}_{re.sub(r'[^a-zA-Z0-9._-]+', '_', filename)}"
    total = 0
    with open(raw_path, "wb") as fp:
        async for chunk in request.stream():
            if chunk:
                fp.write(chunk)
                total += len(chunk)
    if total == 0:
        raw_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Arquivo de vídeo vazio.")
    asyncio.get_event_loop().run_in_executor(
        None, run_upload_job, job_id, raw_path, filename
    )
    return {"jobId": job_id}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    job_id = create_job()
    asyncio.get_event_loop().run_in_executor(None, run_analyze_job, job_id, req)
    return {"jobId": job_id}


@app.post("/api/finalize")
async def api_finalize(
    request: Request,
    filename: str = Query("bigsixx48_corte.mp4"),
    title: str = Query(""),
    platform: str = Query("BIGSIXX48"),
    duration: float = Query(0.0),
):
    job_id = create_job()
    raw_path = TMP_DIR / f"fin_{job_id}.bin"
    total = 0
    with open(raw_path, "wb") as fp:
        async for chunk in request.stream():
            if chunk:
                fp.write(chunk)
                total += len(chunk)
    if total == 0:
        raw_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Gravação vazia recebida.")
    asyncio.get_event_loop().run_in_executor(
        None, run_finalize_job, job_id, raw_path, filename, title, platform, duration
    )
    return {"jobId": job_id}


@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def api_job_cancel(job_id: str):
    job = JOBS.get(job_id)
    if job:
        job["cancelled"] = True
        job["status"] = "failed"
        job["error"] = "Operação cancelada."
    return {"ok": True}


@app.get("/api/library")
async def api_get_library():
    return {"items": load_library_index()}


@app.get("/api/library/{item_id}/download")
async def api_download_library_item(item_id: str):
    items = load_library_index()
    match = next((x for x in items if x.get("id") == item_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado na biblioteca.")
    file_path = LIBRARY_DIR / match["storedFilename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo MP4 não está mais no servidor.")
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=match["filename"],
        headers={"Content-Disposition": f'attachment; filename="{match["filename"]}"'},
    )


@app.delete("/api/library/{item_id}")
async def api_delete_library_item(item_id: str):
    items = load_library_index()
    remaining = []
    for item in items:
        if item.get("id") == item_id:
            fp = LIBRARY_DIR / item.get("storedFilename", "")
            if fp.exists():
                fp.unlink(missing_ok=True)
        else:
            remaining.append(item)
    save_library_index(remaining)
    return {"ok": True}


app.mount("/media", StaticFiles(directory=str(DATA_DIR)), name="media")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.api_route("/", methods=["GET", "HEAD"])
async def serve_root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"ok": True, "message": "BIGSIXX48 API ativa"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("CLIPPER_PORT", 8000)))
    uvicorn.run(app, host="0.0.0.0", port=port)
