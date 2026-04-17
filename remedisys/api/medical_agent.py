"""
Medical AI Assistant Backend API
Handles audio transcription, Spanish translation, and clinical recommendations.

Transcription provider is selectable:
  - Default: OpenAI ``gpt-4o-transcribe`` (no diarization, single-speaker).
  - Diarized: GCP Speech-to-Text v1p1beta1 ``medical_conversation`` with 2-speaker
    diarization — used when ``USE_GCP_STT`` (env) or ``use_gcp_stt`` (site_config)
    is truthy AND Google credentials are reachable.

Required configuration:
  OPENAI_API_KEY                         (env or site_config.openai_api_key)
  USE_GCP_STT=1                          (env or site_config.use_gcp_stt)  -- optional
  GOOGLE_APPLICATION_CREDENTIALS=<path>  (env or site_config.google_application_credentials)

GCP setup (one time):
  1. gcloud services enable speech.googleapis.com --project <project>
  2. Create a service account with role ``roles/speech.client``.
  3. Download the JSON key, store at a path readable by the bench process.
  4. Set GOOGLE_APPLICATION_CREDENTIALS to that path and USE_GCP_STT=1.
  5. Install the SDK: ``bench pip install 'google-cloud-speech>=2.26.0'``.

If GCP fails for any reason (quota, auth, unsupported audio), the chunk falls
back to OpenAI transcription so the encounter continues without interruption.
"""

import os
import json
import tempfile
import time

import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
RECOMMEND_MODEL = os.getenv("OPENAI_RECOMMEND_MODEL", "gpt-4o")

# GCP Speech-to-Text toggle. Set USE_GCP_STT=1 (env) or "use_gcp_stt": 1 in
# site_config.json to swap transcription from OpenAI to GCP with diarization.
# Requires GOOGLE_APPLICATION_CREDENTIALS env pointing at a service-account JSON
# (or equivalent site_config["google_application_credentials"]).
GCP_STT_MODEL = os.getenv("GCP_STT_MODEL", "medical_conversation")
GCP_STT_LANGUAGE = os.getenv("GCP_STT_LANGUAGE", "en-US")


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


def _gcp_stt_enabled() -> bool:
    """True when the feature flag is on AND a credentials path is reachable."""
    flag = os.getenv("USE_GCP_STT") or frappe.conf.get("use_gcp_stt")
    if not flag or str(flag).lower() in ("0", "false", "no", ""):
        return False
    # Either env var is set (ADC) or a file path is present.
    creds = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or frappe.conf.get("google_application_credentials")
    )
    if creds and os.path.exists(creds):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
        return True
    # If GOOGLE_APPLICATION_CREDENTIALS is set directly, trust it.
    return bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))


def _get_gcp_client():
    from google.cloud import speech_v1p1beta1 as speech
    return speech, speech.SpeechClient()


# ---------------------------------------------------------------------------
# GCS audio archival
# ---------------------------------------------------------------------------

def _gcs_bucket_name():
    """Return the configured audio archive bucket, or None if disabled."""
    return frappe.conf.get("audio_gcs_bucket") or os.getenv("AUDIO_GCS_BUCKET")


def _gcs_client():
    """Lazy-load a google-cloud-storage Client using the stt SA creds.

    Returns None if the SDK isn't installed or no credentials are reachable.
    All exceptions swallowed — this is best-effort archival only.
    """
    try:
        creds = (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or frappe.conf.get("google_application_credentials")
        )
        if creds and os.path.exists(creds):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
        from google.cloud import storage
        return storage.Client()
    except Exception:
        return None


def _upload_audio_chunk(file_path, appointment, seq, mime_type="audio/webm"):
    """Upload a single audio chunk to GCS. Fire-and-forget, never raises.

    Layout: gs://<bucket>/<YYYY-MM-DD>/<appointment>/chunk-<seq>.webm
    Returns the gs:// URI on success, empty string on any failure.
    """
    try:
        bucket_name = _gcs_bucket_name()
        if not bucket_name or not file_path or not os.path.exists(file_path):
            return ""
        client = _gcs_client()
        if client is None:
            return ""
        from datetime import datetime as _dt
        date_prefix = _dt.utcnow().strftime("%Y-%m-%d")
        safe_appt = (appointment or "unknown").replace("/", "_")
        blob_path = f"{date_prefix}/{safe_appt}/chunk-{seq}.webm"
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(file_path, content_type=mime_type or "audio/webm")
        return f"gs://{bucket_name}/{blob_path}"
    except Exception:
        # Never raise into /encounter hot path.
        return ""


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
            "utterances": [],
            "full_transcript_en": "",
            "full_transcript_es": "",
            "latest_recommendation": {},
            "speaker_swap": 0,
            "audio_refs": {},
        }
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    state = json.loads(raw)
    state.setdefault("utterances", [])
    state.setdefault("speaker_swap", 0)
    state.setdefault("audio_refs", {})
    return state


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
# Telemetry — append-only Medical Agent Log
# ---------------------------------------------------------------------------

def _log_event(event_type, visit_id=None, duration_ms=None, provider=None,
               appointment=None, sequence_number=None, speaker_count=None,
               text_length=None, error_message=None, extra=None):
    """Insert a Medical Agent Log row. MUST NEVER raise.

    Called from the hot path of /encounter. Any exception here (e.g. first-run
    before migration, DB lock, etc.) is swallowed so the main flow never breaks.
    """
    try:
        doc = frappe.get_doc({
            "doctype": "Medical Agent Log",
            "event_type": event_type,
            "visit_id": visit_id,
            "appointment": appointment,
            "sequence_number": sequence_number,
            "duration_ms": int(duration_ms) if duration_ms is not None else None,
            "provider": provider,
            "speaker_count": speaker_count,
            "text_length": text_length,
            "error_message": error_message,
            "extra_json": json.dumps(extra) if extra else None,
        })
        doc.insert(ignore_permissions=True)
        # Best-effort commit; if commit fails we still don't want to raise.
        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        # Absolutely never raise into the encounter flow.
        try:
            frappe.db.rollback()
        except Exception:
            pass


def _now_ms():
    return int(time.monotonic() * 1000)


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


def _transcribe_gcp(file_path: str, language_hint: str = None) -> list:
    """Transcribe a WebM/Opus chunk via GCP Speech-to-Text with 2-speaker
    diarization. Returns a list of utterances:
        [{"speaker_tag": int, "text": str}, ...]

    Notes on GCP diarization behavior:
    - Sync `recognize()` puts the diarized transcript in the LAST result's
      first alternative. Its `.words` have `speaker_tag` populated.
    - Earlier results in the response are per-utterance without tags — we
      ignore them and use only the diarized final pass.
    - `medical_conversation` requires `use_enhanced=True`.
    - WebM/Opus from MediaRecorder is 48 kHz by default; we configured the
      browser to 16 kHz for lower bandwidth, but GCP auto-detects the
      container's sample rate when `sample_rate_hertz` is omitted.
    """
    speech, client = _get_gcp_client()

    with open(file_path, "rb") as f:
        audio_bytes = f.read()

    diarization = speech.SpeakerDiarizationConfig(
        enable_speaker_diarization=True,
        min_speaker_count=2,
        max_speaker_count=2,
    )
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
        language_code=(language_hint or GCP_STT_LANGUAGE),
        model=GCP_STT_MODEL,
        use_enhanced=True,
        enable_automatic_punctuation=True,
        diarization_config=diarization,
    )
    audio = speech.RecognitionAudio(content=audio_bytes)

    try:
        response = client.recognize(config=config, audio=audio)
    except Exception as exc:
        frappe.log_error(
            message=f"GCP STT failed: {exc}",
            title="Medical Agent",
        )
        return []

    if not response.results:
        return []

    words = list(response.results[-1].alternatives[0].words)
    if not words:
        return []

    # Group consecutive same-tag words into utterances.
    utterances = []
    current_tag = words[0].speaker_tag
    current_words = []
    for w in words:
        if w.speaker_tag != current_tag and current_words:
            utterances.append({
                "speaker_tag": int(current_tag),
                "text": " ".join(current_words).strip(),
            })
            current_words = []
            current_tag = w.speaker_tag
        current_words.append(w.word)
    if current_words:
        utterances.append({
            "speaker_tag": int(current_tag),
            "text": " ".join(current_words).strip(),
        })

    # Drop utterances that look like hallucination noise.
    return [u for u in utterances if u["text"] and not _is_hallucination(u["text"])]


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


# ---------------------------------------------------------------------------
# AI Module Config (admin-configurable recommendation modules)
# ---------------------------------------------------------------------------

# Hardcoded fallback used when the DocType isn't migrated yet (fresh install)
# so /encounter keeps working. Mirrors the original baked-in schema.
_DEFAULT_MODULES = [
    {
        "module_key": "chief_complaint",
        "display_title": "Chief Complaint",
        "output_type": "paragraph",
        "display_order": 10,
        "prompt_fragment": "Single-line chief complaint in the patient's words.",
        "empty_state_text": "—",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "summary",
        "display_title": "Summary",
        "output_type": "paragraph",
        "display_order": 20,
        "prompt_fragment": (
            "2-3 sentence clinical summary of what has been discussed so far."
        ),
        "empty_state_text": "Will populate as the conversation progresses…",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "possible_assessment",
        "display_title": "Possible Assessment",
        "output_type": "chip_list",
        "display_order": 30,
        "prompt_fragment": "Up to 4 differential diagnoses ranked by likelihood.",
        "empty_state_text": "—",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "suggested_lab_tests",
        "display_title": "Suggested Lab Tests",
        "output_type": "chip_list",
        "display_order": 40,
        "prompt_fragment": (
            "0-6 relevant diagnostic tests. Use specific names like 'CBC', "
            "'Lipid Panel', 'HbA1c', 'Chest X-ray'."
        ),
        "empty_state_text": "—",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "suggested_medications",
        "display_title": "Suggested Medications",
        "output_type": "chip_list",
        "display_order": 50,
        "prompt_fragment": (
            "0-6 candidate medications with dose hints like "
            "'Amoxicillin 500mg TID x 7 days' or 'Ibuprofen 400mg PRN'."
        ),
        "empty_state_text": "—",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "recommended_follow_up_questions",
        "display_title": "Follow-up Questions",
        "output_type": "chip_list",
        "display_order": 60,
        "prompt_fragment": (
            "Up to 5 questions the doctor should still ask to narrow the diagnosis."
        ),
        "empty_state_text": "—",
        "card_color": "",
        "icon_svg": "",
    },
    {
        "module_key": "red_flags",
        "display_title": "Red Flags",
        "output_type": "bullet_list",
        "display_order": 70,
        "prompt_fragment": (
            "Urgent red flags that warrant immediate attention; empty array if none."
        ),
        "empty_state_text": "—",
        "card_color": "#ef4444",
        "icon_svg": "",
    },
]

_DEFAULT_SYSTEM_PROMPT = (
    "You are a clinical decision-support assistant for licensed physicians. "
    "You are not the final decision-maker. "
    "Return only valid JSON matching the provided schema."
)
_DEFAULT_URGENCY_SCALE = (
    "Use one of: low, moderate, high, emergent. "
    "'emergent' means the patient needs immediate attention."
)
_DEFAULT_SAFETY_DISCLAIMER = (
    "AI-generated decision support must be reviewed by a licensed clinician."
)


def _load_ai_module_config() -> dict:
    """Load the AI Module Config Single doc and return a normalized dict.

    Falls back to hardcoded defaults if the DocType isn't installed yet
    (e.g. fresh install before migrate ran) so /encounter never breaks.
    """
    fallback = {
        "system_prompt": _DEFAULT_SYSTEM_PROMPT,
        "urgency_scale": _DEFAULT_URGENCY_SCALE,
        "safety_disclaimer": _DEFAULT_SAFETY_DISCLAIMER,
        "modules": list(_DEFAULT_MODULES),
    }

    try:
        if not frappe.db.exists("DocType", "AI Module Config"):
            return fallback
        doc = frappe.get_cached_doc("AI Module Config")
    except Exception:
        return fallback

    modules = []
    for row in doc.get("modules") or []:
        if not row.get("enabled"):
            continue
        if not row.get("module_key") or not row.get("prompt_fragment"):
            continue
        modules.append({
            "module_key": row.get("module_key"),
            "display_title": row.get("display_title") or row.get("module_key"),
            "output_type": row.get("output_type") or "chip_list",
            "display_order": int(row.get("display_order") or 0),
            "prompt_fragment": row.get("prompt_fragment") or "",
            "empty_state_text": row.get("empty_state_text") or "—",
            "card_color": row.get("card_color") or "",
            "icon_svg": row.get("icon_svg") or "",
        })

    if not modules:
        return fallback

    modules.sort(key=lambda m: (m["display_order"], m["module_key"]))
    return {
        "system_prompt": (doc.get("recommendation_system_prompt") or _DEFAULT_SYSTEM_PROMPT).strip(),
        "urgency_scale": (doc.get("urgency_scale") or _DEFAULT_URGENCY_SCALE).strip(),
        "safety_disclaimer": (doc.get("safety_disclaimer") or _DEFAULT_SAFETY_DISCLAIMER).strip(),
        "modules": modules,
    }


def _get_ai_module_config() -> dict:
    """Per-request cached accessor for the AI module config."""
    cache = getattr(frappe.local, "_ai_module_config_cache", None)
    if cache is None:
        cache = _load_ai_module_config()
        frappe.local._ai_module_config_cache = cache
    return cache


def _build_recommendation(transcript_en: str) -> dict:
    """Generate structured clinical decision-support JSON.

    Schema + prompt are assembled from the AI Module Config Single so
    admins can add/remove/reorder modules without code changes.
    """
    if not transcript_en.strip():
        return {}

    client = _get_client()
    cfg = _get_ai_module_config()
    modules = cfg["modules"]

    # Build JSON schema dynamically from enabled modules.
    properties = {
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
        "urgency": {
            "type": "string",
            "enum": ["low", "moderate", "high", "emergent"],
        },
        "patient_facing_spanish_summary": {"type": "string"},
        "safety_disclaimer": {"type": "string"},
    }
    required = [
        "patient_info",
        "urgency",
        "patient_facing_spanish_summary",
        "safety_disclaimer",
    ]

    for m in modules:
        key = m["module_key"]
        if m["output_type"] == "paragraph":
            properties[key] = {"type": "string"}
        else:  # chip_list or bullet_list
            properties[key] = {"type": "array", "items": {"type": "string"}}
        required.append(key)

    schema = {
        "name": "clinical_recommendation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
    }

    # Build prompt fragment list in display order.
    module_instructions = "\n".join(
        f"- {m['module_key']}: {m['prompt_fragment']}" for m in modules
    )

    system_msg = cfg["system_prompt"]
    user_msg = (
        "Analyze the visit transcript and produce a structured draft "
        "for clinician review.\n\n"
        "For each JSON key below, follow its instruction:\n"
        f"{module_instructions}\n\n"
        "Additionally:\n"
        "- patient_info: extract name, age, sex, allergies if mentioned; "
        "use empty string for fields not mentioned.\n"
        f"- urgency: {cfg['urgency_scale']}\n"
        "- patient_facing_spanish_summary: simple, polite, understandable Spanish.\n"
        f"- safety_disclaimer: {cfg['safety_disclaimer']}\n\n"
        "Do not:\n"
        "- Invent facts not present in transcript\n"
        "- Overstate certainty\n"
        "- Present a final diagnosis unless clearly stated by the clinician\n\n"
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
        cached = _load_state(visit_id)
        return {
            "ok": True,
            "visit_id": visit_id,
            "sequence_number": sequence_number,
            "chunk_transcript_en": "",
            "chunk_utterances": [],
            "full_transcript_en": cached.get("full_transcript_en", ""),
            "full_transcript_es": cached.get("full_transcript_es", ""),
            "recommendation": cached.get("latest_recommendation", {}),
            "speaker_swap": int(cached.get("speaker_swap", 0)),
        }

    try:
        # Step 1: Load existing state for context
        state = _load_state(visit_id)
        previous_transcript = state.get("full_transcript_en", "")
        swap = bool(state.get("speaker_swap", 0))

        # Step 2: Transcribe — prefer GCP diarization when enabled, else OpenAI
        chunk_utterances = []
        transcribe_provider = None
        transcribe_start = _now_ms()
        if _gcp_stt_enabled():
            transcribe_provider = f"gcp:{GCP_STT_MODEL}"
            try:
                raw_utts = _transcribe_gcp(temp_path, language_hint=language_hint)
            except Exception as e:
                frappe.log_error(
                    f"GCP STT failed, falling back to OpenAI: {e}",
                    "medical_agent.process_audio_chunk",
                )
                _log_event(
                    "error", visit_id=visit_id, appointment=visit_id,
                    sequence_number=sequence_number,
                    provider=transcribe_provider,
                    error_message=str(e),
                )
                raw_utts = []

            for u in raw_utts:
                tag = u.get("speaker_tag", 1)
                # Map speaker_tag → role. GCP tags start at 1.
                # Default: tag 1 = doctor (left bubble), tag 2 = patient (right bubble).
                # speaker_swap flips the mapping when the doctor clicks "Swap speakers".
                if tag == 1:
                    speaker = "patient" if swap else "doctor"
                else:
                    speaker = "doctor" if swap else "patient"
                chunk_utterances.append({
                    "speaker": speaker,
                    "speaker_tag": int(tag),
                    "text": u.get("text", ""),
                })

            if not chunk_utterances:
                # GCP returned nothing usable — fall back to OpenAI for this chunk.
                transcribe_provider = f"openai:{TRANSCRIBE_MODEL}"
                chunk_text = _transcribe(
                    temp_path,
                    language_hint=language_hint,
                    previous_transcript=previous_transcript,
                )
                if chunk_text:
                    chunk_utterances.append({
                        "speaker": "patient",
                        "speaker_tag": 0,
                        "text": chunk_text,
                    })
            chunk_text = " ".join(u["text"] for u in chunk_utterances).strip()
        else:
            transcribe_provider = f"openai:{TRANSCRIBE_MODEL}"
            chunk_text = _transcribe(
                temp_path,
                language_hint=language_hint,
                previous_transcript=previous_transcript,
            )
            if chunk_text:
                chunk_utterances.append({
                    "speaker": "patient",
                    "speaker_tag": 0,
                    "text": chunk_text,
                })
        _log_event(
            "transcribe", visit_id=visit_id, appointment=visit_id,
            sequence_number=sequence_number,
            duration_ms=_now_ms() - transcribe_start,
            provider=transcribe_provider,
            speaker_count=len({u.get("speaker_tag") for u in chunk_utterances}) or None,
            text_length=len(chunk_text or ""),
        )

        # Step 2b: Archive audio to GCS (best-effort, never raises).
        # We call it synchronously AFTER transcription finishes so it doesn't
        # add latency before the doctor's visible feedback. All exceptions
        # are swallowed by _upload_audio_chunk itself.
        try:
            gcs_uri = _upload_audio_chunk(
                temp_path,
                appointment=visit_id,
                seq=sequence_number,
                mime_type=(uploaded.mimetype or "audio/webm"),
            )
            if gcs_uri:
                refs = state.setdefault("audio_refs", {})
                refs[str(sequence_number)] = gcs_uri
        except Exception:
            # Defensive: _upload_audio_chunk already swallows, but be paranoid.
            pass

        # Step 3: Update session state
        state["chunks"].append({
            "sequence_number": sequence_number,
            "text": chunk_text,
        })
        if chunk_utterances:
            state.setdefault("utterances", []).extend([
                {**u, "sequence_number": sequence_number} for u in chunk_utterances
            ])
        state["full_transcript_en"] = _append_text(
            state.get("full_transcript_en", ""), chunk_text
        )

        full_en = state["full_transcript_en"]

        # Step 4: Translate
        translate_start = _now_ms()
        try:
            full_es = _translate_to_spanish(full_en)
            _log_event(
                "translate", visit_id=visit_id, appointment=visit_id,
                sequence_number=sequence_number,
                duration_ms=_now_ms() - translate_start,
                provider=f"openai:{RECOMMEND_MODEL}",
                text_length=len(full_es or ""),
            )
        except Exception as e:
            _log_event(
                "error", visit_id=visit_id, appointment=visit_id,
                sequence_number=sequence_number,
                duration_ms=_now_ms() - translate_start,
                provider=f"openai:{RECOMMEND_MODEL}",
                error_message=f"translate: {e}",
            )
            raise

        # Step 5: Recommend
        recommend_start = _now_ms()
        try:
            recommendation = _build_recommendation(full_en)
            _log_event(
                "recommend", visit_id=visit_id, appointment=visit_id,
                sequence_number=sequence_number,
                duration_ms=_now_ms() - recommend_start,
                provider=f"openai:{RECOMMEND_MODEL}",
                text_length=len(json.dumps(recommendation)) if recommendation else 0,
            )
        except Exception as e:
            _log_event(
                "error", visit_id=visit_id, appointment=visit_id,
                sequence_number=sequence_number,
                duration_ms=_now_ms() - recommend_start,
                provider=f"openai:{RECOMMEND_MODEL}",
                error_message=f"recommend: {e}",
            )
            raise

        state["full_transcript_es"] = full_es
        state["latest_recommendation"] = recommendation
        _save_state(visit_id, state)

        return {
            "ok": True,
            "visit_id": visit_id,
            "sequence_number": sequence_number,
            "chunk_transcript_en": chunk_text,
            "chunk_utterances": chunk_utterances,
            "full_transcript_en": full_en,
            "full_transcript_es": full_es,
            "recommendation": recommendation,
            "speaker_swap": int(state.get("speaker_swap", 0)),
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
def set_speaker_swap():
    """Toggle which diarized tag maps to doctor vs patient.

    Body: visit_id (required), swap (0/1).
    Also re-labels utterances already stored in state so the UI
    can rebuild bubbles consistently from get_visit_state.
    """
    visit_id = frappe.form_dict.get("visit_id")
    if not visit_id:
        frappe.throw(_("visit_id is required"))
    swap = 1 if str(frappe.form_dict.get("swap") or "0") in ("1", "true", "yes") else 0

    state = _load_state(visit_id)
    prev = int(state.get("speaker_swap", 0))
    state["speaker_swap"] = swap

    if prev != swap:
        for u in state.get("utterances", []):
            if u.get("speaker") == "doctor":
                u["speaker"] = "patient"
            elif u.get("speaker") == "patient":
                u["speaker"] = "doctor"

    _save_state(visit_id, state)
    return {"ok": True, "speaker_swap": swap}


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


def _parse_json_list(raw):
    """Best-effort decode a form/JSON field expected to be a list of strings.

    Returns None when the value is absent/unparseable, so callers can
    distinguish "doctor didn't select anything explicitly" from
    "doctor explicitly selected empty list" (we treat both as 'no override').
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    return None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def end_encounter():
    """Close out a consultation from the /encounter page.

    Finds (or creates) a Patient Encounter linked to the given appointment,
    populates it from the cached AI state, marks the appointment as
    Checked Out, and returns the encounter docname. Called by the
    "End Encounter" button in the encounter topbar.

    Form fields:
        appointment          (required) - Patient Appointment name
        visit_id             (required) - same as appointment for /encounter flow
        selected_tests       (optional JSON array) - doctor-accepted tests
        selected_meds        (optional JSON array) - doctor-accepted meds
        selected_followups   (optional JSON array) - doctor-accepted follow-ups
        doctor_notes         (optional) - free-text observations
    """
    appointment = frappe.form_dict.get("appointment")
    visit_id = frappe.form_dict.get("visit_id") or appointment

    if not appointment:
        frappe.throw(_("appointment is required"))

    # Optional doctor-selected payloads (only override defaults when provided).
    selected_tests = _parse_json_list(frappe.form_dict.get("selected_tests"))
    selected_meds = _parse_json_list(frappe.form_dict.get("selected_meds"))
    selected_followups = _parse_json_list(frappe.form_dict.get("selected_followups"))
    doctor_notes = (frappe.form_dict.get("doctor_notes") or "").strip()

    appt = frappe.db.get_value(
        "Patient Appointment",
        appointment,
        [
            "name", "patient", "practitioner", "appointment_date",
            "appointment_time", "company", "department", "status",
            "appointment_type",
        ],
        as_dict=True,
    )
    if not appt:
        frappe.throw(_("Appointment {0} not found").format(appointment))

    encounter_name = frappe.db.get_value(
        "Patient Encounter",
        {"appointment": appointment, "docstatus": ("<", 2)},
        "name",
    )

    if not encounter_name:
        doc = frappe.new_doc("Patient Encounter")
        doc.patient = appt.patient
        doc.practitioner = appt.practitioner
        doc.appointment = appt.name
        if appt.appointment_type:
            doc.appointment_type = appt.appointment_type
        doc.encounter_date = appt.appointment_date or frappe.utils.today()
        if appt.appointment_time:
            doc.encounter_time = appt.appointment_time
        if appt.company:
            doc.company = appt.company
        if appt.department:
            doc.medical_department = appt.department
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        encounter_name = doc.name

    # Populate AI fields from cached state.
    state = _load_state(visit_id)
    rec = state.get("latest_recommendation", {}) or {}

    doc = frappe.get_doc("Patient Encounter", encounter_name)
    # Backfill mandatory fields that pre-existing encounters may be missing.
    if not doc.get("appointment_type") and appt.appointment_type:
        doc.appointment_type = appt.appointment_type
    doc.ai_chief_complaint = rec.get("chief_complaint", "")
    doc.ai_summary = rec.get("summary", "")
    doc.ai_transcript = state.get("full_transcript_en", "")
    doc.ai_transcript_es = state.get("full_transcript_es", "")
    # Suggested lists: if the doctor explicitly selected items, persist ONLY
    # those; otherwise fall back to the full AI list (back-compat).
    doc.ai_suggested_tests = "\n".join(
        selected_tests if selected_tests is not None else (rec.get("suggested_lab_tests") or [])
    )
    doc.ai_suggested_medications = "\n".join(
        selected_meds if selected_meds is not None else (rec.get("suggested_medications") or [])
    )
    doc.ai_red_flags = "\n".join(rec.get("red_flags") or [])
    doc.ai_followup_questions = "\n".join(
        rec.get("recommended_follow_up_questions") or []
    )
    # New: doctor-accepted follow-ups (subset of ai_followup_questions).
    if selected_followups is not None and hasattr(doc, "ai_selected_followups"):
        doc.ai_selected_followups = "\n".join(selected_followups)
    if doctor_notes:
        doc.ai_doctor_notes = doctor_notes
    doc.ai_urgency = (rec.get("urgency") or "").capitalize()
    doc.ai_recommendation_json = json.dumps(rec) if rec else ""

    # Persist the diarized utterance history + audio archive pointers so the
    # admin session-viewer can replay who-said-what after Redis expires.
    try:
        utts = state.get("utterances") or []
        if hasattr(doc, "ai_utterances_json"):
            doc.ai_utterances_json = json.dumps(utts) if utts else ""
        refs = state.get("audio_refs") or {}
        if hasattr(doc, "ai_audio_refs_json"):
            doc.ai_audio_refs_json = json.dumps(refs) if refs else ""
    except Exception:
        # Non-fatal; persistence of history is best-effort.
        pass

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    # Mark appointment as checked out so it moves to the Completed table.
    if appt.status not in COMPLETED_STATUS_SET:
        frappe.db.set_value(
            "Patient Appointment", appointment, "status", "Checked Out"
        )

    frappe.db.commit()

    _log_event(
        "end_encounter", visit_id=visit_id, appointment=appointment,
        extra={"encounter_name": encounter_name},
    )

    return {
        "ok": True,
        "encounter_name": encounter_name,
        "appointment": appointment,
    }


COMPLETED_STATUS_SET = {"Checked Out", "Closed", "Cancelled", "No Show"}


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

    chat_start = _now_ms()
    try:
        resp = client.chat.completions.create(
            model=RECOMMEND_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"{context}Doctor's message: {message}"},
            ],
            temperature=0.3,
        )
    except Exception as e:
        _log_event(
            "error", visit_id=visit_id, appointment=visit_id,
            duration_ms=_now_ms() - chat_start,
            provider=f"openai:{RECOMMEND_MODEL}",
            error_message=f"chat: {e}",
        )
        raise

    reply = (resp.choices[0].message.content or "").strip()
    _log_event(
        "chat", visit_id=visit_id, appointment=visit_id,
        duration_ms=_now_ms() - chat_start,
        provider=f"openai:{RECOMMEND_MODEL}",
        text_length=len(reply),
    )
    return {"ok": True, "reply": reply}


# ---------------------------------------------------------------------------
# Admin-only audio playback (signed URL)
# ---------------------------------------------------------------------------

@frappe.whitelist(methods=["GET"])
def get_audio_playback_url(appointment: str = None, sequence: str = None):
    """Return a short-lived signed URL for an archived audio chunk.

    System Manager only. Looks up the chunk URI from the Patient Encounter's
    ai_audio_refs_json and signs a 5-minute GET URL using the dedicated
    reader service account (so the hot-path stt credentials are never
    exposed for read access).
    """
    if "System Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw(
            _("Not permitted"), frappe.PermissionError,
        )

    appointment = appointment or frappe.form_dict.get("appointment")
    sequence = sequence or frappe.form_dict.get("sequence")
    if not appointment or sequence in (None, ""):
        frappe.throw(_("appointment and sequence are required"))

    encounter_name = frappe.db.get_value(
        "Patient Encounter",
        {"appointment": appointment, "docstatus": ("<", 2)},
        "name",
    )
    if not encounter_name:
        frappe.throw(_("No Patient Encounter for appointment {0}").format(appointment))

    refs_raw = frappe.db.get_value(
        "Patient Encounter", encounter_name, "ai_audio_refs_json"
    ) or ""
    try:
        refs = json.loads(refs_raw) if refs_raw else {}
    except Exception:
        refs = {}

    gs_uri = refs.get(str(sequence))
    if not gs_uri or not gs_uri.startswith("gs://"):
        frappe.throw(_("No archived audio for sequence {0}").format(sequence))

    # gs://<bucket>/<object path>
    try:
        without_scheme = gs_uri[len("gs://"):]
        bucket_name, _, object_path = without_scheme.partition("/")
    except Exception:
        frappe.throw(_("Invalid archive URI"))

    reader_creds = frappe.conf.get("audio_gcs_reader_credentials")
    if not reader_creds or not os.path.exists(reader_creds):
        frappe.throw(_("Audio reader credentials not configured"))

    try:
        import datetime as _dt
        from google.cloud import storage as _gcs
        from google.oauth2 import service_account as _sa
        creds = _sa.Credentials.from_service_account_file(reader_creds)
        client = _gcs.Client(project=creds.project_id, credentials=creds)
        blob = client.bucket(bucket_name).blob(object_path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=_dt.timedelta(minutes=5),
            method="GET",
        )
    except Exception as e:
        frappe.log_error(
            f"Signed URL generation failed: {e}",
            "medical_agent.get_audio_playback_url",
        )
        frappe.throw(_("Could not generate playback URL"))

    return {"ok": True, "url": url, "expires_in": 300}
