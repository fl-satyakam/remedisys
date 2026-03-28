"""
Medical AI Assistant Backend API
Handles audio transcription, Spanish translation, and clinical recommendations
using OpenAI models. All endpoints require authentication.
"""

import os
import json
import tempfile

import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
RECOMMEND_MODEL = os.getenv("OPENAI_RECOMMEND_MODEL", "gpt-4o")


def _get_client():
    """Lazy-load OpenAI client so import errors surface at call time."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY") or frappe.conf.get("openai_api_key")
    if not api_key:
        frappe.throw(
            _("Missing OpenAI API key. Set 'openai_api_key' in site_config.json "
              "or the OPENAI_API_KEY environment variable."),
            title=_("Configuration Error"),
        )
    return OpenAI(api_key=api_key)


# ---------------------------------------------------------------------------
# Session state helpers (Redis cache, 8-hour TTL per visit)
# ---------------------------------------------------------------------------

def _cache_key(visit_id: str) -> str:
    return f"medical_agent:visit:{visit_id}"


def _load_state(visit_id: str) -> dict:
    raw = frappe.cache().get_value(_cache_key(visit_id))
    if not raw:
        return {
            "chunks": [],
            "full_transcript_en": "",
            "full_transcript_es": "",
            "latest_recommendation": {},
        }
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _save_state(visit_id: str, state: dict) -> None:
    frappe.cache().set_value(
        _cache_key(visit_id),
        json.dumps(state),
        expires_in_sec=60 * 60 * 8,
    )


def _append_text(existing: str, new_text: str) -> str:
    existing = (existing or "").strip()
    new_text = (new_text or "").strip()
    if not existing:
        return new_text
    if not new_text:
        return existing
    return f"{existing} {new_text}"


# ---------------------------------------------------------------------------
# OpenAI helpers
# ---------------------------------------------------------------------------

def _transcribe(file_path: str, language_hint: str = None) -> str:
    """Transcribe audio chunk via OpenAI Audio API."""
    client = _get_client()

    # Ensure the file has a .webm extension so OpenAI recognizes the format
    webm_path = file_path
    if not file_path.endswith(".webm"):
        webm_path = file_path + ".webm"
        os.rename(file_path, webm_path)

    with open(webm_path, "rb") as f:
        kwargs = {"file": f, "model": TRANSCRIBE_MODEL}
        if language_hint:
            kwargs["language"] = language_hint
        result = client.audio.transcriptions.create(**kwargs)

    # Rename back for cleanup
    if webm_path != file_path:
        os.rename(webm_path, file_path)

    return (getattr(result, "text", None) or "").strip()


def _translate_to_spanish(transcript_en: str) -> str:
    """Translate English transcript to medically-faithful Spanish."""
    if not transcript_en.strip():
        return ""

    client = _get_client()
    prompt = (
        "You are a medical interpreter assistant.\n"
        "Translate the following clinician-patient transcript into Spanish.\n\n"
        "Rules:\n"
        "- Preserve medical meaning exactly.\n"
        "- Do not invent symptoms, history, or diagnosis.\n"
        "- Keep names, medications, dosages, and abbreviations accurate.\n"
        "- Output only the Spanish translation.\n\n"
        f"Transcript:\n{transcript_en}"
    )

    resp = client.chat.completions.create(
        model=RECOMMEND_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


def _build_recommendation(transcript_en: str) -> dict:
    """Generate structured clinical decision-support JSON."""
    if not transcript_en.strip():
        return {}

    client = _get_client()

    schema = {
        "name": "clinical_recommendation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "chief_complaint": {"type": "string"},
                "summary": {"type": "string"},
                "possible_assessment": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "recommended_follow_up_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "suggested_next_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "red_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "moderate", "high", "emergent"],
                },
                "patient_facing_spanish_summary": {"type": "string"},
                "safety_disclaimer": {"type": "string"},
            },
            "required": [
                "chief_complaint",
                "summary",
                "possible_assessment",
                "recommended_follow_up_questions",
                "suggested_next_steps",
                "red_flags",
                "urgency",
                "patient_facing_spanish_summary",
                "safety_disclaimer",
            ],
        },
    }

    system_msg = "Return only valid JSON matching the provided schema."
    user_msg = (
        "You are a clinical decision-support assistant for licensed physicians.\n"
        "Analyze the visit transcript and produce a structured draft for clinician review.\n\n"
        "Critical rules:\n"
        "- Do NOT present output as final diagnosis.\n"
        "- Do NOT fabricate facts not present in transcript.\n"
        "- Clearly surface uncertainty.\n"
        "- Recommendations must be conservative and safe.\n"
        "- Include urgent escalation red flags when appropriate.\n"
        "- patient_facing_spanish_summary: simple, polite, understandable.\n"
        "- safety_disclaimer: state this is AI-generated and must be reviewed "
        "by a licensed clinician.\n\n"
        f"Transcript:\n{transcript_en}"
    )

    resp = client.chat.completions.create(
        model=RECOMMEND_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_schema", "json_schema": schema},
        temperature=0.3,
    )

    content = resp.choices[0].message.content
    if not content:
        return _fallback_recommendation()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        frappe.log_error("Invalid JSON from OpenAI model", "Medical Agent")
        return _fallback_recommendation()


def _fallback_recommendation() -> dict:
    return {
        "chief_complaint": "",
        "summary": "Unable to parse structured output.",
        "possible_assessment": [],
        "recommended_follow_up_questions": [],
        "suggested_next_steps": [],
        "red_flags": [],
        "urgency": "moderate",
        "patient_facing_spanish_summary": "",
        "safety_disclaimer": (
            "AI-generated output must be reviewed by a licensed clinician."
        ),
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist(methods=["POST"])
def process_audio_chunk():
    """
    Receive a 10-second audio chunk and return incremental results.

    Form-data fields:
        visit_id          (required)
        sequence_number   (required)
        audio_chunk       (file, required)
        language_hint     (optional, e.g. "en" or "es")
    """
    visit_id = frappe.form_dict.get("visit_id")
    sequence_number = frappe.form_dict.get("sequence_number")
    language_hint = frappe.form_dict.get("language_hint")

    if not visit_id:
        frappe.throw(_("visit_id is required"))

    uploaded = frappe.request.files.get("audio_chunk")
    if not uploaded:
        frappe.throw(_("audio_chunk file is required"))

    # Save uploaded blob to a temp file
    suffix = os.path.splitext(uploaded.filename or "")[-1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        uploaded.save(tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = tmp.name

    # Skip empty/tiny files (< 1KB likely has no audio)
    if os.path.getsize(temp_path) < 1000:
        os.remove(temp_path)
        return {
            "ok": True,
            "visit_id": visit_id,
            "sequence_number": sequence_number,
            "chunk_transcript_en": "",
            "full_transcript_en": _load_state(visit_id).get("full_transcript_en", ""),
            "full_transcript_es": _load_state(visit_id).get("full_transcript_es", ""),
            "recommendation": _load_state(visit_id).get("latest_recommendation", {}),
        }

    try:
        # Step 1: Transcribe
        chunk_text = _transcribe(temp_path, language_hint=language_hint)

        # Step 2: Update session state
        state = _load_state(visit_id)
        state["chunks"].append({
            "sequence_number": sequence_number,
            "text": chunk_text,
        })
        state["full_transcript_en"] = _append_text(
            state.get("full_transcript_en", ""), chunk_text
        )

        full_en = state["full_transcript_en"]

        # Step 3: Translate
        full_es = _translate_to_spanish(full_en)

        # Step 4: Recommend
        recommendation = _build_recommendation(full_en)

        state["full_transcript_es"] = full_es
        state["latest_recommendation"] = recommendation
        _save_state(visit_id, state)

        return {
            "ok": True,
            "visit_id": visit_id,
            "sequence_number": sequence_number,
            "chunk_transcript_en": chunk_text,
            "full_transcript_en": full_en,
            "full_transcript_es": full_es,
            "recommendation": recommendation,
        }
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@frappe.whitelist(methods=["GET"])
def get_visit_state(visit_id: str = None):
    """Return the current visit session state."""
    visit_id = visit_id or frappe.form_dict.get("visit_id")
    if not visit_id:
        frappe.throw(_("visit_id is required"))
    return _load_state(visit_id)


@frappe.whitelist(methods=["POST"])
def clear_visit_state():
    """Reset a visit session."""
    visit_id = frappe.form_dict.get("visit_id")
    if not visit_id:
        frappe.throw(_("visit_id is required"))
    frappe.cache().delete_value(_cache_key(visit_id))
    return {"ok": True}
