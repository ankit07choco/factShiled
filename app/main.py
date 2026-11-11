import os
import json
import logging
from typing import Optional
from fastapi import FastAPI, Request, File, UploadFile, Form, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.pipeline import pipeline
from app.core.local_web_search import get_local_model_status
from app.core.preprocessing import extract_text_from_video
from app.webhook.meta_whatsapp import (
    META_APP_SECRET,
    META_PHONE_NUMBER_ID,
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
    description="Multi-Signal Claim Verification Architecture combining Fact-Check DB Lookup, Vector Search, Linguistic Style Classifier, and Meta Cloud API WhatsApp Webhook.",
    version="1.0.0"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Renders the main web dashboard interface."""
    return templates.TemplateResponse(request, "index.html", {"request": request})

@app.post("/api/verify")
async def verify_claim_endpoint(
    text: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None)
):
    """
    Core claim verification API endpoint.
    Accepts text claim or image forward upload for OCR & multi-signal verification.
    """
    if image and video:
        return JSONResponse(status_code=400, content={"error": "Upload either an image or a video, not both."})

    image_bytes = None
    if image:
        if image.content_type and not image.content_type.startswith("image/"):
            return JSONResponse(status_code=415, content={"error": "The uploaded file is not an image."})
        image_bytes = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content={"error": "Image uploads must be 16 MB or smaller."})

    if video:
        if video.content_type and not video.content_type.startswith("video/"):
            return JSONResponse(status_code=415, content={"error": "The uploaded file is not a video."})
        video_bytes = await video.read(MAX_UPLOAD_BYTES + 1)
        if len(video_bytes) > MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content={"error": "Video uploads must be 16 MB or smaller."})
        video_result = extract_text_from_video(video_bytes)
        has_caption = bool(text and text.strip())
        if not video_result.get("success") and not has_caption:
            status_code = 503 if "unavailable" in video_result.get("error", "").lower() else 422
            return JSONResponse(status_code=status_code, content={"error": video_result["error"]})
        text = " ".join(
            part for part in (text, video_result.get("extracted_text", "")) if part
        )
    else:
        video_result = None

    if not text and not image_bytes and not video:
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide claim text or upload an image or video."}
        )

    result = pipeline.verify(text=text, image_bytes=image_bytes)
    if video_result:
        result["video_result"] = video_result
    if result.get("error") and not result.get("input_text"):
        return JSONResponse(status_code=422, content={"error": result["error"], **result})
    return JSONResponse(content=result)

@app.get("/api/integrations-status")
async def integrations_status():
    """Reports local search/model readiness without exposing credentials."""
    local_model_status = get_local_model_status()
    return {
        "local_fact_check_records": len(fact_check_engine.fact_checks),
        "web_search_provider": "Bing public search page with Wikipedia fallback",
        "web_search_requires_api_key": False,
        "local_model_provider": "Ollama",
        "local_model_available": local_model_status["available"],
        "local_model": local_model_status["model"],
        "local_model_message": local_model_status["message"],
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
    """Reports whether WhatsApp credentials are configured without exposing them."""
    return {
        "verify_token_configured": bool(os.getenv("META_VERIFY_TOKEN")),
        "app_secret_configured": bool(META_APP_SECRET),
        "access_token_configured": bool(WHATSAPP_API_TOKEN),
        "phone_number_id_configured": bool(META_PHONE_NUMBER_ID),
        "webhook_path": "/webhook/whatsapp",
        "live_messaging_ready": bool(
            os.getenv("META_VERIFY_TOKEN")
            and META_APP_SECRET
            and WHATSAPP_API_TOKEN
            and META_PHONE_NUMBER_ID
        )
    }
