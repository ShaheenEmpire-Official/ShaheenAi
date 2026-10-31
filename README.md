# ShaheenAI Creator

ShaheenAI now includes a one-input website-to-explainer-video prototype. The visitor enters a public webpage URL. The server extracts readable HTML text, creates text-card scenes, attempts an automatic spoken narration, renders an MP4 with FFmpeg, and creates an SRT caption file.

## Important: deploy the server once

GitHub Pages hosts static files only; it cannot execute the Python video engine. The repo includes a Render Blueprint and Dockerfile.

1. Open the repository's GitHub Pages URL.
2. Tap **Deploy ShaheenAI server**. Sign in to Render and authorize access to this GitHub repository.
3. Choose the free service option shown by Render and finish creating the service.
4. After the service finishes its first deploy, open the Render URL shown in the Render dashboard. That is the working ShaheenAI app. It asks only for a website URL.

The first deploy requires the repository owner's action and approval. This project cannot create a hosting account or approve access on the owner's behalf. Render's free service can sleep after inactivity, so the first request after sleep may take longer.

## Run locally

Python 3.10+, FFmpeg and the packages in requirements.txt are required.

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000.

## Current working scope

- Reads public HTML pages that allow automated requests.
- Extracts page title, description, headings and readable paragraphs.
- Detects whether the source text is Urdu script or English.
- Creates a short text-card explainer video (MP4) with original ShaheenAI visuals.
- Attempts to add spoken voiceover using gTTS; video creation can still complete without audio if that service is unavailable.
- Produces timed SRT captions and offers downloads.

## Not included / honest limits

- It does not copy or download a website's existing videos, images or music.
- It does not yet translate arbitrary English content into Urdu or Urdu into English.
- It is a deterministic webpage explainer, not a general AI writer or a full professional editor.
- Pages that require login, block automated access, or render their content only through client-side JavaScript may not be readable.
- Generated files are stored on the server's temporary filesystem. Download them after generation; temporary files may disappear after a restart or redeploy.
- Render free instances can sleep when idle and are intended for testing/hobby projects, not production guarantees.

Only use URLs and source material you have permission to process.
