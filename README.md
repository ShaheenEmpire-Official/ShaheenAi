# SHAHEEN AI Video Studio

SHAHEEN AI converts a publicly readable webpage into a short, original text-card explainer video.

## Current features

- Paste a public webpage URL and extract its title, metadata, headings, and readable paragraphs.
- Detect English or Urdu script.
- Choose vertical (9:16), landscape (16:9), or square (1:1) output.
- Choose quick or standard length.
- Try automatic English/Urdu narration; rendering can continue without narration if the speech service is unavailable.
- Preview the generated MP4 and download the MP4 and SRT captions.
- Use GitHub Actions to validate Python syntax, run tests, build the Docker image, and test real MP4 generation.

## Free deployment options

### Vercel (recommended free-tier route)

The repository contains a Vercel FastAPI entrypoint (`index.py`), `vercel.json`, and a portable FFmpeg package so the app can run as a Python Function.

1. Connect this public GitHub repository to a Vercel project.
2. Deploy with the default project settings.
3. Open the Vercel deployment URL. The same app URL serves the interface and API.

The Vercel Hobby plan currently documents a 300-second maximum function duration and Python functions have a 500 MB uncompressed bundle limit. Video responses are returned directly to the browser from the same function request because serverless temporary files are not durable. The app caps the encoded MP4 response size. These platform limits mean some longer or large videos may need a shorter setting. Check the current Vercel plan terms before relying on them for regular use.

### Render (alternative)

A Render Blueprint is included in `render.yaml`. The free plan may require billing setup for the account/workspace and free instances can sleep when idle. Do not add a payment method unless the account owner and a parent/guardian have reviewed the terms.

## Run locally

Requirements: Python 3.11+, FFmpeg, and the packages in `requirements.txt`.

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000.

## Test

```bash
python -m compileall -q backend tests index.py
python -m unittest discover -s tests -v
```

## Honest scope and limits

This version creates an explainer using original SHAHEEN AI text-card visuals from the webpage's readable text. It does **not** yet record the actual website screen, automatically select its images/videos, generate a full cinematic storyboard, or fetch trending commercial music. It does not copy third-party videos or music, and does not include copyrighted songs. Automatic narration depends on an external text-to-speech service.

Pages behind login, pages that block automated requests, and pages whose content exists only after complex JavaScript execution may not be readable. The output is temporary and the serverless response size is capped. Use only sites and source material you own or have permission to process.

No ads or ad scripts are included in this project.
