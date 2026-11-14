# Drive MCP Instagram automation

This module is separate from the existing Social Media Publisher app. Codex retrieves one original through Google Drive MCP and supplies a verified local handoff to Python. Sources route to feed photos, Stories or Reels. Run at most one eligible item per invocation.

## Deploy into a fresh cloud environment

Check out the reviewed source revision and run:

```bash
cd automation/instagram-autoposter
./bootstrap.sh
```

The bootstrap creates a local Python environment, installs the tested lockfile and checks FFmpeg/FFprobe. It does not post. Python 3.11+ and Git are needed. Package installation requires PyPI; publishing requires api.openai.com, graph.facebook.com, storage.googleapis.com and oauth2.googleapis.com as applicable. Preserve existing network grants.

The private scheduler prompt supplies `runtime-config.json` using the example's keys. This file contains source-folder IDs, actual brand details, expected Instagram username and STATE_BACKEND=gcs. It is deliberately excluded from Git. Do not commit your runtime config, .env, downloaded media, previews, posting record, service-account JSON or any credentials. The example contains names only, never actual account values.

Configure runtime environment variables:

- GCS_BUCKET_NAME: private bucket name.
- GCS_SERVICE_ACCOUNT_JSON: complete signing-key JSON or a readable local file path.
- META_PAGE_ACCESS_TOKEN and META_IG_USER_ID, or the canonical INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID aliases.
- META_GRAPH_VERSION: a supported Graph version (default v27.0).
- OPENAI_API_KEY: needed for feed/Reel captions; not for Stories.

Grant the signing account Storage Object Admin on the private bucket. Enable public access prevention, uniform bucket access and no retention lock. Add the provided lifecycle deletion rule only for `instagram-temp/` (not the posting-state prefix). Signed media URLs expire after six hours and completed objects are deleted. Storage, downloads and any soft-delete retention can incur charges.

## Durable state is required for recreated computers

Set STATE_BACKEND=gcs. Local JSON is only a cache. The canonical log is:

```
instagram-state/v1/<INSTAGRAM_ACCOUNT_ID>/<ROOT_DRIVE_FOLDER_ID>/processed_images.json
```

The same prefix contains an initialization marker and distributed lease. Each command downloads current canonical state while holding a two-hour lease. Generation-matched writes reject stale writers. Publishing intent is committed to GCS before a publishing request is sent. Local deletion or an old environment snapshot cannot erase remote posting history.

For this new deployment, after credentials and the expected account are verified, run:

```bash
./run.sh --ensure-state
```

This validates Meta identity and creates state only when both remote state and its initialization marker have never existed. Existing state is retained. If a marker exists but state is missing, it refuses to initialize an empty record. A nonempty local-only history requires explicit verified migration, never an automatic new log. A crash between marker and state initialization deliberately fails closed and needs operator investigation. Keep remote object-version/backup recovery available; do not delete the state prefix or apply temporary-media lifecycle rules to it.

Normal commands:

```bash
.venv/bin/python preflight.py
./run.sh --ensure-state
./run.sh --plan
./run.sh --input work/handoff.json --dry-run
./run.sh --input work/handoff.json
./run.sh --resume
./run.sh --status
```

`--ensure-state` is idempotent and does not publish. `--input` without --dry-run publishes immediately. `--resume` can finish a saved container. A source file/hash is suppressed globally across formats after tracking; identical bytes are not intentionally cross-posted. Changing filenames or computers cannot reset the record. Edited source bytes may represent new media.

The at-most-once approach does not automatically repeat an ambiguous publishing request. Restore a missing/corrupt canonical record from its current valid backup; never initialize a fresh record to force a retry. `--retire-pending` permanently suppresses an unresolved pending item after checking the actual account. Exactly-once delivery across independent services cannot be guaranteed.

## MCP handoff

Read authenticated metadata and fetch the original with download_raw_file=true and include_base64=false. If the connector returns a Sediment file ID, use download_file with the ID stripped of sediment://. Use the materializer's local path, not its signed URL. Never make the source public or use Drive service-account credentials.

`work/handoff.json` includes file_id, filename, mime_type, parent_ids, absolute local_path, file_size_bytes from the authenticated connector response and a locally measured sha256. Add md5_checksum only if the provider exposed it. The local SHA-256 detects changes between materialization and submission; it is not presented as a provider checksum. The permanent log also records SHA-256 and Drive ID. Missing parent/size/type evidence is an error.

## Supported formats

Posts: JPEG/PNG images. Stories: JPEG/PNG or MP4/MOV. Reels: MP4/MOV. Sources must be direct children of one configured folder; ambiguous parents and unsupported combinations are rejected. Oldest eligible file across folders is chosen by the Codex task; Python accepts one handoff and does not independently choose another file.

Story photos are fitted directly from the orientation-corrected original to a 1080×1920 canvas, without feed aspect-ratio conversion first. A 9:16 source fills that canvas. Other ratios retain all content with white padding; the workflow does not crop photography or embedded text to force a fill. Feed photos keep their separate aspect-ratio rules.

## Optional licensed music for still photos

Set the nonsecret `GOOGLE_DRIVE_MUSIC_FOLDER_ID` to a separate private folder of original MP3 tracks (maximum 25 MB per file). Codex inspects the source photo and chooses a suitable mood using the track filenames; it does not claim to have listened to the files. Use clear labels such as romantic, cinematic, classical, piano, instrumental or celebration. MP3 downloads use authenticated Drive MCP and the same private materialization process as photos. Existing video soundtracks are preserved, not replaced.

For a photo, add a `music` object to the media handoff with the track's authenticated `file_id`, `filename`, `mime_type` (`audio/mpeg`), direct `parent_ids`, original `file_size_bytes`, locally computed `sha256`, absolute `local_path`, and `mood` (romantic, cinematic, instrumental or celebration). The renderer verifies size, hash and MP3 decoding and produces a static 1080×1920 H.264/AAC video lasting 15 seconds, looping short tracks and fading audio in/out. This is embedded audio, not an Instagram music sticker or catalog attribution. Photo sources in Stories publish as video Stories; photo sources in Posts with music publish as Reels shared to the feed, with the normal generated caption. Photos without a music handoff retain their existing route.

The canonical posting record remains keyed by the original photo ID and hash. Music is reusable and is not treated as another posting candidate. Its selected file ID, checksum and mood are saved with a pending photo; recovery must fetch that same track with matching bytes. Adding or changing music never permits reposting an already tracked image. Pending containers are resumed without rerendering. Local audio paths are not saved to remote history.

Source images: at most 25 MB and 40 megapixels. Video source/output: at most 250 MB. Reels: 3 seconds to 15 minutes. Video Stories: at most 60 seconds, without automatic splitting/trimming. Images are converted to JPEG; media is padded when needed rather than cropped. Videos become 1080×1920 H.264/AAC MP4 at 30 fps, retaining available source audio without adding music.

The exact marketing system prompt is embedded in main.py. Actual brand values are supplied separately. Reels use four sampled frames without speech transcription or full-frame-by-frame analysis. Stories have no feed caption or added overlays/stickers; Meta enforces Business-account eligibility when creating the Story container. The Facebook Login IG User endpoint does not expose account_type. Expected account ID/username are checked before publication using its supported id and username fields.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover original-image handoff, routing, payloads, image/video conversion, provider-optional checksums, account guards, duplicate prevention, interrupted publishing and fresh-computer canonical-state recovery with distributed-lock and generation checks. Tests use simulated remote APIs; the FFmpeg conversion test is real. Live credentials/network/connector availability still need an execution test.
