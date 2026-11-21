"""Content-derived clip selection, local speech recognition and subject tracking.

No generated speech, captions or claimed video events are substituted when a
recognizer is unavailable. All returned captions originate in the source audio.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unicodedata
import wave

import numpy as np

_MODEL_LOCK = threading.Lock()
_MODELS = {}


def _plain(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower())
                   if not unicodedata.combining(c))


def _probe(path):
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, check=True, timeout=60,
    )
    return json.loads(process.stdout)


def _normalize(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return values
    lo, hi = np.percentile(values, [10, 95])
    if hi - lo < 1e-8:
        peak = float(np.max(np.abs(values)))
        return np.full_like(values, 0.5 if peak > 1e-8 else 0.0)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _audio_energy(wav_path):
    """Return half-second RMS bins without keeping a whole long video in RAM."""
    energy = []
    with wave.open(str(wav_path), "rb") as wav:
        frames = max(1, wav.getframerate() // 2)
        while True:
            buf = wav.readframes(frames)
            if not buf:
                break
            samples = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
            energy.append(float(np.sqrt(np.mean(samples * samples))))
    return np.asarray(energy, dtype=float)


def _transcribe(wav_path, cache_dir, progress, duration):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("O reconhecimento de voz não está instalado. Execute a instalação do app (faster-whisper).") from exc

    model_name = os.environ.get("WHISPER_MODEL", "tiny")
    cache = os.environ.get("WHISPER_CACHE_DIR", str(cache_dir))
    progress(25, "Preparando reconhecimento de voz local; o primeiro uso baixa o modelo...")
    transcript = []
    words = []
    with _MODEL_LOCK:
        key = (model_name, cache)
        try:
            if key not in _MODELS:
                _MODELS[key] = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=max(1, min(4, os.cpu_count() or 1)),
                    num_workers=1,
                    download_root=cache,
                )
            # FFmpeg already supplied normalized PCM. Passing the waveform
            # avoids a second decode and PyAV-version-specific open options.
            with wave.open(str(wav_path), "rb") as wav:
                waveform = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
            segments, info = _MODELS[key].transcribe(
                waveform,
                beam_size=3,
                word_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 450},
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
            )
            language = getattr(info, "language", None)
            for segment in segments:
                start = max(0.0, float(segment.start))
                end = min(duration, float(segment.end))
                text = str(segment.text).strip()
                if not text or end <= start or float(getattr(segment, "no_speech_prob", 0)) > 0.8:
                    continue
                transcript.append({"start": round(start, 3), "end": round(end, 3), "text": text})
                for word in segment.words or []:
                    word_text = str(word.word).strip()
                    word_start = max(start, float(word.start))
                    word_end = min(end, float(word.end))
                    if word_text and word_end > word_start:
                        words.append({"start": word_start, "end": word_end, "text": word_text})
                progress(min(65, 27 + int(38 * end / max(duration, 0.1))), "Transcrevendo a fala real do vídeo...")
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível transcrever o áudio. Verifique a instalação do reconhecimento de voz; "
                "no primeiro uso, o servidor também precisa de conexão para baixar o modelo Whisper. "
                f"Detalhe: {str(exc)[:240]}"
            ) from exc
    return transcript, words, language


def _visual_signals(path, duration, progress):
    """Sample at most 600 source frames, measuring motion and face position."""
    try:
        import cv2
    except ImportError:
        return [], []
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return [], []
    cascade = None
    if hasattr(cv2, "CascadeClassifier"):
        cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        candidate = cv2.CascadeClassifier(cascade_path)
        if not candidate.empty():
            cascade = candidate
    step = max(1.0, duration / 600)
    motion = []
    tracking = []
    previous = None
    previous_x = 0.5
    sample_count = max(1, int(math.ceil(duration / step)))
    try:
        for index in range(sample_count):
            timestamp = min(max(0, duration - 0.05), index * step)
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            thumb = cv2.resize(frame, (320, 180))
            gray = cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY)
            value = 0.0
            center = None
            if previous is not None:
                delta = cv2.absdiff(gray, previous).astype(np.float32)
                value = float(np.mean(delta)) / 255.0
                strong = np.maximum(delta - 20.0, 0.0)
                if float(strong.sum()) > 1000:
                    column_weights = strong.sum(axis=0)
                    center = float(np.dot(np.arange(320), column_weights) / strong.sum()) / 320.0
            if cascade is not None:
                faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(18, 18))
                if len(faces):
                    x, y, width, height = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                    center = (float(x) + float(width) / 2) / 320.0
            if center is not None:
                previous_x = 0.65 * previous_x + 0.35 * max(0.0, min(1.0, center))
            tracking.append({"time": round(timestamp, 3), "x": round(previous_x, 4)})
            motion.append({"time": timestamp, "value": value})
            previous = gray
            if index % 50 == 0:
                progress(68 + int(12 * index / max(1, sample_count)), "Medindo movimento e enquadramento do vídeo...")
    finally:
        cap.release()
    return motion, tracking


def _phrase_captions(transcript, words, start, end):
    selected = [w for w in words if w["end"] > start and w["start"] < end]
    captions = []
    group = []

    def append_group():
        if not group:
            return
        a = max(start, group[0]["start"])
        b = min(end, group[-1]["end"])
        if b > a:
            captions.append({"start": round(a - start, 3), "end": round(b - start, 3),
                             "text": " ".join(w["text"] for w in group).upper()})

    for word in selected:
        if group and (len(group) >= 4 or word["start"] - group[-1]["end"] > 0.7):
            append_group()
            group = []
        group.append(word)
        if re.search(r"[.!?]$", word["text"]):
            append_group()
            group = []
    append_group()
    if not selected:
        for segment in transcript:
            a, b = max(start, segment["start"]), min(end, segment["end"])
            if b > a:
                captions.append({"start": round(a - start, 3), "end": round(b - start, 3),
                                 "text": segment["text"].upper()})
    return captions


def _select_clips(metadata, duration, opts, energy, motion, transcript, words):
    count = max(1, min(8, int(opts.get("count", 5))))
    minimum = max(0.3, float(opts.get("minDuration", opts.get("minD", 15))))
    maximum = max(minimum, float(opts.get("maxDuration", opts.get("maxD", 30))))
    # A short source cannot supply the requested length; all intervals still
    # stay within real media and use different, overlapping starts when needed.
    target = min((minimum + maximum) / 2, duration * (0.85 if count > 1 else 1.0))
    target = max(min(0.3, duration), target)
    available = max(0.0, duration - target)
    step = max(0.25, min(2.0, target / 8, duration / max(count * 4, 1)))
    starts = np.arange(0, available + step * 0.25, step).tolist()
    starts += np.linspace(0, available, max(count * 4, 2)).tolist()
    starts = sorted(set(round(min(available, max(0, x)), 4) for x in starts))
    energy_norm = _normalize(energy)
    motion_norm = _normalize([m["value"] for m in motion])
    focus_tokens = set(re.findall(r"[\w]+", _plain(opts.get("focus", ""))))
    candidates = []
    for start in starts:
        end = min(duration, start + target)
        a, b = int(start * 2), max(int(start * 2) + 1, int(math.ceil(end * 2)))
        energy_window = energy_norm[a:b]
        audio = float(np.mean(energy_window)) if len(energy_window) else 0.0
        motion_window = [motion_norm[i] for i, sample in enumerate(motion) if start <= sample["time"] <= end]
        visual = float(np.mean(motion_window)) if motion_window else 0.0
        speech = [s for s in transcript if s["end"] > start and s["start"] < end]
        speech_text = " ".join(s["text"] for s in speech)
        speech_coverage = min(1.0, sum(max(0, min(end, s["end"]) - max(start, s["start"])) for s in speech) / max(target, 0.1))
        matches = focus_tokens.intersection(re.findall(r"[\w]+", _plain(speech_text)))
        keyword = len(matches) / max(1, len(focus_tokens))
        score = audio * 0.38 + visual * 0.25 + speech_coverage * 0.20 + keyword * 0.45
        candidates.append({"start": start, "end": end, "score": score, "audio": audio,
                           "visual": visual, "speech": speech, "matches": matches})
    ordered = sorted(candidates, key=lambda c: (-c["score"], c["start"]))
    selected = []
    for separation in [min(target * 0.55, available / max(count, 1)), 0.0]:
        for candidate in ordered:
            if candidate in selected:
                continue
            if all(abs(candidate["start"] - chosen["start"]) >= max(0.0001, separation) for chosen in selected):
                selected.append(candidate)
            if len(selected) >= count:
                break
        if len(selected) >= count:
            break
    title = str(metadata.get("title") or "Vídeo")
    peak = max((c["score"] for c in candidates), default=0)
    clips = []
    for rank, candidate in enumerate(selected, 1):
        start = round(candidate["start"], 3)
        end = min(duration, round(candidate["end"], 3))
        speech = candidate["speech"]
        phrase = speech[0]["text"].strip() if speech else ""
        clip_title = phrase[:84].strip() or f"{title[:68]} — Corte {rank}"
        signals = []
        category = "Trecho"
        if candidate["matches"]:
            signals.append("Fala com as palavras-chave: " + ", ".join(sorted(candidate["matches"])))
            category = "Palavra-chave"
        if speech:
            signals.append("Fala detectada e transcrita do áudio original")
            if category == "Trecho":
                category = "Fala"
        if candidate["audio"] > 0:
            signals.append("Seleção por energia do áudio")
            if category == "Trecho":
                category = "Energia"
        if candidate["visual"] > 0:
            signals.append("Movimento medido nas imagens")
            if category == "Trecho":
                category = "Movimento"
        if not signals:
            signals.append("Trecho do vídeo original sem fala ou atividade detectável")
        reason = ". ".join(signals) + ". Pontuação relativa de seleção."
        if target < minimum or available < target * max(1, count - 1):
            reason += " Cortes podem se sobrepor para respeitar a duração do vídeo."
        description = " ".join(s["text"] for s in speech).strip()[:500] or f"Trecho de {title}."
        clips.append({
            "id": rank, "rank": rank, "title": clip_title, "hookReason": reason, "category": category,
            "viralScore": int(round(100 * candidate["score"] / peak)) if peak > 0 else 0,
            "startTime": start, "endTime": end, "duration": round(end - start, 3),
            "description": description, "hashtags": ["#bigsixx48", "#cortes", "#shorts", "#reels"],
            "captions": _phrase_captions(transcript, words, start, end),
        })
    return clips


def analyze_media(path, metadata, opts, progress_callback=None):
    """Analyze the actual source file; suitable for a background worker thread."""
    path = Path(path)
    progress = progress_callback or (lambda percent, message: None)
    progress(3, "Verificando o vídeo original...")
    probe = _probe(path)
    duration = float(metadata.get("duration") or probe.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("O vídeo não possui duração válida para gerar cortes.")
    audio_present = any(s.get("codec_type") == "audio" for s in probe.get("streams", []))
    energy = np.asarray([], dtype=float)
    transcript, words, language = [], [], None
    if audio_present:
        with tempfile.TemporaryDirectory(prefix="clipper-audio-") as tmp:
            wav_path = Path(tmp) / "speech.wav"
            progress(10, "Extraindo o áudio real para análise e legendas...")
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(wav_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
                timeout=max(120, int(duration * 2)),
            )
            energy = _audio_energy(wav_path)
            if len(energy) and float(np.max(energy)) > 0.0001:
                transcript, words, language = _transcribe(wav_path, Path(__file__).parent / ".data" / "models", progress, duration)
            else:
                progress(65, "Áudio silencioso: não há fala para criar legendas.")
    else:
        progress(65, "Vídeo sem faixa de áudio: analisando as imagens.")
    motion, tracking = _visual_signals(path, duration, progress)
    progress(85, "Selecionando os trechos pelos sinais reais do vídeo...")
    clips = _select_clips(metadata, duration, opts, energy, motion, transcript, words)
    progress(98, "Cortes e legendas do vídeo prontos.")
    return {"clips": clips, "transcript": transcript,
            "words": [{"start": round(w["start"], 3), "end": round(w["end"], 3), "text": w["text"]} for w in words],
            "tracking": tracking,
            "language": language, "analysisMethod": "audio-energy+local-whisper+visual-motion",
            "hasSpeech": bool(transcript)}
