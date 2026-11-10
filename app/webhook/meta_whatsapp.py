import hashlib
import hmac
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

from app.core.pipeline import pipeline
from app.core.preprocessing import extract_text_from_video

logger = logging.getLogger(__name__)

WEBHOOK_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
WHATSAPP_API_TOKEN = os.getenv("META_WHATSAPP_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v26.0")
MAX_MEDIA_BYTES = 16 * 1024 * 1024

MediaDownloader = Callable[[str], Tuple[bytes, str]]


def verify_meta_webhook(mode: Optional[str], token: Optional[str], challenge: Optional[str]):
    """Handles Meta WhatsApp Cloud API webhook handshake (GET request)."""
    if WEBHOOK_VERIFY_TOKEN and mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        return int(challenge) if challenge and challenge.isdigit() else challenge
    return None


def verify_meta_signature(body: bytes, signature: Optional[str], app_secret: str) -> bool:
    """Validates Meta's X-Hub-Signature-256 header when an app secret is configured."""
    if not signature or not signature.startswith("sha256=") or not app_secret:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _is_meta_media_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed_hosts = ("facebook.com", "fbcdn.net", "fbsbx.com")
    return parsed.scheme == "https" and any(
        host == domain or host.endswith("." + domain)
        for domain in allowed_hosts
    )


def download_meta_media(media_id: str) -> Tuple[bytes, str]:
    """Fetches a WhatsApp Cloud API media object with size and host validation."""
    if not WHATSAPP_API_TOKEN:
        raise RuntimeError("WhatsApp media download is not configured.")
    if not media_id:
        raise ValueError("WhatsApp media ID is missing.")

    headers = {"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"}
    endpoint = (
        f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/"
        f"{quote(media_id, safe='')}"
    )
    metadata_response = requests.get(endpoint, headers=headers, timeout=10)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    media_url = metadata.get("url")
    if not media_url or not _is_meta_media_url(media_url):
        raise ValueError("Meta returned an invalid media URL.")

    media_response = requests.get(media_url, headers=headers, timeout=20, stream=True)
    media_response.raise_for_status()
    if not _is_meta_media_url(media_response.url):
        raise ValueError("Meta media download redirected to an untrusted host.")

    content_length = media_response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_MEDIA_BYTES:
        raise ValueError("WhatsApp media exceeds the 16 MB processing limit.")

    content = bytearray()
    for chunk in media_response.iter_content(chunk_size=64 * 1024):
        content.extend(chunk)
        if len(content) > MAX_MEDIA_BYTES:
            raise ValueError("WhatsApp media exceeds the 16 MB processing limit.")

    mime_type = metadata.get("mime_type") or media_response.headers.get(
        "Content-Type", ""
    ).split(";", 1)[0]
    return bytes(content), mime_type


def _reply_for_message(
    message: Dict[str, Any],
    media_downloader: Optional[MediaDownloader]
) -> Dict[str, Any]:
    sender_id = message.get("from")
    message_type = message.get("type", "")
    caption = ""
    result = None
    received_text = ""
    warning = ""

    if message_type == "text":
        received_text = message.get("text", {}).get("body", "")
        result = pipeline.verify(text=received_text)
    elif message_type in ("image", "video"):
        media_info = message.get(message_type, {})
        caption = media_info.get("caption", "")
        received_text = caption
        media_id = media_info.get("id")
        if not media_downloader:
            warning = "Media download is not configured. Configure the WhatsApp access token."
        elif not media_id:
            warning = "The WhatsApp message did not include a media ID."
        else:
            try:
                media_bytes, mime_type = media_downloader(media_id)
                if message_type == "image" and mime_type.startswith("image/"):
                    result = pipeline.verify(text=caption or None, image_bytes=media_bytes)
                    if result.get("ocr_result", {}).get("error") and caption:
                        warning = result["ocr_result"]["error"]
                elif message_type == "video" and mime_type.startswith("video/"):
                    video_result = extract_text_from_video(media_bytes)
                    received_text = " ".join(
                        part
                        for part in (caption, video_result.get("extracted_text", ""))
                        if part
                    )
                    if received_text:
                        result = pipeline.verify(text=received_text)
                        result["video_result"] = video_result
                        if not video_result.get("success"):
                            warning = video_result["error"]
                        else:
                            warning = "Only on-screen text was analyzed; video speech is not transcribed."
                    else:
                        warning = video_result.get("error", "Video could not be analyzed.")
                else:
                    warning = f"Unsupported media type: {mime_type or 'unknown'}."
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                logger.warning("WhatsApp media processing failed: %s", exc)
                warning = str(exc)
    else:
        warning = "Please send a text message, image, or video."

    if result and result.get("error") and not result.get("whatsapp_reply"):
        warning = result["error"]

    if result and result.get("whatsapp_reply"):
        reply_text = result["whatsapp_reply"]
    else:
        reply_text = warning or "I could not read this message. Please send text or a clearer image."

    if warning and result and result.get("whatsapp_reply"):
        reply_text = f"{reply_text}\n\n⚠️ {warning}"

    response = {
        "success": result is not None or bool(warning),
        "sender_id": sender_id,
        "message_type": message_type,
        "received_text": received_text,
        "reply_text": reply_text
    }
    if result:
        response["pipeline_result"] = result
    if sender_id and reply_text:
        response["meta_response_payload"] = {
            "messaging_product": "whatsapp",
            "to": sender_id,
            "type": "text",
            "text": {"body": reply_text}
        }
    return response


def process_whatsapp_payload(
    payload: Dict[str, Any],
    media_downloader: Optional[MediaDownloader] = None
) -> Dict[str, Any]:
    """Parses a Meta webhook event and prepares replies for its incoming messages."""
    entries = payload.get("entry", [])
    if not entries:
        test_message = payload.get("message") or payload.get("text")
        if isinstance(test_message, str) and test_message:
            result = pipeline.verify(text=test_message)
            return {
                "success": True,
                "simulated": True,
                "pipeline_result": result,
                "reply_text": result.get("whatsapp_reply")
            }
        return {"error": "Invalid payload structure", "success": False}

    message_results = []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                message_results.append(_reply_for_message(message, media_downloader))

    if not message_results:
        return {"status": "event_acknowledged_no_message", "success": True}

    first_result = dict(message_results[0])
    first_result["messages"] = message_results
    return first_result


def send_meta_whatsapp_message(
    to_phone: str,
    text: str,
    phone_number_id: str = META_PHONE_NUMBER_ID,
    access_token: str = WHATSAPP_API_TOKEN
) -> bool:
    """Sends a text reply using the configured Meta WhatsApp Cloud API credentials."""
    if not access_token or not phone_number_id:
        logger.error("WhatsApp reply delivery is not configured.")
        return False

    url = (
        f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/"
        f"{quote(phone_number_id, safe='')}/messages"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text}
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        if not response.ok:
            logger.error(
                "Meta WhatsApp send failed with status %s: %s",
                response.status_code,
                response.text[:500]
            )
        return response.ok
    except requests.RequestException:
        logger.exception("Could not send WhatsApp reply to %s", to_phone)
        return False
