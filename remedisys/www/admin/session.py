"""
/admin/session?a=<appointment> — deep-dive on a single consultation.

Pulls live Redis state (if present) and the Patient Encounter row (if
present) and the Medical Agent Log rows for the visit. Read-only view.
"""

import json

import frappe
from frappe import _

from remedisys.api.admin import load_visit_state
from remedisys.www.admin import guard


no_cache = 1


def get_context(context):
	if not guard(context):
		return context

	appt_id = frappe.form_dict.get("a") or frappe.form_dict.get("appointment")
	context.appointment_id = appt_id
	if not appt_id:
		context.error = "No appointment specified."
		return context

	appt = frappe.db.get_value(
		"Patient Appointment",
		appt_id,
		[
			"name", "patient", "patient_name", "practitioner",
			"appointment_date", "appointment_time", "status",
		],
		as_dict=True,
	) or {}
	practitioner_name = None
	if appt.get("practitioner"):
		practitioner_name = frappe.db.get_value(
			"Healthcare Practitioner", appt["practitioner"], "practitioner_name"
		) or appt["practitioner"]
	context.appointment = appt
	context.practitioner_name = practitioner_name

	# Live Redis state (if still cached)
	state = load_visit_state(appt_id)
	context.has_live_state = bool(state)
	context.live_state = state or {}
	context.utterances = state.get("utterances") if state else []
	context.chunks = state.get("chunks") if state else []
	context.transcript_en = state.get("full_transcript_en", "") if state else ""
	context.transcript_es = state.get("full_transcript_es", "") if state else ""
	context.recommendation = state.get("latest_recommendation", {}) if state else {}

	# Fall back to Patient Encounter
	encounter_name = frappe.db.get_value(
		"Patient Encounter",
		{"appointment": appt_id, "docstatus": ("<", 2)},
		"name",
	)
	context.encounter_name = encounter_name
	context.encounter = None
	if encounter_name:
		enc = frappe.db.get_value(
			"Patient Encounter",
			encounter_name,
			[
				"name", "ai_transcript", "ai_transcript_es", "ai_summary",
				"ai_chief_complaint", "ai_suggested_tests",
				"ai_suggested_medications", "ai_red_flags",
				"ai_followup_questions", "ai_urgency",
				"ai_recommendation_json",
			],
			as_dict=True,
		)
		context.encounter = enc
		# Prefer live state if present; otherwise hydrate transcripts from encounter
		if not context.transcript_en and enc and enc.get("ai_transcript"):
			context.transcript_en = enc["ai_transcript"]
		if not context.transcript_es and enc and enc.get("ai_transcript_es"):
			context.transcript_es = enc["ai_transcript_es"]
		if not context.recommendation and enc and enc.get("ai_recommendation_json"):
			try:
				context.recommendation = json.loads(enc["ai_recommendation_json"])
			except (ValueError, TypeError):
				context.recommendation = {}

	# Pretty-print the recommendation JSON
	try:
		context.recommendation_pretty = json.dumps(
			context.recommendation or {}, indent=2, ensure_ascii=False
		)
	except Exception:
		context.recommendation_pretty = ""

	# Agent logs for this visit
	context.logs = frappe.get_all(
		"Medical Agent Log",
		filters={"visit_id": appt_id},
		fields=[
			"name", "creation", "event_type", "sequence_number",
			"duration_ms", "provider", "speaker_count", "text_length",
			"error_message",
		],
		order_by="creation asc",
		limit=500,
	)

	# TODO: when audio retention ships, expose playback links here.

	context.error = None
	return context
