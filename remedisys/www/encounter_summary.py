"""
/encounter-summary?e=<encounter_name> — post-session wrap-up page.

Shown after the doctor clicks "End Encounter" on /encounter. Displays:
  - Patient + visit header
  - AI chief complaint + summary + urgency
  - Bilingual transcript (English + Spanish if captured)
  - Doctor-selected lab tests, medications, follow-ups
  - Red flags
  - Doctor's free-text notes
  - Two action buttons: Generate Invoice + Generate Prescription, which
    call remedisys.api.billing.* and redirect to editable Frappe forms.

Authenticated Physicians / Healthcare Admins only.
"""

import json

import frappe
from frappe import _


no_cache = 1


def _lines(raw):
	"""Split a \\n-joined text field into a list, trimming blanks."""
	if not raw:
		return []
	return [s.strip() for s in str(raw).splitlines() if s.strip()]


def _parse_json(raw, default):
	if not raw:
		return default
	try:
		v = json.loads(raw)
		return v if v is not None else default
	except (ValueError, TypeError):
		return default


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/encounter-summary"
		raise frappe.Redirect

	name = frappe.form_dict.get("e")
	if not name:
		context.error = _("Missing encounter id (?e=<name>).")
		return context

	if not frappe.db.exists("Patient Encounter", name):
		context.error = _("Encounter {0} not found.").format(name)
		return context

	enc = frappe.get_doc("Patient Encounter", name)

	# Patient snapshot
	patient_name = enc.patient_name or enc.patient
	patient_age = enc.patient_age or ""
	patient_sex = enc.patient_sex or ""

	# AI fields (all custom, added by the live encounter flow)
	chief_complaint = enc.get("ai_chief_complaint") or ""
	ai_summary = enc.get("ai_summary") or ""
	urgency = (enc.get("ai_urgency") or "").strip()
	transcript_en = enc.get("ai_transcript") or ""
	transcript_es = enc.get("ai_transcript_es") or ""
	doctor_notes = enc.get("ai_doctor_notes") or ""

	selected_tests = _lines(enc.get("ai_suggested_tests"))
	selected_meds = _lines(enc.get("ai_suggested_medications"))
	selected_followups = _lines(enc.get("ai_selected_followups"))
	all_followups = _lines(enc.get("ai_followup_questions"))
	red_flags = _lines(enc.get("ai_red_flags"))

	utterances = _parse_json(enc.get("ai_utterances_json"), [])

	# Full AI recommendation payload (may contain assessment, extra keys)
	rec = _parse_json(enc.get("ai_recommendation_json"), {})
	possible_assessment = rec.get("possible_assessment") or []
	if isinstance(possible_assessment, str):
		possible_assessment = _lines(possible_assessment)

	# Encounter meta
	encounter_date = enc.encounter_date
	encounter_time = enc.encounter_time
	practitioner_name = enc.practitioner_name or enc.practitioner or ""

	# Link back to the live encounter page only if appointment is still there.
	appointment = enc.appointment
	is_submitted = enc.docstatus == 1
	is_invoiced = bool(enc.get("invoiced"))

	context.encounter_name = name
	context.appointment = appointment or ""
	context.patient = enc.patient
	context.patient_name = patient_name
	context.patient_age = str(patient_age) if patient_age else ""
	context.patient_sex = patient_sex
	context.practitioner_name = practitioner_name
	context.encounter_date = encounter_date
	context.encounter_time = encounter_time
	context.is_submitted = bool(is_submitted)
	context.is_invoiced = bool(is_invoiced)

	context.chief_complaint = chief_complaint
	context.ai_summary = ai_summary
	context.urgency = urgency
	context.urgency_class = urgency.lower() if urgency else ""
	context.transcript_en = transcript_en
	context.transcript_es = transcript_es
	context.doctor_notes = doctor_notes
	context.selected_tests = selected_tests
	context.selected_meds = selected_meds
	context.selected_followups = selected_followups
	context.all_followups = all_followups
	context.red_flags = red_flags
	context.possible_assessment = possible_assessment
	context.utterances = utterances

	context.error = None
	return context
