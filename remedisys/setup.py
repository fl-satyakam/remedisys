"""
Remedisys Setup — Bootstraps custom fields, default Physician user,
and Healthcare Practitioner linkage on install / migrate.

Idempotent. Every helper below is safe to run repeatedly.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from remedisys.setup_cleanup import hide_unused_workspaces


DEFAULT_DOCTOR_EMAIL = "saty@remedisys.local"
DEFAULT_DOCTOR_FIRST_NAME = "Saty"
DEFAULT_DOCTOR_LAST_NAME = "Singhal"
DEFAULT_DOCTOR_ROLES = ("Physician", "Healthcare Administrator")


AI_CUSTOM_FIELDS = {
    "Patient Encounter": [
        {
            "fieldname": "ai_assistant_section",
            "label": "AI Assistant",
            "fieldtype": "Section Break",
            "insert_after": "encounter_comment",
            "collapsible": 1,
        },
        {
            "fieldname": "ai_chief_complaint",
            "label": "Chief Complaint (AI)",
            "fieldtype": "Small Text",
            "insert_after": "ai_assistant_section",
            "read_only": 1,
            "description": "Auto-captured from patient conversation",
        },
        {
            "fieldname": "ai_summary",
            "label": "AI Summary",
            "fieldtype": "Text",
            "insert_after": "ai_chief_complaint",
            "read_only": 1,
            "description": "AI-generated visit summary for clinician review",
        },
        {
            "fieldname": "ai_col_break",
            "fieldtype": "Column Break",
            "insert_after": "ai_summary",
        },
        {
            "fieldname": "ai_transcript",
            "label": "Conversation Transcript",
            "fieldtype": "Text",
            "insert_after": "ai_col_break",
            "read_only": 1,
            "description": "Raw transcription of the patient-doctor conversation",
        },
        {
            "fieldname": "ai_transcript_es",
            "label": "Spanish Translation",
            "fieldtype": "Text",
            "insert_after": "ai_transcript",
            "read_only": 1,
        },
        {
            "fieldname": "ai_recommendations_section",
            "label": "AI Recommendations",
            "fieldtype": "Section Break",
            "insert_after": "ai_transcript_es",
            "collapsible": 1,
        },
        {
            "fieldname": "ai_suggested_tests",
            "label": "Suggested Lab Tests",
            "fieldtype": "Small Text",
            "insert_after": "ai_recommendations_section",
            "read_only": 1,
            "description": "AI-suggested investigations",
        },
        {
            "fieldname": "ai_suggested_medications",
            "label": "Suggested Medications",
            "fieldtype": "Small Text",
            "insert_after": "ai_suggested_tests",
            "read_only": 1,
            "description": "AI-suggested medications for clinician review",
        },
        {
            "fieldname": "ai_rec_col_break",
            "fieldtype": "Column Break",
            "insert_after": "ai_suggested_medications",
        },
        {
            "fieldname": "ai_red_flags",
            "label": "Red Flags",
            "fieldtype": "Small Text",
            "insert_after": "ai_rec_col_break",
            "read_only": 1,
            "description": "Urgent clinical alerts from AI analysis",
        },
        {
            "fieldname": "ai_followup_questions",
            "label": "Suggested Follow-up Questions",
            "fieldtype": "Small Text",
            "insert_after": "ai_red_flags",
            "read_only": 1,
        },
        {
            "fieldname": "ai_selected_followups",
            "label": "Doctor-Selected Follow-ups",
            "fieldtype": "Small Text",
            "insert_after": "ai_followup_questions",
            "read_only": 1,
            "description": "Follow-up questions the doctor accepted during the visit",
        },
        {
            "fieldname": "ai_urgency",
            "label": "AI Urgency Level",
            "fieldtype": "Select",
            "options": "\nLow\nModerate\nHigh\nEmergent",
            "insert_after": "ai_followup_questions",
            "read_only": 1,
        },
        {
            "fieldname": "ai_doctor_notes",
            "label": "Doctor's Notes",
            "fieldtype": "Text",
            "insert_after": "ai_urgency",
            "description": "Doctor's own observations and input",
        },
        {
            "fieldname": "ai_recommendation_json",
            "label": "AI Recommendation JSON",
            "fieldtype": "Long Text",
            "insert_after": "ai_doctor_notes",
            "hidden": 1,
            "read_only": 1,
            "description": "Stores full AI recommendation for panel reload",
        },
        {
            "fieldname": "ai_utterances_json",
            "label": "AI Utterances JSON",
            "fieldtype": "Long Text",
            "insert_after": "ai_recommendation_json",
            "hidden": 1,
            "read_only": 1,
            "description": "Persisted diarized utterance history for admin session-viewer",
        },
        {
            "fieldname": "ai_audio_refs_json",
            "label": "AI Audio Refs JSON",
            "fieldtype": "Long Text",
            "insert_after": "ai_utterances_json",
            "hidden": 1,
            "read_only": 1,
            "description": "Map of sequence_number -> gs:// URI for archived audio chunks",
        },
    ],
    "Patient": [
        {
            "fieldname": "ai_profile_section",
            "label": "AI Longitudinal Profile",
            "fieldtype": "Section Break",
            "insert_after": "customer",
            "collapsible": 1,
        },
        {
            "fieldname": "ai_profile_summary",
            "label": "AI Profile Summary",
            "fieldtype": "Text",
            "insert_after": "ai_profile_section",
            "read_only": 1,
            "description": "Synthesized across recent encounters by the /patient-360 page.",
        },
        {
            "fieldname": "ai_profile_summary_updated_on",
            "label": "AI Summary Updated On",
            "fieldtype": "Datetime",
            "insert_after": "ai_profile_summary",
            "read_only": 1,
        },
    ],
}


def setup_custom_fields():
    """Create or update AI custom fields on Patient Encounter."""
    create_custom_fields(AI_CUSTOM_FIELDS, update=True)
    frappe.db.commit()


def ensure_doctor_user() -> str:
    """Create the default Physician user and link it to a Healthcare Practitioner.

    Returns the user's email. Idempotent.
    """
    email = DEFAULT_DOCTOR_EMAIL

    if not frappe.db.exists("User", email):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": DEFAULT_DOCTOR_FIRST_NAME,
                "last_name": DEFAULT_DOCTOR_LAST_NAME,
                "send_welcome_email": 0,
                "enabled": 1,
                "user_type": "System User",
                "roles": [{"role": r} for r in DEFAULT_DOCTOR_ROLES],
            }
        )
        user.insert(ignore_permissions=True)
    else:
        user = frappe.get_doc("User", email)
        existing_roles = {r.role for r in user.get("roles", [])}
        added = False
        for role in DEFAULT_DOCTOR_ROLES:
            if role not in existing_roles:
                user.append("roles", {"role": role})
                added = True
        if added:
            user.save(ignore_permissions=True)

    _link_practitioner_to_user(email)
    frappe.db.commit()
    return email


def _link_practitioner_to_user(user_email: str) -> None:
    """Attach an unlinked Healthcare Practitioner to the given user.

    If any practitioner is already linked to this user, nothing happens.
    Else we bind the first unlinked practitioner. If none exist, one is created.
    """
    already_linked = frappe.db.get_value(
        "Healthcare Practitioner", {"user_id": user_email}, "name"
    )
    if already_linked:
        return

    unlinked = frappe.db.get_value(
        "Healthcare Practitioner",
        {"user_id": ["in", ("", None)]},
        "name",
    )
    if unlinked:
        frappe.db.set_value("Healthcare Practitioner", unlinked, "user_id", user_email)
        return

    user = frappe.get_doc("User", user_email)
    practitioner = frappe.get_doc(
        {
            "doctype": "Healthcare Practitioner",
            "first_name": user.first_name,
            "last_name": user.last_name or "",
            "user_id": user_email,
            "status": "Active",
        }
    )
    practitioner.insert(ignore_permissions=True)


def after_install():
    setup_custom_fields()
    ensure_doctor_user()
    hide_unused_workspaces()


def after_migrate():
    setup_custom_fields()
    ensure_doctor_user()
    hide_unused_workspaces()
