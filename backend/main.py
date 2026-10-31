import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, HttpUrl

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("SHAHEEN_OUTPUT_DIR", "/tmp/shaheenai-output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ShaheenAI Creator", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")


class CreateRequest(BaseModel):
    url: HttpUrl


def validate_public_url(value: str):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Enter a public http:// or https:// website URL.")
    try:
        records = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        if not records:
            raise HTTPException(400, "The website address could not be resolved.")
        for record in records:
            address = ipaddress.ip_address(record[4][0])
            if not address.is_global:
                raise HTTPException(400, "Private and local network addresses are not allowed.")
    except socket.gaierror:
        raise HTTPException(400, "The website host could not be resolved.")
    return parsed


def fetch_public_page(raw_url: str):
    current = raw_url
    headers = {"User-Agent": "ShaheenAI-Reader/0.2 (+public webpage summary)"}
    try:
        with httpx.Client(timeout=18, headers=headers, follow_redirects=False) as client:
            for _ in range(4):
                validate_public_url(current)
                response = client.get(current)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(502, "The website returned an invalid redirect.")
                    from urllib.parse import urljoin
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                if "text/html" not in response.headers.get("content-type", "").lower():
                    raise HTTPException(415, "This link does not return a normal HTML webpage.")
                if len(response.content) > 3_000_000:
                    raise HTTPException(413, "This webpage is larger than the 3 MB reading limit.")
                return response.text, str(response.url)
            raise HTTPException(400, "The website redirected too many times.")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"The website rejected the request (HTTP {exc.response.status_code}).")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not read this website: {type(exc).__name__}.")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def extract_page(raw_html: str, final_url: str):
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
        tag.decompose()

    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not title:
        title = urlparse(final_url).hostname or "Website summary"

    meta = (
        soup.find("meta", attrs={"property": "og:description"})
        or soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"name": "Description"})
    )
    description = clean(meta.get("content", "") if meta else "")

    headings = [
        clean(item.get_text(" ", strip=True))
        for item in soup.find_all(["h1", "h2", "h3"])
    ]
    headings = [item for item in headings if len(item) > 3][:8]

    paragraphs = [
        clean(item.get_text(" ", strip=True))
        for item in soup.find_all(["p", "li"])
    ]
    paragraphs = [p for p in paragraphs if len(p) >= 45]
    # Keep a small, readable set of source passages for a short explainer.
    unique = []
    seen = set()
    for item in paragraphs:
        key = item[:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item[:380])
        if len(unique) >= 5:
            break

    if not unique and description:
        unique = [description]
    if not unique and headings:
        unique = headings[:4]
    if not unique:
        body = clean(soup.get_text(" ", strip=True))
        if body:
            unique = [body[:380]]
    if not unique:
        raise HTTPException(422, "This page did not contain readable text. Try a public article or blog page.")

    sample = " ".join([title, description] + headings + unique)
    language = "Urdu" if re.search(r"[\u0600-\u06FF]", sample) else "English"
    return title, description, headings, unique, language


def shape_text(text: str, is_urdu: bool) -> str:
    if not is_urdu:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def get_font(size: int, is_urdu: bool):
    candidates = (
        [
            "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        if is_urdu
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]
    )
    for name in candidates:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width, is_urdu=False):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        display_candidate = shape_text(candidate, is_urdu)
        if current and draw.textbbox((0, 0), display_candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def make_slide(path: Path, title: str, sentence: str, index: int, total: int, is_urdu: bool):
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (7, 16, 33))
    draw = ImageDraw.Draw(image)
    # Dark blue vertical gradient, drawn locally with Pillow.
    for y in range(height):
        t = y / height
        color = (int(7 + 7*t), int(17 + 12*t), int(35 + 28*t))
        draw.line((0, y, width, y), fill=color)

    accent = (47, 190, 237)
    gold = (243, 190, 91)
    draw.rounded_rectangle((64, 65, 1016, 1855), radius=42, outline=(36, 73, 106), width=3)
    brand_font = get_font(38, False)
    small_font = get_font(30, False)
    title_font = get_font(54, is_urdu)
    body_font = get_font(46 if is_urdu else 43, is_urdu)

    draw.text((100, 110), "SHAHEEN AI", font=brand_font, fill=accent)
    draw.text((100, 190), f"WEB STORY  |  {index:02d}/{total:02d}", font=small_font, fill=gold)

    y = 350
    for line in wrap_text(draw, title, title_font, 850, is_urdu)[:4]:
        draw.text((100, y), shape_text(line, is_urdu), font=title_font, fill=(245, 248, 255))
        y += 82

    draw.rounded_rectangle((100, y + 45, 980, y + 51), radius=3, fill=accent)
    y += 125
    for line in wrap_text(draw, sentence, body_font, 850, is_urdu)[:11]:
        draw.text((100, y), shape_text(line, is_urdu), font=body_font, fill=(213, 226, 241))
        y += 72

    draw.text((100, 1740), "CREATED FROM PUBLIC WEBPAGE TEXT", font=small_font, fill=(135, 166, 197))
    image.save(path, format="PNG")


def probe_duration(path: Path):
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        return None
    try:
        return max(1.0, float(result.stdout.strip()))
    except ValueError:
        return None


def make_srt(lines, durations):
    blocks, current = [], 0.0
    for idx, (line, duration) in enumerate(zip(lines, durations), start=1):
        start = current
        current += duration
        end = current
        def stamp(value):
            whole = int(value)
            millis = int(round((value - whole) * 1000))
            hours, rem = divmod(whole, 3600)
            minutes, seconds = divmod(rem, 60)
            return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
        blocks.append(f"{idx}\n{stamp(start)} --> {stamp(end)}\n{line}")
    return "\n\n".join(blocks) + "\n"


def render_video(title: str, lines, language: str, job_id: str):
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "The video renderer is not installed on this server.")
    is_urdu = language == "Urdu"
    work = Path(tempfile.mkdtemp(prefix="shaheenai-"))
    slides = []
    weights = [max(4, len(line.split())) for line in lines]
    audio_path = work / "voice.mp3"
    voiceover_ok = False
    try:
        # Voice generation is attempted automatically. The video still renders if TTS is temporarily unavailable.
        try:
            speech_text = " ".join(lines)
            voice_lang = "ur" if is_urdu else "en"
            gTTS(text=speech_text[:3800], lang=voice_lang, slow=False).save(str(audio_path))
            voiceover_ok = audio_path.exists() and audio_path.stat().st_size > 1000
        except Exception:
            voiceover_ok = False

        audio_duration = probe_duration(audio_path) if voiceover_ok else None
        if not audio_duration:
            audio_duration = max(18.0, float(len(lines) * 5))
        total_weight = sum(weights) or len(lines)
        durations = [audio_duration * weight / total_weight for weight in weights]
        # Keep the slides long enough to read; the last slide absorbs rounding.
        if durations:
            durations[-1] += max(0.0, audio_duration - sum(durations))

        concat_file = work / "slides.txt"
        with concat_file.open("w", encoding="utf-8") as handle:
            for idx, sentence in enumerate(lines):
                slide = work / f"slide_{idx:03d}.png"
                make_slide(slide, title, sentence, idx + 1, len(lines), is_urdu)
                slides.append(slide)
                handle.write(f"file '{slide.as_posix()}'\n")
                handle.write(f"duration {durations[idx]:.3f}\n")
            handle.write(f"file '{slides[-1].as_posix()}'\n")

        video_path = OUTPUT_DIR / f"{job_id}.mp4"
        srt_path = OUTPUT_DIR / f"{job_id}.srt"
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
        ]
        if voiceover_ok:
            command += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
        else:
            command += ["-map", "0:v:0", "-an"]
        command += [
            "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", "25",
        ]
        if voiceover_ok:
            command += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            command += ["-t", f"{audio_duration:.2f}"]
        command += ["-movflags", "+faststart", str(video_path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not video_path.exists():
            detail = (result.stderr or "FFmpeg could not render the video.")[-700:]
            raise HTTPException(500, f"Video rendering failed: {detail}")

        srt = make_srt(lines, durations)
        srt_path.write_text(srt, encoding="utf-8")
        return video_path.name, srt_path.name, srt, voiceover_ok, round(audio_duration)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.get("/")
def home():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "ShaheenAI Creator",
        "video_renderer": bool(shutil.which("ffmpeg")),
        "features": ["public webpage extraction", "script cards", "MP4 slideshow", "SRT captions", "automatic TTS attempt"],
    }


@app.post("/api/create")
def create(req: CreateRequest, request: Request):
    requested_url = str(req.url)
    validate_public_url(requested_url)
    raw_html, final_url = fetch_public_page(requested_url)
    title, description, headings, paragraphs, language = extract_page(raw_html, final_url)

    opening = f"آج کی ویب کہانی: {title}" if language == "Urdu" else f"Today on the web: {title}"
    ending = "اصل ویب سائٹ پر مزید تفصیل پڑھیں۔" if language == "Urdu" else "Visit the original website for the full details."
    body_lines = paragraphs[:5]
    script_lines = [opening] + body_lines + [ending]
    job_id = uuid.uuid4().hex
    video_name, srt_name, srt_text, voiceover_ok, seconds = render_video(
        title, script_lines, language, job_id
    )

    base = str(request.base_url).rstrip("/")
    return {
        "status": "video_created",
        "title": title,
        "source_url": final_url,
        "language": language,
        "duration_seconds": seconds,
        "script": script_lines,
        "captions_srt": srt_text,
        "video_url": f"{base}/media/{video_name}",
        "captions_url": f"{base}/media/{srt_name}",
        "voiceover": "generated" if voiceover_ok else "unavailable_video_has_no_voice",
        "notice": "This is an automatically generated text-card explainer video based on readable webpage text. It does not copy or download the site's original video footage. Pages requiring login, blocking automated access, or built mainly with JavaScript may not be readable. The script follows the source language; automatic translation is not included.",
    }


@app.get("/api/download/{filename}")
def download_file(filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|srt)", filename):
        raise HTTPException(404, "File not found.")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "This file is no longer available. Create the video again.")
    media_type = "video/mp4" if filename.endswith(".mp4") else "application/x-subrip"
    return FileResponse(path, media_type=media_type, filename=filename)
