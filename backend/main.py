from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import ipaddress, socket, re, html
import httpx

app = FastAPI(title="ShaheenAI Creator Engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class CreateRequest(BaseModel):
    url: HttpUrl
    language: str = "auto"  # auto, English, Urdu, Roman Urdu
    duration_seconds: int = 45

def safe_url(raw: str):
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "Only public http/https website URLs are supported.")
    try:
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise HTTPException(400, "Private or local network addresses are not allowed.")
    except socket.gaierror:
        raise HTTPException(400, "Website host could not be resolved.")
    return p

def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

def detect_language(text):
    if re.search(r"[\u0600-\u06FF]", text):
        return "Urdu"
    return "English"

def build_content(title, description, body, language, duration):
    source = clean_text(description) or clean_text(body)[:700]
    if not source:
        source = title
    sentences = re.split(r"(?<=[.!?۔])\s+", source)
    sentences = [s for s in sentences if len(s) > 20]
    if not sentences:
        sentences = [source]
    max_lines = max(3, min(8, duration // 8))
    points = sentences[:max_lines]
    # This is a deterministic template engine, not an LLM or a full translator.
    if language == "Urdu":
        opening = f"آج کی ویڈیو: {title}"
        outro = "مزید معلومات کے لیے اصل ویب سائٹ دیکھیں۔"
        labels = ["تعارف", "اہم بات", "مزید تفصیل", "اختتام"]
    elif language == "Roman Urdu":
        opening = f"Aaj ki video: {title}"
        outro = "Mazeed maloomat ke liye asal website dekhein."
        labels = ["Intro", "Aham baat", "Mazeed tafseel", "Outro"]
    else:
        opening = f"Today’s video: {title}"
        outro = "Visit the original website for more details."
        labels = ["INTRO", "KEY POINT", "DETAIL", "OUTRO"]
    script = [opening] + points + [outro]
    captions = []
    slot = max(3, duration // max(1, len(script)))
    for i, line in enumerate(script):
        start = i * slot
        end = min(duration, (i + 1) * slot)
        captions.append({"start": start, "end": end, "text": line})
    return script, captions

def srt_time(seconds):
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

@app.get("/api/health")
def health():
    return {"ok": True, "service": "ShaheenAI Creator Engine", "features": ["website research", "script", "captions", "SRT export"], "video_rendering": False}

@app.post("/api/create")
async def create(req: CreateRequest):
    url = str(req.url)
    parsed = safe_url(url)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent":"ShaheenAI-ResearchBot/0.1"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            if len(response.content) > 3_000_000:
                raise HTTPException(413, "Page is too large (maximum 3 MB).")
            if "text/html" not in response.headers.get("content-type", ""):
                raise HTTPException(415, "This URL is not an HTML webpage.")
            # Validate final redirect destination too.
            safe_url(str(response.url))
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not read this webpage: {type(exc).__name__}")
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "") or parsed.hostname
    meta = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"})
    description = clean_text(meta.get("content", "") if meta else "")
    body = clean_text(soup.get_text(" ", strip=True))[:12000]
    headings = [clean_text(h.get_text(" ", strip=True)) for h in soup.find_all(["h1","h2"])[:12]]
    lang = req.language
    if lang == "auto":
        lang = detect_language(title + " " + description + " " + body)
    if lang not in ("English", "Urdu", "Roman Urdu"):
        raise HTTPException(400, "Language must be English, Urdu, Roman Urdu, or auto.")
    duration = max(15, min(180, req.duration_seconds))
    script, captions = build_content(title, description, body, lang, duration)
    srt = "\n\n".join(f"{i+1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i,c in enumerate(captions))
    return {
        "status":"research_and_script_ready",
        "title":title, "source_url":url, "language":lang, "duration_seconds":duration,
        "description":description, "headings":headings, "script":script,
        "captions":captions, "srt":srt,
        "video_status":"not_rendered",
        "notice":"This engine extracts public webpage text and creates a draft script/captions. It does not download copyrighted videos, translate arbitrary text, generate voice, or render an MP4."
    }

@app.get("/")
def root():
    return {"message":"ShaheenAI API is running. Open /docs to test endpoints."}
