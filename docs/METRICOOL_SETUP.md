# Metricool handoff

The connected Metricool brand is `aamodpisatphotography` (brand ID `8060412`), with Instagram and Facebook connected as of 12 November 2026. Its scheduled queue was empty for 12 November–12 December 2026 when checked.

## Current workflow

1. Replace the sample files in `templates/*/assets/` with client-approved media and edit the matching template notes with factual event details. Check image/video rights and client consent.
2. Generate drafts with `python3 run.py generate`. Review captions and media in the local UI (`python3 run.py serve`). Exclude unwanted items, then approve the batch.
3. Schedule each approved item in Metricool with its approved caption, media, platform and future time. Check the Metricool preview before submitting. Keep the published/scheduled links for reconciliation.

The Metricool connection in ChatGPT can inspect and schedule posts for this brand. It does **not** provide credentials to this local Python app. The app currently publishes directly through Meta when `publish-due` runs; it does not synchronize Metricool's planner or approval state. **Do not run or schedule `publish-due` for items you have scheduled in Metricool**, or they may publish twice.

Metricool's own “Send for review” feature requires a plan with team management and reviewer emails. Until that is configured, use the app's approval UI before asking ChatGPT to schedule an item in Metricool. Scheduling a post in Metricool is a publishing commitment at its scheduled time.

Before the first real post: replace sample assets and prompts with the intended campaign, confirm the approved caption and target networks, and select a future posting time in Asia/Kolkata. The sample local drafts are rejected; they are not queued for publication.
