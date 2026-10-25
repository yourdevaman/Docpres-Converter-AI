"""Docpres Converter AI — local Flask backend.

Extracts visible text from prescription/medicine-pack images via Gemini.
It is a transcription aid, not a medical decision system. Keep the Gemini API
key in a local .env file; never place it in index.html or browser JavaScript.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)

# Accept either index.html beside app.py or the conventional templates/index.html.
ROOT_INDEX = BASE_DIR / "index.html"
TEMPLATES_INDEX = BASE_DIR / "templates" / "index.html"
if TEMPLATES_INDEX.is_file():
    TEMPLATE_DIR = BASE_DIR / "templates"
elif ROOT_INDEX.is_file():
    TEMPLATE_DIR = BASE_DIR
else:
    TEMPLATE_DIR = BASE_DIR / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
MAX_IMAGE_BYTES = 7 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + (1024 * 1024)

DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_LANGUAGES = {"English", "Hinglish", "Hindi"}
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """You are the document-extraction assistant for Docpres Converter AI.
This is a medical document transcription aid, NOT a clinician, pharmacist,
diagnostic tool, medicine-authenticity service, or prescribing system.

Return ONLY one JSON object with exactly this general schema:
{
  "document_type": "prescription | medicine_pack | unclear",
  "overall_readability": "good | fair | poor",
  "summary": "brief neutral summary of visible text",
  "medicines": [{
    "name_as_written": "string or Unclear",
    "possible_name_reading": "string or Unclear",
    "strength_as_written": "string or Unclear",
    "instructions_as_written": "string or Unclear",
    "duration_as_written": "string or Unclear",
    "confidence": "high | medium | low",
    "uncertainty_note": "unclear characters or why review is needed"
  }],
  "other_text": ["faithfully transcribed non-medicine text"],
  "verification_flags": ["details that require pharmacist/doctor confirmation"],
  "safe_next_steps": ["short practical steps"]
}
Rules:
- Transcribe only what is visibly present. Never invent medicine names, strengths,
  doses, frequencies, routes, durations, diagnosis, or patient/prescriber details.
- If illegible, use "Unclear" and explain uncertainty; do not guess.
- Do not calculate doses or recommend changing, starting, stopping, or substituting medicine.
- Do not claim authenticity, safety, approval, availability under PMBJP/Janaushadhi,
  or equivalence based on an image. Do not certify interactions or contraindications.
- If the image is not a prescription or medicine package, set document_type to "unclear"
  and do not infer medical facts.
- Keep output concise, valid JSON only, no Markdown fences.
"""


def get_api_key() -> str:
    """Read the key only from server environment or .env."""
    return os.getenv("GEMINI_API_KEY", "").strip()


def get_model() -> str:
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip()
    model = model.removeprefix("models/")
    return model or DEFAULT_MODEL


def api_key_is_configured() -> bool:
    key = get_api_key()
    if not key:
        return False
    lowered = key.lower()
    placeholders = ("replace_with_", "your_api_key", "your_key_here", "paste_your_key", "your_new_api_key")
    return not any(marker in lowered for marker in placeholders)


def as_text(value: Any, fallback: str = "Unclear") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return fallback


def safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    doc_type = as_text(raw.get("document_type"), "unclear").lower()
    if doc_type not in {"prescription", "medicine_pack", "unclear"}:
        doc_type = "unclear"
    readability = as_text(raw.get("overall_readability"), "poor").lower()
    if readability not in {"good", "fair", "poor"}:
        readability = "poor"
    medicines_in = raw.get("medicines")
    if not isinstance(medicines_in, list):
        medicines_in = []
    fields = (
        "name_as_written", "possible_name_reading", "strength_as_written",
        "instructions_as_written", "duration_as_written", "confidence", "uncertainty_note",
    )
    medicines: list[dict[str, str]] = []
    for item in medicines_in:
        if not isinstance(item, dict):
            continue
        medicine = {field: as_text(item.get(field)) for field in fields}
        confidence = medicine["confidence"].lower()
        medicine["confidence"] = confidence if confidence in {"high", "medium", "low"} else "low"
        medicines.append(medicine)
    return {
        "document_type": doc_type,
        "overall_readability": readability,
        "summary": as_text(raw.get("summary"), "No reliable summary was returned."),
        "medicines": medicines,
        "other_text": safe_list(raw.get("other_text")),
        "verification_flags": safe_list(raw.get("verification_flags")),
        "safe_next_steps": safe_list(raw.get("safe_next_steps")),
    }


def infer_mime_type(filename: str, reported_mime: str | None) -> str | None:
    mime = (reported_mime or "").lower().strip()
    if mime in ALLOWED_MIME_TYPES:
        return mime
    guessed, _ = mimetypes.guess_type(filename)
    guessed = (guessed or "").lower()
    return guessed if guessed in ALLOWED_MIME_TYPES else None


def parse_gemini_json(body: dict[str, Any]) -> dict[str, Any]:
    candidates = body.get("candidates") or []
    if not candidates:
        feedback = body.get("promptFeedback", {})
        app.logger.warning("Gemini returned no candidates; prompt feedback: %s", json.dumps(feedback)[:500])
        raise ValueError("Gemini could not read this image. Try a clearer, well-lit photo.")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    raw_text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not raw_text:
        app.logger.warning("Gemini returned empty text; finish reason=%s", candidate.get("finishReason", "unknown"))
        raise ValueError("No readable text was returned. Try a clearer image or rotate it upright.")
    raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.IGNORECASE).strip()
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("The model did not return a JSON object.")
    return parsed


@app.get("/")
def home():
    """Serve the main page from either supported project layout."""
    if not (TEMPLATE_DIR / "index.html").is_file():
        return "Docpres Converter AI: index.html not found beside app.py or in templates/.", 500
    return render_template("index.html")


@app.get("/api/health")
def health():
    """Confirm the backend is live and indicate whether a key is configured."""
    return jsonify({"ok": True, "api_configured": api_key_is_configured(), "model": get_model()})


@app.post("/api/analyze")
def analyze():
    if not api_key_is_configured():
        return jsonify({"error": "Gemini API is not configured. Add GEMINI_API_KEY to the .env file and restart the server."}), 503

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a prescription or medicine-pack image first."}), 400
    mime_type = infer_mime_type(uploaded.filename, uploaded.mimetype)
    if mime_type is None:
        return jsonify({"error": "Unsupported file type. Upload a JPG, PNG, or WEBP image."}), 415
    image_bytes = uploaded.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        return jsonify({"error": "The selected file is empty."}), 400
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return jsonify({"error": "Image is too large. Please use an image smaller than 7 MB."}), 413

    language = request.form.get("language", "English")
    if language not in ALLOWED_LANGUAGES:
        language = "English"
    language_instruction = {
        "English": "Write summary, verification flags, and safe next steps in plain English.",
        "Hinglish": "Write summary, verification flags, and safe next steps in Hinglish (Hindi in Latin script). Keep transcription fields faithful to the image.",
        "Hindi": "Write summary, verification flags, and safe next steps in simple Hindi. Keep transcription fields faithful to the image.",
    }[language]

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [
            {"text": "Read this image carefully. Return the required JSON object only. Preserve uncertainty and never guess. " + language_instruction},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "maxOutputTokens": 2500},
    }

    model = quote(get_model(), safe="-._")
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": get_api_key()},
            json=payload,
            timeout=(10, 90),
        )
    except requests.Timeout:
        return jsonify({"error": "Analysis timed out. Try a clearer or smaller image."}), 504
    except requests.RequestException as exc:
        app.logger.warning("Gemini connection failed (%s).", type(exc).__name__)
        return jsonify({"error": "Could not reach Gemini. Check internet connection and try again."}), 502

    if not response.ok:
        # Log provider detail in terminal for debugging; never return the provider response to the browser.
        app.logger.warning("Gemini request failed: HTTP %s; provider body=%s", response.status_code, response.text[:600])
        if response.status_code in (400, 404):
            return jsonify({"error": f"Gemini rejected the model or request (HTTP {response.status_code}). Check GEMINI_MODEL and the terminal."}), 502
        if response.status_code in (401, 403):
            return jsonify({"error": "Gemini rejected the API key or project access. Create/enable a key in Google AI Studio, update .env, and restart the server."}), 502
        if response.status_code == 429:
            return jsonify({"error": "Gemini quota or rate limit reached. Check API quota in Google AI Studio."}), 429
        if response.status_code == 402:
            return jsonify({"error": "Google reports a billing/payment prerequisite. Check your Gemini project billing status."}), 502
        return jsonify({"error": f"Gemini returned HTTP {response.status_code}. See the VS Code terminal for details."}), 502

    try:
        result = normalize_result(parse_gemini_json(response.json()))
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
        app.logger.warning("Could not parse Gemini response (%s).", type(exc).__name__)
        if isinstance(exc, ValueError) and str(exc).startswith(("Gemini could not", "No readable")):
            message = str(exc)
        else:
            message = "The AI response could not be parsed safely. Try another clear image."
        return jsonify({"error": message}), 502
    return jsonify({"result": result})


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_error):
    return jsonify({"error": "Upload is too large. Please use an image under 7 MB."}), 413


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    """Return JSON for API failures rather than Flask's HTML error page."""
    if isinstance(error, HTTPException):
        status = error.code or 500
        message = error.description
    else:
        status = 500
        message = "An unexpected backend error occurred. See the VS Code terminal for the traceback."
        app.logger.exception("Unhandled server error on %s", request.path)
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), status
    return message, status


if __name__ == "__main__":
    try:
        port = int(os.getenv("PORT", "5000"))
    except (TypeError, ValueError):
        port = 5000
    print("\nDocpres Converter AI backend starting...")
    print(f"Project folder: {BASE_DIR}")
    print(f"Frontend found: {(TEMPLATE_DIR / 'index.html').is_file()}")
    print(f"API key configured: {api_key_is_configured()}")
    print(f"Model: {get_model()}")
    print(f"Open: http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
