"""
/admin/sessions — Live + completed consultation sessions.
"""

from datetime import timedelta

import frappe
from frappe import _

from remedisys.api.admin import live_visit_keys, load_visit_state
from remedisys.www.admin import guard


no_cache = 1


def get_context(context):
	if not guard(context):
		return context

	live_rows = []
	for visit_id in live_visit_keys():
		state = load_visit_state(visit_id)
		if not state:
			continue
		appt = frappe.db.get_value(
			"Patient Appointment",
			visit_id,
			["name", "patient_name", "practitioner", "appointment_date", "appointment_time", "status"],
			as_dict=True,
		) or {}
		practitioner_name = None
		if appt.get("practitioner"):
			practitioner_name = frappe.db.get_value(
				"Healthcare Practitioner", appt["practitioner"], "practitioner_name"
			) or appt["practitioner"]
		live_rows.append({
			"visit_id": visit_id,
			"appointment": appt.get("name") or visit_id,
			"patient_name": appt.get("patient_name") or "(unknown)",
			"practitioner": practitioner_name or "(unknown)",
			"appointment_date": appt.get("appointment_date"),
			"appointment_time": appt.get("appointment_time"),
			"status": "Live",
			"chunk_count": len(state.get("chunks") or []),
			"utterance_count": len(state.get("utterances") or []),
		})
	live_rows.sort(key=lambda r: (r.get("appointment_date") or "", r.get("appointment_time") or ""), reverse=True)

	completed_rows = []
	recent_encounters = frappe.get_all(
		"Patient Encounter",
		fields=[
			"name", "patient", "appointment", "practitioner",
			"encounter_date", "encounter_time", "modified",
		],
		order_by="modified desc",
		limit=100,
	)
	for enc in recent_encounters:
		patient_name = None
		if enc.get("patient"):
			patient_name = frappe.db.get_value("Patient", enc["patient"], "patient_name") or enc["patient"]
		practitioner_name = None
		if enc.get("practitioner"):
			practitioner_name = frappe.db.get_value(
				"Healthcare Practitioner", enc["practitioner"], "practitioner_name"
			) or enc["practitioner"]
		completed_rows.append({
			"encounter_name": enc["name"],
			"appointment": enc.get("appointment"),
			"visit_id": enc.get("appointment"),
			"patient_name": patient_name or "(unknown)",
			"practitioner": practitioner_name or "(unknown)",
			"encounter_date": enc.get("encounter_date"),
			"encounter_time": enc.get("encounter_time"),
			"modified": enc.get("modified"),
			"status": "Completed",
		})

	context.live_rows = live_rows
	context.completed_rows = completed_rows
	return context
