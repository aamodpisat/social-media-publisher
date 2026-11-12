# Template contract (YAML front matter)

Required:

- `title` — shown in the approval UI
- `media` — filename relative to that type folder (or a list)
- `platforms` — `instagram` and/or `facebook`

Optional:

- `cta`
- `hashtags` — list of strings (hints for the LLM, not pasted blindly)

Folders:

- `templates/story/` → Instagram/Facebook stories
- `templates/posts/` → feed posts
- `templates/reels/` → Reels (video file required)

The body under the second `---` is a brief for the LLM. Never put API keys or tokens here.
