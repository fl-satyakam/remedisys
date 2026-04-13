"""
Remedisys Setup — Creates custom fields on Patient Encounter
for AI Assistant integration.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


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
    ]
}


def setup_custom_fields():
    """Create or update AI custom fields on Patient Encounter."""
    create_custom_fields(AI_CUSTOM_FIELDS, update=True)
    frappe.db.commit()


def after_install():
    setup_custom_fields()


def after_migrate():
    setup_custom_fields()
