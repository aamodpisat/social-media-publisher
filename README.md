# Social Media Publisher

Local app that:

1. Reads templates from `templates/story`, `templates/posts`, and `templates/reels`
2. Asks your configured LLM for captions (any OpenAI-compatible model via `.env`)
3. Lets you **approve the week’s batch in one click** (manual workflow)
4. Can scan and auto-publish one new folder item per weekend run
5. Records fingerprints so the same caption + media cannot be posted twice

This is an **application** (UI + scheduler + Meta API). The LLM is one step. It is not a Cursor chat agent.

## Setup

Python 3.9+.

```bash
cd /Users/aamodpisat/apps/social-media-publisher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — never commit it
```

Put real media next to the sample markdown:

- `templates/story/assets/` — 9:16 images or video
- `templates/posts/assets/` — feed images or video
- `templates/reels/assets/` — video only (`.mp4` / `.mov`)

For automatic folder publishing, set `MEDIA_ROOT` to your media directory (default: `~/Documents/Instagram Photos & Reels`) and use its `Posts/`, `Reels/`, and `Story/` subfolders. Configure Meta and Contentstack values in `.env` as described in [docs/META_SETUP.md](docs/META_SETUP.md).

## Run

```bash
python3 run.py serve
```

Open http://127.0.0.1:8000

```bash
python3 run.py generate
python3 run.py publish-due
python3 run.py next-media
python3 run.py publish-one --media "/path/from/next-media" --caption "Your caption here"
```

Schedule the local Codex automation on Saturday and Sunday. It should call `next-media`, inspect that one file, draft a caption, and pass both to `publish-one --media ... --caption ...`. The command handles at most one stable, previously unpublished file per run. This mode uses Codex for captions and does not require an LLM API key.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Meta credentials

See [docs/META_SETUP.md](docs/META_SETUP.md).

## Metricool

For the connected photography brand and the manual approved-draft handoff, see [docs/METRICOOL_SETUP.md](docs/METRICOOL_SETUP.md). The local scheduler still uses Meta directly; avoid running it for posts scheduled in Metricool.
