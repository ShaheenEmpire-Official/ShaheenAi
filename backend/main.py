import base64
import html
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, HttpUrl
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("SHAHEEN_OUTPUT_DIR", "/tmp/shaheenai-output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_PAGE_BYTES = 3_000_000
app = FastAPI(title="SHAHEEN AI Video Studio", version="1.0.0")
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")
rate_windows = defaultdict(deque)


@app.middleware("http")
async def normalize_vercel_rewrite_path(request: Request, call_next):
    # Vercel rewrites /api/* to the single FastAPI function at /api/index/*.
    path = request.scope.get("path", "")
    prefix = "/api/index"
    if os.environ.get("VERCEL") and path.startswith(prefix):
        rewritten = path[len(prefix):] or "/"
        request.scope["path"] = rewritten
        request.scope["raw_path"] = rewritten.encode("utf-8")
    return await call_next(request)


def get_ffmpeg_binary():
    system_binary = shutil.which("ffmpeg")
    if system_binary:
        return system_binary
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class CreateRequest(BaseModel):
    url: HttpUrl
    video_format: Literal["vertical", "landscape", "square"] = "vertical"
    length: Literal["quick", "standard"] = "quick"
    voiceover: bool = True


def validate_public_url(value: str):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Please enter a public HTTP or HTTPS website URL.")
    if parsed.username or parsed.password:
        raise HTTPException(400, "Website URLs containing login details are not accepted.")
    expected_port = 443 if parsed.scheme == "https" else 80
    if parsed.port not in (None, expected_port):
        raise HTTPException(400, "Only standard public website ports are supported.")
    host = parsed.hostname.rstrip(".").lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise HTTPException(400, "Local network addresses are not allowed.")
    try:
        records = socket.getaddrinfo(host, expected_port, type=socket.SOCK_STREAM)
        addresses = {record[4][0].split("%")[0] for record in records}
        if not addresses:
            raise HTTPException(400, "The website address could not be resolved.")
        for raw in addresses:
            if not ipaddress.ip_address(raw).is_global:
                raise HTTPException(400, "Private and local network addresses are not allowed.")
    except socket.gaierror:
        raise HTTPException(400, "The website host could not be resolved.")
    except ValueError:
        raise HTTPException(400, "The website address is invalid.")
    return parsed


def fetch_public_page(raw_url: str):
    current = raw_url
    headers = {"User-Agent": "SHAHEEN-AI-VideoStudio/1.0 (+public webpage summarizer)", "Accept": "text/html"}
    timeout = httpx.Timeout(18.0, connect=7.0)
    try:
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False, trust_env=False) as client:
            for _ in range(4):
                validate_public_url(current)
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(502, "The website returned an invalid redirect.")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    if "text/html" not in response.headers.get("content-type", "").lower():
                        raise HTTPException(415, "This link does not return a readable HTML webpage.")
                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_PAGE_BYTES:
                            raise HTTPException(413, "This webpage is larger than the 3 MB reading limit.")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    return b"".join(chunks).decode(encoding, errors="replace"), str(response.url)
            raise HTTPException(400, "The website redirected too many times.")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"The website returned HTTP {exc.response.status_code}.")
    except (httpx.HTTPError, UnicodeError) as exc:
        raise HTTPException(502, f"Could not read this website ({type(exc).__name__}).")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def extract_page(raw_html: str, final_url: str):
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "header"]):
        tag.decompose()

    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not title:
        title = urlparse(final_url).hostname or "Website story"

    meta = (
        soup.find("meta", attrs={"property": "og:description"})
        or soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"name": "Description"})
    )
    description = clean(meta.get("content", "") if meta else "")
    headings = [clean(item.get_text(" ", strip=True)) for item in soup.find_all(["h1", "h2", "h3"])]
    headings = [item for item in headings if len(item) > 3][:8]
    paragraphs = [clean(item.get_text(" ", strip=True)) for item in soup.find_all(["p", "li"])]
    paragraphs = [p for p in paragraphs if len(p) >= 35]

    unique, seen = [], set()
    for item in paragraphs:
        key = item[:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item[:420])
        if len(unique) >= 5:
            break
    if not unique and description:
        unique = [description[:420]]
    if not unique and headings:
        unique = headings[:4]
    if not unique:
        body = clean(soup.get_text(" ", strip=True))
        if body:
            unique = [body[:420]]
    if not unique:
        raise HTTPException(422, "No readable page text was found. Try a public article, product page, or blog.")

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
        ["/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        if is_urdu else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"]
    )
    for name in candidates:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width, is_urdu=False):
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        shown = shape_text(candidate, is_urdu)
        if current and draw.textbbox((0, 0), shown, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


SIZES = {
    "vertical": (1080, 1920),
    "landscape": (1920, 1080),
    "square": (1080, 1080),
}


def make_slide(path: Path, title: str, sentence: str, index: int, total: int,
               is_urdu: bool, video_format: str):
    width, height = SIZES[video_format]
    image = Image.new("RGB", (width, height), (7, 16, 33))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height)
        color = (int(7 + 7*t), int(17 + 12*t), int(35 + 35*t))
        draw.line((0, y, width, y), fill=color)

    scale = height / 1920
    pad = int(width * 0.085)
    draw.rounded_rectangle((int(pad*.62), int(pad*.62), width-int(pad*.62), height-int(pad*.62)),
                           radius=int(42*scale), outline=(36, 73, 106), width=max(2, int(3*scale)))
    brand_font = get_font(max(20, int(38*scale)), False)
    small_font = get_font(max(16, int(28*scale)), False)
    title_font = get_font(max(26, int(57*scale)), is_urdu)
    body_font = get_font(max(22, int(43*scale)), is_urdu)

    draw.text((pad, int(105*scale)), "SHAHEEN AI", font=brand_font, fill=(123, 220, 255))
    draw.text((pad, int(175*scale)), f"WEB STORY  |  {index:02d}/{total:02d}",
              font=small_font, fill=(243, 190, 91))

    max_text_width = width - 2*pad
    y = int(height * (0.24 if height > 1200 else 0.22))
    max_title_lines = 3 if video_format != "landscape" else 2
    for line in wrap_text(draw, title, title_font, max_text_width, is_urdu)[:max_title_lines]:
        draw.text((pad, y), shape_text(line, is_urdu), font=title_font, fill=(245, 248, 255))
        y += int(78*scale)
    y += int(45*scale)
    draw.rounded_rectangle((pad, y, width-pad, y+max(4, int(6*scale))), radius=4, fill=(47, 190, 237))
    y += int(85*scale)

    max_body_lines = 10 if video_format == "vertical" else (5 if video_format == "landscape" else 7)
    for line in wrap_text(draw, sentence, body_font, max_text_width, is_urdu)[:max_body_lines]:
        draw.text((pad, y), shape_text(line, is_urdu), font=body_font, fill=(213, 226, 241))
        y += int(68*scale)

    footer = "MADE WITH SHAHEEN AI"
    draw.text((pad, height-int(125*scale)), footer, font=small_font, fill=(135, 166, 197))
    image.save(path, format="PNG", optimize=True)


def probe_duration(path: Path):
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None
    try:
        return max(1.0, float(result.stdout.strip()))
    except ValueError:
        return None


def make_srt(lines, durations):
    blocks, current = [], 0.0
    def stamp(value):
        whole = int(value)
        millis = int(round((value - whole) * 1000))
        if millis == 1000:
            whole += 1
            millis = 0
        hours, rem = divmod(whole, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
    for idx, (line, duration) in enumerate(zip(lines, durations), start=1):
        start = current
        current += duration
        blocks.append(f"{idx}\n{stamp(start)} --> {stamp(current)}\n{line}")
    return "\n\n".join(blocks) + "\n"


def render_video(title: str, lines, language: str, job_id: str,
                 video_format: str, length: str, use_voiceover: bool):
    ffmpeg_binary = get_ffmpeg_binary()
    if not ffmpeg_binary:
        raise HTTPException(503, "The video renderer is not installed on this server.")
    is_urdu = language == "Urdu"
    work = Path(tempfile.mkdtemp(prefix="shaheenai-"))
    slides = []
    weights = [max(4, len(line.split())) for line in lines]
    audio_path = work / "voice.mp3"
    voiceover_ok = False
    try:
        if use_voiceover:
            try:
                speech = " ".join(lines)
                gTTS(text=speech[:3800], lang="ur" if is_urdu else "en",
                     slow=False, timeout=(5, 15)).save(str(audio_path))
                voiceover_ok = audio_path.exists() and audio_path.stat().st_size > 1000
            except Exception:
                voiceover_ok = False

        audio_duration = probe_duration(audio_path) if voiceover_ok else None
        if not audio_duration:
            audio_duration = 22.0 if length == "quick" else 38.0
        total_weight = sum(weights) or len(lines)
        durations = [audio_duration * weight / total_weight for weight in weights]
        if durations:
            durations[-1] += max(0.0, audio_duration - sum(durations))

        concat_file = work / "slides.txt"
        with concat_file.open("w", encoding="utf-8") as handle:
            for idx, sentence in enumerate(lines):
                slide = work / f"slide_{idx:03d}.png"
                make_slide(slide, title, sentence, idx+1, len(lines), is_urdu, video_format)
                slides.append(slide)
                handle.write(f"file '{slide.as_posix()}'\n")
                handle.write(f"duration {durations[idx]:.3f}\n")
            handle.write(f"file '{slides[-1].as_posix()}'\n")

        video_name = f"{job_id}.mp4"
        srt_name = f"{job_id}.srt"
        video_path, srt_path = OUTPUT_DIR/video_name, OUTPUT_DIR/srt_name
        width, height = SIZES[video_format]
        command = [ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", str(concat_file)]
        if voiceover_ok:
            command += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
        else:
            command += ["-map", "0:v:0", "-an"]
        command += ["-vf", "fps=30,format=yuv420p", "-s", f"{width}x{height}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                    "-maxrate", "550k", "-bufsize", "1100k"]
        if voiceover_ok:
            command += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            command += ["-t", f"{audio_duration:.2f}"]
        command += ["-movflags", "+faststart", str(video_path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not video_path.exists():
            detail = (result.stderr or "FFmpeg could not render the video.")[-600:]
            raise HTTPException(500, f"Video rendering failed: {detail}")
        srt = make_srt(lines, durations)
        srt_path.write_text(srt, encoding="utf-8")
        return video_name, srt_name, srt, voiceover_ok, round(audio_duration)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def enforce_rate_limit(request: Request):
    now = time.time()
    client_ip = request.client.host if request.client else "unknown"
    for ip in list(rate_windows.keys()):
        while rate_windows[ip] and now-rate_windows[ip][0] > 600:
            rate_windows[ip].popleft()
        if not rate_windows[ip]:
            rate_windows.pop(ip, None)
    bucket = rate_windows[client_ip]
    while bucket and now-bucket[0] > 600:
        bucket.popleft()
    if len(bucket) >= 3:
        raise HTTPException(429, "Too many videos were requested. Please try again in a few minutes.")
    bucket.append(now)


@app.get("/")
def home():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "SHAHEEN AI Video Studio",
        "version": "1.0.0",
        "video_renderer": bool(get_ffmpeg_binary()),
        "formats": list(SIZES.keys()),
        "features": ["public webpage reading", "vertical/landscape/square MP4",
                     "optional Urdu/English voiceover", "SRT captions"],
    }


@app.post("/api/create")
def create(req: CreateRequest, request: Request):
    enforce_rate_limit(request)
    requested_url = str(req.url)
    validate_public_url(requested_url)
    raw_html, final_url = fetch_public_page(requested_url)
    title, description, headings, paragraphs, language = extract_page(raw_html, final_url)

    opening = f"آج کی ویب کہانی: {title}" if language == "Urdu" else f"Today on the web: {title}"
    ending = "اصل ویب سائٹ پر مزید تفصیل پڑھیں۔" if language == "Urdu" else "Visit the original website for the full details."
    body_lines = paragraphs[:5]
    if description and description not in body_lines:
        body_lines = [description[:420]] + body_lines[:4]
    script_lines = [opening] + body_lines + [ending]
    job_id = uuid.uuid4().hex
    video_name, srt_name, srt_text, voiceover_ok, seconds = render_video(
        title, script_lines, language, job_id, req.video_format, req.length, req.voiceover
    )
    base = str(request.base_url).rstrip("/")
    video_base64 = None
    if os.environ.get("VERCEL"):
        # Vercel functions are stateless: send the rendered MP4 in the same
        # response so the browser can preview/download it without a later
        # request landing on a different temporary instance.
        encoded = base64.b64encode((OUTPUT_DIR / video_name).read_bytes()).decode("ascii")
        if len(encoded) > 3_200_000:
            raise HTTPException(413, "This video is too large for the free serverless response. Try the Quick length.")
        video_base64 = encoded

    return {
        "status": "video_created",
        "video_base64": video_base64,
        "title": title,
        "source_url": final_url,
        "language": language,
        "format": req.video_format,
        "duration_seconds": seconds,
        "script": script_lines,
        "captions_srt": srt_text,
        "video_url": f"{base}/media/{video_name}",
        "download_url": f"{base}/api/download/{video_name}",
        "captions_url": f"{base}/api/download/{srt_name}",
        "voiceover": "generated" if voiceover_ok else ("disabled" if not req.voiceover else "unavailable"),
        "notice": "Original text-card explainer created from readable webpage text. The source page's original videos, images, and music are not copied. Login-only, blocked, and JavaScript-only pages may not be readable. Use websites and material you own or have permission to process.",
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
