from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from smp.config import get_settings
from smp.generator.run import generate_week
from smp.redact import redact
from smp.scheduler import resolve_posting_days
from smp.scheduler.days import iso_week_id
from smp.scheduler.run import publish_due
from smp.store import drafts as draft_store
from smp.store.settings import AppUiSettings, load_settings, save_settings

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"

app = FastAPI(title="Social Media Publisher")
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB / "templates"))

NOTICES = {
    "generated": "Drafts are ready.",
    "approved": "This week is approved.",
    "saved": "Saved.",
    "excluded": "Removed from this week.",
    "schedule-saved": "Schedule saved.",
    "published": "Posted.",
    "not-a-posting-day-or-empty": "Nothing is due today.",
}

STATUS_LABELS = {
    "draft": "Ready",
    "approved": "Approved",
    "rejected": "Removed",
    "duplicate_blocked": "Already posted",
    "published": "Posted",
    "failed": "Failed",
}

TYPE_LABELS = {"story": "Story", "posts": "Post", "reels": "Reel"}
DAY_LETTERS = [
    ("mon", "M"),
    ("tue", "T"),
    ("wed", "W"),
    ("thu", "T"),
    ("fri", "F"),
    ("sat", "S"),
    ("sun", "S"),
]


def _safe_error(exc: BaseException) -> str:
    return str(redact(str(exc)))


def _flash(request: Request) -> dict:
    key = request.query_params.get("notice")
    return {
        "error": request.query_params.get("error"),
        "notice": NOTICES.get(key, key if key else None),
    }


@app.middleware("http")
async def no_secret_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    settings = get_settings()
    ui = load_settings()
    effective = resolve_posting_days(ui.posting_days, settings.env_posting_days())
    batches = []
    for batch_id in draft_store.list_batch_ids():
        items = draft_store.batch_items(batch_id)
        batches.append(
            {
                "id": batch_id,
                "count": len(items),
                "approved": sum(1 for i in items if i.status == "approved"),
                "draft": sum(1 for i in items if i.status == "draft"),
                "published": sum(1 for i in items if i.status == "published"),
                "summary": _batch_summary(items),
            }
        )
    current = iso_week_id()
    flash = _flash(request)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "effective_days": effective,
            "using_defaults": not ui.posting_days,
            "day_letters": DAY_LETTERS,
            "batches": batches,
            "current_week": current,
            "error": flash["error"],
            "notice": flash["notice"],
        },
    )


def _batch_summary(items) -> str:
    n = len(items)
    posted = sum(1 for i in items if i.status == "published")
    approved = sum(1 for i in items if i.status == "approved")
    if posted == n and n:
        return "Posted"
    if approved:
        return f"{approved} approved"
    return f"{n} ready" if n else "Empty"


@app.get("/weeks/{batch_id}", response_class=HTMLResponse)
async def week_detail(request: Request, batch_id: str):
    items = draft_store.batch_items(batch_id)
    eligible = sum(1 for i in items if i.status in {"draft", "approved"})
    flash = _flash(request)
    view_items = []
    for item in items:
        view_items.append(
            {
                "raw": item,
                "type_label": TYPE_LABELS.get(item.content_type, item.content_type),
                "status_label": STATUS_LABELS.get(item.status, item.status),
                "can_exclude": item.status not in {"published", "rejected"},
            }
        )
    return templates.TemplateResponse(
        "week.html",
        {
            "request": request,
            "batch_id": batch_id,
            "items": view_items,
            "eligible": eligible,
            "error": flash["error"],
            "notice": flash["notice"],
        },
    )


@app.post("/actions/generate")
async def action_generate():
    try:
        items = generate_week()
        batch = items[0].batch_id if items else iso_week_id()
        return RedirectResponse(f"/weeks/{batch}?notice=generated", status_code=303)
    except Exception as exc:
        return RedirectResponse("/?error=" + _safe_error(exc), status_code=303)


@app.post("/weeks/{batch_id}/approve")
async def action_approve(batch_id: str):
    try:
        draft_store.approve_batch(batch_id)
        return RedirectResponse(f"/weeks/{batch_id}?notice=approved", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/weeks/{batch_id}?error=" + _safe_error(exc), status_code=303)


@app.post("/items/{draft_id}/caption")
async def action_caption(draft_id: str, caption: str = Form(...), batch_id: str = Form(...)):
    try:
        draft_store.update_caption(draft_id, caption)
        return RedirectResponse(f"/weeks/{batch_id}?notice=saved", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/weeks/{batch_id}?error=" + _safe_error(exc), status_code=303)


@app.post("/items/{draft_id}/exclude")
async def action_exclude(draft_id: str, batch_id: str = Form(...)):
    try:
        draft_store.exclude(draft_id)
        return RedirectResponse(f"/weeks/{batch_id}?notice=excluded", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/weeks/{batch_id}?error=" + _safe_error(exc), status_code=303)


@app.post("/settings/days")
async def action_days(request: Request):
    form = await request.form()
    use_env = form.get("use_env") == "on"
    if use_env:
        save_settings(AppUiSettings(posting_days=[]))
    else:
        selected = [str(v) for v in form.getlist("day")]
        save_settings(AppUiSettings(posting_days=selected))
    return RedirectResponse("/?notice=schedule-saved", status_code=303)


@app.post("/actions/publish-due")
async def action_publish():
    try:
        results = publish_due()
        notice = "published" if results else "not-a-posting-day-or-empty"
        return RedirectResponse(f"/?notice={notice}", status_code=303)
    except Exception as exc:
        return RedirectResponse("/?error=" + _safe_error(exc), status_code=303)


@app.get("/api/status")
async def api_status():
    return JSONResponse(get_settings().public_status())


@app.exception_handler(HTTPException)
async def http_exc(_, exc: HTTPException):
    return JSONResponse({"detail": _safe_error(exc)}, status_code=exc.status_code)
