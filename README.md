# ShaheenAI

A mobile-friendly starter creator engine. The backend reads a public HTML webpage, extracts its title, description, headings and text, then creates a template-based script, timed captions and SRT subtitle text.

## Run locally (Android Termux or computer)

Install Python 3.10+, then run:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Test the API at `http://127.0.0.1:8000/docs`.

## API

- `GET /api/health` — service status.
- `POST /api/create` — JSON example:

```json
{
  "url": "https://example.com",
  "language": "English",
  "duration_seconds": 45
}
```

Language: `auto`, `English`, `Urdu`, or `Roman Urdu`. The response contains the source page details, script, timed captions, and SRT text.

## Feature status — read before use

**Working in the code:** public HTML page extraction, metadata/headings extraction, template-based script draft, timed caption draft, and SRT text export.

**Not implemented yet:** actual MP4 rendering/editing, voiceover, general-purpose AI writing/translation, video download, social publishing, user accounts, or persistent project storage. The current language templates do not translate arbitrary source text; they format a draft in the selected language. No video file is created.

Only process webpages you have permission to use. The API blocks private/local network addresses and limits fetched pages to 3 MB.
