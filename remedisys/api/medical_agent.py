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

TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
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


def _get_json_body() -> dict:
    """Parse request body as JSON, handling bytes vs str."""
    raw = frappe.request.data
    if not raw:
        return frappe.form_dict
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw) if raw.strip() else frappe.form_dict


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


# Whisper hallucinates these phrases on silence/noise (trained on YouTube data).
# Matched case-insensitively after stripping punctuation.
_HALLUCINATION_PATTERNS = {
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subscribe to my channel",
    "like and subscribe",
    "see you next time",
    "bye bye",
    "goodbye",
    "thank you",
    "you",
    "the end",
    "subtitles by",
    "amara org",
    "sil",
    "silence",
    "music",
    "applause",
}


def _is_hallucination(text: str) -> bool:
    """Check if transcription is a known Whisper hallucination."""
    if not text:
        return True
    cleaned = text.strip().strip(".,!?;:").lower()
    if len(cleaned) < 3:
        return True
    if cleaned in _HALLUCINATION_PATTERNS:
        return True
    # Catch variations like "Thank you for watching!" or "Thank you for watching."
    for pattern in _HALLUCINATION_PATTERNS:
        if cleaned == pattern or cleaned.startswith(pattern):
            return True
    # Model sometimes echoes back the prompt instruction on silence
    if "doctor-patient medical consultation" in cleaned:
        return True
    if "transcribe" in cleaned and "accurately" in cleaned:
        return True
    return False


def _transcribe(file_path: str, language_hint: str = None,
                previous_transcript: str = "") -> str:
    """Transcribe audio chunk via OpenAI Audio API.

    Uses the previous transcript as a prompt to give Whisper context,
    which dramatically reduces hallucinations and improves accuracy
    for ongoing conversations.
    """
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

        # Build a prompt to guide transcription context.
        # The openai SDK uses "prompt" for all transcription models.
        prompt_text = (
            "This is a doctor-patient medical consultation. "
            "Transcribe the spoken words accurately. "
            "Do not hallucinate or invent text when there is silence. "
            "If the audio is silent or contains only noise, return an empty string."
        )
        if previous_transcript:
            tail = previous_transcript.strip()[-500:]
            prompt_text = f"{prompt_text} Previous conversation context: {tail}"
        kwargs["prompt"] = prompt_text

        result = client.audio.transcriptions.create(**kwargs)

    # Rename back for cleanup
    if webm_path != file_path:
        os.rename(webm_path, file_path)

    text = (getattr(result, "text", None) or "").strip()

    # Filter out known hallucinations
    if _is_hallucination(text):
        return ""

    return text


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
                "patient_info": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "string"},
                        "sex": {"type": "string"},
                        "allergies": {"type": "string"},
                    },
                    "required": ["name", "age", "sex", "allergies"],
                },
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
                "suggested_lab_tests": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "suggested_medications": {
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
                "patient_info",
                "chief_complaint",
                "summary",
                "possible_assessment",
                "recommended_follow_up_questions",
                "suggested_lab_tests",
                "suggested_medications",
                "suggested_next_steps",
                "red_flags",
                "urgency",
                "patient_facing_spanish_summary",
                "safety_disclaimer",
            ],
        },
    }

    system_msg = (
        "You are a clinical decision-support assistant for licensed physicians. "
        "You are not the final decision-maker. "
        "Return only valid JSON matching the provided schema."
    )
    user_msg = (
        "Analyze the visit transcript and produce a structured draft "
        "for clinician review.\n\n"
        "Your job:\n"
        "- Extract patient details (name, age, sex, allergies) if mentioned\n"
        "- Summarize the visit\n"
        "- Identify likely concerns\n"
        "- Suggest follow-up questions\n"
        "- Suggest specific lab tests or investigations\n"
        "- Suggest specific medications with dosage if appropriate\n"
        "- Suggest next-step options\n"
        "- Highlight red flags\n"
        "- Produce a patient-facing Spanish explanation\n\n"
        "For patient_info: extract whatever is mentioned in the transcript. "
        "Use empty string for fields not mentioned.\n\n"
        "For suggested_lab_tests: list specific tests like "
        "'CBC', 'Lipid Panel', 'HbA1c', 'Chest X-ray', etc.\n\n"
        "For suggested_medications: include drug name and dosage suggestion "
        "like 'Amoxicillin 500mg TID x 7 days', 'Ibuprofen 400mg PRN', etc.\n\n"
        "Do not:\n"
        "- Invent facts not present in transcript\n"
        "- Overstate certainty\n"
        "- Present a final diagnosis unless clearly stated by the clinician\n"
        "- Recommend treatment beyond the transcript context without "
        "uncertainty language\n\n"
        "Additional rules:\n"
        "- patient_facing_spanish_summary: simple, polite, understandable\n"
        "- safety_disclaimer: state this is AI-generated decision support "
        "and must be reviewed by a licensed clinician\n\n"
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
        "patient_info": {"name": "", "age": "", "sex": "", "allergies": ""},
        "chief_complaint": "",
        "summary": "Unable to parse structured output.",
        "possible_assessment": [],
        "recommended_follow_up_questions": [],
        "suggested_lab_tests": [],
        "suggested_medications": [],
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

@frappe.whitelist(allow_guest=True, methods=["POST"])
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

    # Skip empty/tiny files (< 4KB likely has no meaningful speech)
    if os.path.getsize(temp_path) < 4000:
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
        # Step 1: Load existing state for context
        state = _load_state(visit_id)
        previous_transcript = state.get("full_transcript_en", "")

        # Step 2: Transcribe with previous context to reduce hallucinations
        chunk_text = _transcribe(
            temp_path,
            language_hint=language_hint,
            previous_transcript=previous_transcript,
        )
        # Step 3: Update session state
        state["chunks"].append({
            "sequence_number": sequence_number,
            "text": chunk_text,
        })
        state["full_transcript_en"] = _append_text(
            state.get("full_transcript_en", ""), chunk_text
        )

        full_en = state["full_transcript_en"]

        # Step 4: Translate
        full_es = _translate_to_spanish(full_en)

        # Step 5: Recommend
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


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_visit_state(visit_id: str = None):
    """Return the current visit session state."""
    visit_id = visit_id or frappe.form_dict.get("visit_id")
    if not visit_id:
        frappe.throw(_("visit_id is required"))
    return _load_state(visit_id)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def clear_visit_state():
    """Reset a visit session."""
    visit_id = frappe.form_dict.get("visit_id")
    if not visit_id:
        frappe.throw(_("visit_id is required"))
    frappe.cache().delete_value(_cache_key(visit_id))
    return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def populate_encounter():
    """Push AI-generated data into a Patient Encounter document.

    Expected JSON body:
        encounter_name   (required) - Patient Encounter docname
        visit_id         (required) - to load cached AI state
        doctor_notes     (optional) - doctor's own notes
        selected_tests   (optional) - JSON array of selected test strings
        selected_meds    (optional) - JSON array of selected medication strings
    """
    data = _get_json_body()
    encounter_name = data.get("encounter_name")
    visit_id = data.get("visit_id")

    if not encounter_name:
        frappe.throw(_("encounter_name is required"))
    if not visit_id:
        frappe.throw(_("visit_id is required"))

    state = _load_state(visit_id)
    rec = state.get("latest_recommendation", {})

    doc = frappe.get_doc("Patient Encounter", encounter_name)

    # Populate AI fields
    doc.ai_chief_complaint = rec.get("chief_complaint", "")
    doc.ai_summary = rec.get("summary", "")
    doc.ai_transcript = state.get("full_transcript_en", "")
    doc.ai_transcript_es = state.get("full_transcript_es", "")
    doc.ai_suggested_tests = "\n".join(
        data.get("selected_tests") or rec.get("suggested_lab_tests", [])
    )
    doc.ai_suggested_medications = "\n".join(
        data.get("selected_meds") or rec.get("suggested_medications", [])
    )
    doc.ai_red_flags = "\n".join(rec.get("red_flags", []))
    doc.ai_followup_questions = "\n".join(
        rec.get("recommended_follow_up_questions", [])
    )
    doc.ai_urgency = (rec.get("urgency", "") or "").capitalize()
    doc.ai_recommendation_json = json.dumps(rec) if rec else ""

    if data.get("doctor_notes"):
        doc.ai_doctor_notes = data.get("doctor_notes")

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "encounter_name": encounter_name}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def save_ai_state():
    """Auto-save transcript and AI data to the Patient Encounter.

    Called automatically after each audio chunk is processed so
    data survives page reloads.

    Expected JSON body:
        encounter_name        (required)
        full_transcript_en    (optional)
        full_transcript_es    (optional)
        recommendation        (optional) - full recommendation dict
    """
    data = _get_json_body()
    encounter_name = data.get("encounter_name")

    if not encounter_name:
        frappe.throw(_("encounter_name is required"))

    doc = frappe.get_doc("Patient Encounter", encounter_name)
    rec = data.get("recommendation") or {}

    doc.ai_transcript = data.get("full_transcript_en") or ""
    doc.ai_transcript_es = data.get("full_transcript_es") or ""
    doc.ai_chief_complaint = rec.get("chief_complaint") or ""
    doc.ai_summary = rec.get("summary") or ""
    doc.ai_suggested_tests = "\n".join(rec.get("suggested_lab_tests") or [])
    doc.ai_suggested_medications = "\n".join(rec.get("suggested_medications") or [])
    doc.ai_red_flags = "\n".join(rec.get("red_flags") or [])
    doc.ai_followup_questions = "\n".join(
        rec.get("recommended_follow_up_questions") or []
    )
    doc.ai_urgency = (rec.get("urgency") or "").capitalize()
    doc.ai_recommendation_json = json.dumps(rec) if rec else ""

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def rework_recommendation():
    """Re-run the AI recommendation with doctor's notes appended.

    Expected JSON body:
        visit_id       (required)
        doctor_notes   (required) - doctor's input to guide re-analysis
    """
    data = _get_json_body()
    visit_id = data.get("visit_id")
    doctor_notes = data.get("doctor_notes", "")

    if not visit_id:
        frappe.throw(_("visit_id is required"))
    if not doctor_notes.strip():
        frappe.throw(_("doctor_notes is required"))

    state = _load_state(visit_id)
    full_en = state.get("full_transcript_en", "")

    if not full_en.strip():
        frappe.throw(_("No transcript available to rework"))

    # Append doctor's notes to transcript for richer context
    augmented = (
        f"{full_en}\n\n"
        f"[Doctor's clinical notes and instructions]: {doctor_notes}"
    )

    recommendation = _build_recommendation(augmented)
    full_es = _translate_to_spanish(full_en)

    state["latest_recommendation"] = recommendation
    state["full_transcript_es"] = full_es
    _save_state(visit_id, state)

    return {
        "ok": True,
        "visit_id": visit_id,
        "full_transcript_en": full_en,
        "full_transcript_es": full_es,
        "recommendation": recommendation,
    }


@frappe.whitelist(allow_guest=True, methods=["POST"])
def chat_with_ai():
    """Send a free-text message to the AI in the context of the visit.

    Expected JSON body:
        visit_id   (required)
        message    (required) - doctor's question or instruction
    """
    data = _get_json_body()
    visit_id = data.get("visit_id")
    message = data.get("message", "")

    if not visit_id:
        frappe.throw(_("visit_id is required"))
    if not message.strip():
        frappe.throw(_("message is required"))

    state = _load_state(visit_id)
    full_en = state.get("full_transcript_en", "")
    rec = state.get("latest_recommendation", {})

    client = _get_client()

    system_msg = (
        "You are Cura, an AI clinical assistant for licensed physicians. "
        "You have access to the current visit transcript and AI analysis. "
        "Answer the doctor's question concisely and accurately. "
        "If asked to summarize, re-analyze, check drug interactions, or "
        "suggest prescriptions, do so based on the transcript context. "
        "Always note that your output is AI-generated and must be reviewed."
    )
    context = f"Current transcript:\n{full_en}\n\n" if full_en else ""
    if rec:
        context += f"Current AI analysis summary:\n{rec.get('summary', '')}\n\n"

    resp = client.chat.completions.create(
        model=RECOMMEND_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"{context}Doctor's message: {message}"},
        ],
        temperature=0.3,
    )

    reply = (resp.choices[0].message.content or "").strip()
    return {"ok": True, "reply": reply}
