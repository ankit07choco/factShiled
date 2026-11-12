import os
import json
import logging
import secrets
import sqlite3
from typing import Any, Literal, Optional
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from app.core.pipeline import pipeline
from app.core.image_origin import get_image_origin_model_status
from app.core.local_web_search import get_local_model_status
from app.core.verification_store import verification_store
from app.webhook.meta_whatsapp import (
    META_APP_SECRET,
    META_PHONE_NUMBER_ID,
    WEBHOOK_VERIFY_TOKEN,
    WHATSAPP_API_TOKEN,
    download_meta_media,
    process_whatsapp_payload,
    send_meta_whatsapp_message,
    verify_meta_signature,
    verify_meta_webhook,
)
from app.core.fact_check_search import fact_check_engine
from app.core.fever_benchmark import get_fever_status, search_fever_claims

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

app = FastAPI(
    title="FactShield AI - WhatsApp Misinformation Verification Engine",
    description="Claim verification with published fact-checks, public web search, local AI assessment, image OCR and AI-origin assessment, and Meta WhatsApp Cloud API webhooks.",
    version="1.0.0"
)

ADMIN_USERNAME = os.getenv("FACTSHIELD_ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("FACTSHIELD_ADMIN_PASSWORD", "")
_configured_session_secret = os.getenv("FACTSHIELD_SESSION_SECRET", "")
SESSION_SECRET_CONFIGURED = len(_configured_session_secret) >= 32
SESSION_SECRET_KEY = _configured_session_secret or secrets.token_urlsafe(32)
SESSION_COOKIE_SECURE = os.getenv(
    "FACTSHIELD_SESSION_COOKIE_SECURE", "false"
).strip().lower() in {"1", "true", "yes"}
ADMIN_LOGIN_ENABLED = bool(
    ADMIN_USERNAME
    and len(ADMIN_PASSWORD) >= 12
    and SESSION_SECRET_CONFIGURED
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="factshield_session",
    max_age=12 * 60 * 60,
    same_site="lax",
    https_only=SESSION_COOKIE_SECURE,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
ANDROID_APK_PATH = os.path.join(STATIC_DIR, "downloads", "factshield-android.apk")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class AdminCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class VerificationRecordUpdate(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)
    verdict: Literal["Likely True", "Likely False"]
    confidence_score: int = Field(ge=0, le=100)
    explanation: str = Field(max_length=4000)
    sources: list[dict[str, Any]] = Field(default_factory=list)


def require_admin(
    request: Request,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
) -> bool:
    if request.session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    expected_token = request.session.get("csrf_token")
    if (
        not expected_token
        or not x_csrf_token
        or not secrets.compare_digest(expected_token, x_csrf_token)
    ):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")
    return True


@app.get("/api/session")
async def get_session(request: Request):
    role = request.session.get("role")
    if role != "admin":
        return {"role": "user"}
    csrf_token = request.session.get("csrf_token")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = csrf_token
    return {"role": "admin", "csrf_token": csrf_token}


@app.post("/api/admin/login")
async def admin_login(credentials: AdminCredentials, request: Request):
    if not ADMIN_LOGIN_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin login is not configured. Set FACTSHIELD_ADMIN_USERNAME, "
                "a FACTSHIELD_ADMIN_PASSWORD of at least 12 characters, and a "
                "random FACTSHIELD_SESSION_SECRET of at least 32 characters."
            ),
        )
    if not (
        secrets.compare_digest(
            credentials.username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8")
        )
        and secrets.compare_digest(
            credentials.password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")
        )
    ):
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

    request.session.clear()
    csrf_token = secrets.token_urlsafe(32)
    request.session.update({"role": "admin", "csrf_token": csrf_token})
    return {"role": "admin", "csrf_token": csrf_token}


@app.post("/api/admin/logout", dependencies=[Depends(require_admin)])
async def admin_logout(request: Request):
    request.session.clear()
    return {"role": "user"}


@app.get("/api/verifications")
async def get_saved_verifications(
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    records, total = verification_store.list_records(
        search=search, limit=limit, offset=offset
    )
    return {"total": total, "data": records}


@app.put(
    "/api/verifications/{record_id}",
    dependencies=[Depends(require_admin)],
)
async def update_saved_verification(
    record_id: int,
    changes: VerificationRecordUpdate,
):
    if not changes.claim.strip():
        raise HTTPException(status_code=422, detail="Claim text cannot be blank.")
    try:
        updated = verification_store.update_record(record_id, dict(changes))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Another saved record already has the same normalized claim.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Saved verification not found.")
    return {"updated": True}


@app.delete(
    "/api/verifications/{record_id}",
    dependencies=[Depends(require_admin)],
)
async def delete_saved_verification(
    record_id: int
):
    if not verification_store.delete_record(record_id):
        raise HTTPException(status_code=404, detail="Saved verification not found.")
    return {"deleted": True}


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Renders the main web dashboard interface."""
    return templates.TemplateResponse(request, "index.html", {"request": request})

@app.api_route("/downloads/android", methods=["GET", "HEAD"], include_in_schema=False)
async def download_android_app():
    """Downloads the Android app package from the website."""
    if not os.path.isfile(ANDROID_APK_PATH):
        return JSONResponse(
            status_code=404,
            content={"error": "The Android app download is not available."},
        )
    return FileResponse(
        ANDROID_APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="FactShield-Android.apk",
    )

@app.post("/api/verify")
async def verify_claim_endpoint(
    request: Request,
    text: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    input_mode: Optional[str] = Form(None),
):
    """
    Core claim verification API endpoint.
    Accepts text claim or image forward upload for OCR & multi-signal verification.
    """
    if "video" in await request.form():
        return JSONResponse(
            status_code=415,
            content={"error": "Video verification is not supported. Upload text or an image."}
        )

    image_bytes = None
    if image:
        if image.content_type and not image.content_type.startswith("image/"):
            return JSONResponse(status_code=415, content={"error": "The uploaded file is not an image."})
        image_bytes = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content={"error": "Image uploads must be 16 MB or smaller."})

    if not text and not image_bytes:
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide claim text or upload an image."}
        )

    result = pipeline.verify(text=text, image_bytes=image_bytes, input_mode=input_mode)
    if result.get("error") and not result.get("input_text") and not result.get("image_origin"):
        return JSONResponse(status_code=422, content={"error": result["error"], **result})
    try:
        saved_record = verification_store.save_if_conclusive(result)
    except sqlite3.Error:
        logger.exception("Could not save a completed verification to the database.")
        return JSONResponse(
            status_code=503,
            content={
                "error": "Verification completed, but the result could not be saved.",
                "verification_result": result,
            },
        )
    result["saved_to_database"] = saved_record is not None
    if saved_record:
        result["database_record_id"] = saved_record["id"]
    return JSONResponse(content=result)

@app.get("/api/integrations-status")
async def integrations_status():
    """Reports local search/model readiness without exposing credentials."""
    local_model_status = get_local_model_status()
    image_origin_model_status = get_image_origin_model_status()
    return {
        "local_fact_check_records": len(fact_check_engine.fact_checks),
        "web_search_provider": "Bing public search page with Wikipedia fallback",
        "web_search_requires_api_key": False,
        "local_model_provider": "Ollama",
        "local_model_available": local_model_status["available"],
        "local_model": local_model_status["model"],
        "local_model_message": local_model_status["message"],
        "image_origin_model_provider": "Ollama vision",
        "image_origin_model_available": image_origin_model_status["available"],
        "image_origin_model": image_origin_model_status["model"],
        "image_origin_model_message": image_origin_model_status["message"],
        "note": (
            "Bing search results are retrieved without an API key; verdicts are "
            "generated locally by Ollama. Published local fact-check records take precedence."
        )
    }

@app.get("/api/fact-checks")
async def get_fact_checks(
    query: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    language: Optional[str] = Query(None)
):
    """
    Returns filterable fact-check database items.
    """
    all_checks = fact_check_engine.fact_checks

    filtered = []
    for item in all_checks:
        match_query = True
        match_cat = True
        match_lang = True

        if query:
            q = query.lower()
            match_query = (
                q in item.get('claim', '').lower() or
                q in item.get('claim_hi', '').lower() or
                q in item.get('summary', '').lower() or
                any(q in k.lower() for k in item.get('keywords', []))
            )

        if category and category != "All":
            match_cat = item.get('category') == category

        if language and language != "All":
            match_lang = item.get('language') == language

        if match_query and match_cat and match_lang:
            filtered.append(item)

    return {"total": len(filtered), "data": filtered}

@app.get("/api/benchmark/status")
async def fever_benchmark_status():
    """Reports availability of the separate FEVER research benchmark."""
    return get_fever_status()

@app.get("/api/benchmark/search")
async def search_fever_benchmark(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(10, ge=1, le=20)
):
    """Searches FEVER benchmark claims without using their labels for live verdicts."""
    status = get_fever_status()
    if not status["available"]:
        return JSONResponse(
            status_code=503,
            content={"error": status["note"], "data": []}
        )
    results = search_fever_claims(q, limit=limit)
    return {
        "query": q,
        "dataset": status["dataset"],
        "attribution": status["attribution"],
        "warning": "Research benchmark labels are not published fact-check verdicts.",
        "total": len(results),
        "data": results,
    }

@app.get("/api/analytics")
async def get_analytics():
    """
    Provides aggregated analytics for misinformation categories, verdicts, and Indian languages.
    """
    checks = fact_check_engine.fact_checks
    
    categories = {}
    verdicts = {"Likely False": 0, "Disputed": 0, "Unverified": 0, "Likely True": 0}
    languages = {}

    for item in checks:
        cat = item.get('category', 'Uncategorized')
        categories[cat] = categories.get(cat, 0) + 1

        v = item.get('confidence_rating', item.get('verdict', 'Likely False'))
        if v in verdicts:
            verdicts[v] += 1
        elif item.get('verdict') == 'False':
            verdicts['Likely False'] += 1
        elif item.get('verdict') == 'True':
            verdicts['Likely True'] += 1

        lang = item.get('language', 'en')
        languages[lang] = languages.get(lang, 0) + 1

    return {
        "total_fact_checks_indexed": len(checks),
        "saved_verifications": verification_store.summary(),
        "verdict_distribution": verdicts,
        "category_breakdown": categories,
        "language_breakdown": languages,
        "pipeline_weights": {
            "fact_check_api": "40%",
            "semantic_vector_search": "25%",
            "style_classifier": "20%",
            "evidence_retrieval": "15%"
        }
    }

@app.get("/api/viva-info")
async def get_viva_info():
    """
    Returns comprehensive documentation, evaluation metrics (Precision, Recall, F1),
    cross-dataset testing results, error analysis, and stated limitations for academic presentation.
    """
    metrics_path = os.path.join(BASE_DIR, '..', 'data', 'evaluation_metrics.json')
    metrics_data = {}
    if os.path.exists(metrics_path):
        with open(metrics_path, 'r', encoding='utf-8') as f:
            metrics_data = json.load(f)

    return {
        "title": "WhatsApp Misinformation Claim Verification System",
        "core_design_decision": "Style classifiers learn writing style rather than truth and fail on real WhatsApp forwards. Published local fact-checks take precedence; public Bing results plus a local Ollama model provide an optional cited assessment.",
        "architecture_modules": [
            "Signal 1: Fact-check lookup against the bundled local ClaimReview database",
            "Signal 2: Semantic Vector Search (TF-IDF + Cosine Similarity over Indian & Global DB)",
            "Signal 3: Public Bing web search and local Ollama assessment with source links",
            "Signal 4: Linguistic Style & Sensationalism Classifier (ALL CAPS, forwarding pressure, urgency)",
            "Source citations are displayed but domain authority is not independently scored",
            "Preprocessing: Language Detection (langdetect for Hindi/Bengali/English) & Image OCR Text Extraction"
        ],
        "evaluation_metrics": metrics_data.get("pipeline_in_domain_metrics", {}),
        "cross_dataset_test": metrics_data.get("cross_dataset_evaluation", {}),
        "error_analysis": metrics_data.get("error_analysis", []),
        "limitations": [
            "Unverified is a legitimate & expected output when a claim is brand-new and has no published fact-checks yet.",
            "Satire, opinion pieces, and nuanced half-truths cannot be forcibly fit into a strict binary label.",
            "Confidence score (0-100%) represents an automated statistical estimate, not absolute ground truth.",
            "Bing search and Ollama assessments are AI-generated and are not published fact-checks; Bing results may be blocked or change format.",
            "Code-mixed regional scripts (e.g., Hinglish written in Latin script) require continuous vocabulary updates."
        ]
    }

@app.get("/webhook/whatsapp")
async def meta_webhook_verification(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """Meta WhatsApp Cloud API Webhook Verification Endpoint."""
    challenge = verify_meta_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is not None:
        return Response(content=str(challenge), media_type="text/plain")
    return Response(status_code=403, content="Invalid verification token")

@app.post("/webhook/whatsapp")
async def meta_webhook_post(request: Request):
    """Meta WhatsApp Cloud API Webhook & Simulator Event Handler."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": "Request body must be valid JSON."})

    is_live_webhook = (
        payload.get("object") == "whatsapp_business_account"
        and not payload.get("simulated")
    )
    if is_live_webhook:
        if not META_APP_SECRET:
            return JSONResponse(
                status_code=503,
                content={"error": "Configure META_APP_SECRET before enabling live WhatsApp webhooks."}
            )
        if not verify_meta_signature(
            raw_body, request.headers.get("X-Hub-Signature-256"), META_APP_SECRET
        ):
            return JSONResponse(status_code=403, content={"error": "Invalid webhook signature."})

    result = process_whatsapp_payload(payload, media_downloader=download_meta_media)
    if is_live_webhook:
        message_results = result.get("messages", [result])
        for message_result in message_results:
            sender_id = message_result.get("sender_id")
            reply_text = message_result.get("reply_text")
            if not sender_id or not reply_text:
                continue
            delivered = send_meta_whatsapp_message(
                sender_id,
                reply_text,
                phone_number_id=META_PHONE_NUMBER_ID,
                access_token=WHATSAPP_API_TOKEN
            )
            message_result["delivered"] = delivered
            if not delivered:
                logger.error("Could not deliver WhatsApp reply to sender %s", sender_id)
    return JSONResponse(content=result)


@app.get("/api/whatsapp-status")
async def whatsapp_status():
    """Reports Meta WhatsApp Cloud API readiness without exposing credentials."""
    return {
        "provider": "Meta WhatsApp Cloud API",
        "verify_token_configured": bool(WEBHOOK_VERIFY_TOKEN),
        "app_secret_configured": bool(META_APP_SECRET),
        "access_token_configured": bool(WHATSAPP_API_TOKEN),
        "phone_number_id_configured": bool(META_PHONE_NUMBER_ID),
        "webhook_path": "/webhook/whatsapp",
        "live_messaging_ready": bool(
            WEBHOOK_VERIFY_TOKEN
            and META_APP_SECRET
            and WHATSAPP_API_TOKEN
            and META_PHONE_NUMBER_ID
        ),
    }
