"""
/encounter — doctor's live consultation screen.

Linked by Patient Appointment. Accepts `?a=<appointment_id>` (fall back to
`frappe.form_dict`). Loads patient + practitioner context, resolves the
encounter number (count of prior completed visits + 1), and renders a
full-canvas page with a left cumulative-cards column and a right AI
sidebar.

Authenticated Physician / Nursing User only. Guests bounce to /login.
"""

from datetime import date, datetime

import frappe
from frappe import _

from remedisys.api.medical_agent import _get_ai_module_config


no_cache = 1


PENDING_STATUSES = ("Scheduled", "Open", "Confirmed", "Checked In")
COMPLETED_STATUSES = ("Checked Out", "Closed")


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/queue"
		raise frappe.Redirect

	appt_id = frappe.form_dict.get("a") or frappe.form_dict.get("appointment")
	if not appt_id:
		context.error = "No appointment specified."
		return context

	appt = frappe.db.get_value(
		"Patient Appointment",
		appt_id,
		[
			"name", "patient", "patient_name", "patient_age", "patient_sex",
			"practitioner", "appointment_date", "appointment_time",
			"status", "notes", "appointment_based_on_check_in",
			"department",
		],
		as_dict=True,
	)
	if not appt:
		context.error = f"Appointment {appt_id} not found."
		return context

	practitioner = frappe.db.get_value(
		"Healthcare Practitioner",
		{"user_id": frappe.session.user, "status": "Active"},
		"name",
	)
	if practitioner and appt.practitioner != practitioner:
		context.error = "This appointment belongs to another practitioner."
		return context

	prior_completed = frappe.db.count(
		"Patient Appointment",
		filters={
			"patient": appt.patient,
			"practitioner": appt.practitioner,
			"name": ("!=", appt.name),
			"status": ("in", COMPLETED_STATUSES),
		},
	)
	context.is_new_patient = prior_completed == 0
	context.encounter_number = prior_completed + 1

	last_visit = None
	if prior_completed:
		last = frappe.get_all(
			"Patient Appointment",
			filters={
				"patient": appt.patient,
				"practitioner": appt.practitioner,
				"name": ("!=", appt.name),
				"status": ("in", COMPLETED_STATUSES),
			},
			fields=["appointment_date"],
			order_by="appointment_date desc",
			limit=1,
		)
		if last:
			last_visit = last[0].appointment_date.strftime("%b %d, %Y")
	context.last_visit = last_visit

	existing_encounter = frappe.db.get_value(
		"Patient Encounter",
		{"appointment": appt.name, "docstatus": ("<", 2)},
		"name",
	)
	context.existing_encounter = existing_encounter

	practitioner_name = frappe.db.get_value(
		"Healthcare Practitioner",
		appt.practitioner,
		"practitioner_name",
	) or appt.practitioner

	context.error = None
	context.appointment = appt
	context.practitioner_name = practitioner_name
	context.patient_label = appt.patient_name or appt.patient
	context.patient_id = appt.patient
	context.patient_age = appt.patient_age or ""
	context.patient_sex = appt.patient_sex or ""
	context.visit_id = appt.name
	context.chief_complaint_hint = appt.notes or ""
	context.is_walkin = bool(appt.appointment_based_on_check_in)

	# Configurable AI modules for the left-column cards. Safe on fresh install —
	# _get_ai_module_config falls back to hardcoded defaults if the DocType
	# hasn't been migrated yet.
	try:
		cfg = _get_ai_module_config()
		context.ai_modules = cfg.get("modules") or []
	except Exception:
		context.ai_modules = []

	return context
