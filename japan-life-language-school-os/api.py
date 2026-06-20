from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from school_platform.i18n import append_lang_to_url, localize_school_platform_html, normalize_ui_lang
from school_platform.router import router as school_platform_router

app = FastAPI(title="Japan Life Language School OS", version="1.0.0")
app.include_router(school_platform_router)


@app.middleware("http")
async def school_platform_language_middleware(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/school-platform"):
        return response

    lang = normalize_ui_lang(request.query_params.get("lang"))
    location = response.headers.get("location")
    if location:
        response.headers["location"] = append_lang_to_url(location, lang)

    if request.url.path.startswith("/school-platform/api"):
        return response

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    localized_html = localize_school_platform_html(body.decode("utf-8"), lang)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return HTMLResponse(content=localized_html, status_code=response.status_code, headers=headers)


@app.get("/", include_in_schema=False)
def home(request: Request):
    target = "/school-platform"
    query_string = request.url.query
    if query_string:
        target = f"{target}?{query_string}"
    return RedirectResponse(url=target, status_code=307)


@app.get("/marketplace", include_in_schema=False)
def marketplace_home(request: Request):
    return RedirectResponse(url="/school-platform", status_code=307)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "mode": "school_platform_only"}
