# SHAHEEN AI Video Studio

SHAHEEN AI turns a public webpage into an original, share-ready explainer video. Open the app, paste a URL, choose a video shape, and create an MP4 with optional narration and subtitle captions.

## What it does

- Reads publicly accessible HTML pages and extracts the title, description, headings, and readable page text.
- Detects Urdu-script or English content and prepares a short story outline.
- Renders original SHAHEEN AI text-card visuals as MP4 in **vertical (9:16), landscape (16:9), or square (1:1)** formats.
- Offers quick or standard video timing.
- Attempts English or Urdu narration using gTTS. When voice generation is unavailable, video creation continues without narration.
- Generates a timed SRT subtitle file and provides an in-page video preview and download links.
- Includes a health endpoint at `/api/health`, basic per-client request throttling, URL validation, redirect re-validation, and a 3 MB source-page limit.

## Run locally

Requirements: Python 3.11+, FFmpeg, and the packages in `requirements.txt`.

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000.

## Deploy on Render

The repository includes a Dockerfile and Render Blueprint. The blueprint defines a single free-plan web service in the Singapore region.

1. Open the Render Blueprint page for this repository:  
   https://dashboard.render.com/blueprint/new?repo=https://github.com/ShaheenEmpire-Official/ShaheenAi
2. Review the service settings and apply the Blueprint.
3. Once the first deploy is live, open the service URL supplied by Render. The app and API run together on that URL.

The repository is public, but deploying still requires a Render account and the account owner's approval in Render. Render free services may sleep when idle and are resource-limited; first requests can be slow and sustained video workloads are not guaranteed. Confirm current plan terms in Render before using it for public production traffic.

## Test suite

```bash
python -m compileall -q backend tests
python -m unittest discover -s tests -v
```

GitHub Actions also builds the Docker image and runs an end-to-end MP4/SRT smoke test after pushes and pull requests.

## Important limits

- The output is an animated text-card explainer, not a pixel-perfect screen recording of the source website and not a full AI video editor.
- It does not copy the source website's images, videos, or music.
- It does not translate arbitrary content between languages or rewrite it with a large language model.
- Pages requiring login, blocking automated requests, or rendering most content only with client-side JavaScript may not be readable.
- gTTS relies on an external service and may not always be available.
- Generated files are kept on the server's temporary filesystem. Download them after creation; files can disappear after restarts or redeploys.
- The URL checks block common private/local destinations and re-check redirects, but they are not a substitute for a dedicated production security review.
- Use only websites and content you own or have permission to process.
