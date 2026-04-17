"""
/patient-360?p=<patient> — unified patient dashboard.

Replaces the raw /app/patient desk link from the queue. Shows:
  - Demographics + contact card
  - AI-synthesized longitudinal summary (generated on demand, cached on Patient)
  - Lab report uploader with instant AI analysis
  - Last encounter preview (chief complaint, assessment, transcript snippet)
  - Next scheduled visit
  - Recent prescriptions (rolled up from Patient Encounters)
  - Recent invoices

Authenticated users only. The AI endpoints are separately gated in
remedisys.api.patient_profile.
"""

import json
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import format_datetime, formatdate, get_datetime, getdate, now_datetime


no_cache = 1


COMPLETED_STATUSES = ("Checked Out", "Closed")
UPCOMING_STATUSES = ("Scheduled", "Open", "Confirmed", "Checked In")


def _lines(raw):
	if not raw:
		return []
	return [s.strip() for s in str(raw).splitlines() if s.strip()]


def _safe_json(raw, default):
	if not raw:
		return default
	try:
		v = json.loads(raw)
		return v if v is not None else default
	except (ValueError, TypeError):
		return default


def _initials(label):
	parts = [p for p in (label or "").split() if p]
	if not parts:
		return "?"
	if len(parts) == 1:
		return parts[0][:2].upper()
	return (parts[0][0] + parts[-1][0]).upper()


def _format_date(d):
	if not d:
		return ""
	try:
		return formatdate(d, "d MMM yyyy")
	except Exception:
		return str(d)


def _format_datetime(d, t=None):
	if not d:
		return ""
	try:
		if t is None:
			return format_datetime(d, "d MMM yyyy · h:mm a")
		# date + time columns
		dt = datetime.combine(getdate(d), (get_datetime(str(t)).time() if t else datetime.min.time()))
		return dt.strftime("%d %b %Y · %-I:%M %p")
	except Exception:
		return f"{d} {t or ''}".strip()


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/patient-360"
		raise frappe.Redirect

	patient_id = (
		frappe.form_dict.get("p")
		or frappe.form_dict.get("patient")
		or frappe.form_dict.get("name")
	)
	if not patient_id:
		context.error = _("Missing patient id (?p=<name>).")
		_set_blank(context)
		return context

	if not frappe.db.exists("Patient", patient_id):
		context.error = _("Patient {0} not found.").format(patient_id)
		_set_blank(context)
		return context

	pat = frappe.get_doc("Patient", patient_id)

	# Demographics
	context.error = None
	context.patient = pat.name
	context.patient_name = pat.patient_name or pat.name
	context.patient_initials = _initials(pat.patient_name or pat.name)
	context.patient_sex = pat.sex or ""
	context.patient_dob = _format_date(pat.dob)
	context.patient_age = _compute_age(pat.dob)
	context.patient_blood_group = pat.blood_group or ""
	context.patient_mobile = pat.mobile or ""
	context.patient_email = pat.email or ""
	context.patient_customer = pat.customer or ""
	context.patient_allergies = pat.get("allergies") or ""
	context.patient_medical_history = pat.get("medical_history") or ""

	# Cached AI summary (on Patient custom field ai_profile_summary,
	# written by patient_profile.generate_summary).
	context.ai_summary = pat.get("ai_profile_summary") or ""
	context.ai_summary_updated = _format_date(pat.get("ai_profile_summary_updated_on"))
	context.ai_summary_status = "stale" if _summary_is_stale(pat) else "fresh"

	# Encounters (latest first)
	encs = frappe.get_all(
		"Patient Encounter",
		filters={"patient": pat.name},
		fields=[
			"name", "encounter_date", "encounter_time", "practitioner",
			"practitioner_name", "docstatus", "invoiced",
			"ai_chief_complaint", "ai_summary", "ai_urgency",
			"ai_suggested_medications", "ai_suggested_tests",
			"ai_transcript", "ai_recommendation_json",
		],
		order_by="encounter_date desc, encounter_time desc",
		limit=10,
	)

	last_enc = encs[0] if encs else None
	context.last_encounter = _shape_last_encounter(last_enc)
	context.encounter_count = len(encs)

	# Upcoming appointments
	upcoming = frappe.get_all(
		"Patient Appointment",
		filters={
			"patient": pat.name,
			"status": ("in", UPCOMING_STATUSES),
			"appointment_date": (">=", date.today()),
		},
		fields=[
			"name", "appointment_date", "appointment_time",
			"practitioner", "department", "status",
		],
		order_by="appointment_date asc, appointment_time asc",
		limit=3,
	)
	practitioner_names = {}
	for a in upcoming:
		if a.practitioner and a.practitioner not in practitioner_names:
			practitioner_names[a.practitioner] = frappe.db.get_value(
				"Healthcare Practitioner", a.practitioner, "practitioner_name"
			) or a.practitioner
	context.upcoming_visits = [
		{
			"name": a.name,
			"when": _format_datetime(a.appointment_date, a.appointment_time),
			"practitioner": practitioner_names.get(a.practitioner, a.practitioner or ""),
			"department": a.department or "",
			"status": a.status or "",
		}
		for a in upcoming
	]
	context.next_visit = context.upcoming_visits[0] if context.upcoming_visits else None

	# Recent prescriptions — take child rows from last 3 submitted encounters
	context.recent_prescriptions = _collect_prescriptions(encs[:3])

	# Recent invoices
	invs = frappe.get_all(
		"Sales Invoice",
		filters={"patient": pat.name, "docstatus": ("<", 2)},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "currency"],
		order_by="posting_date desc",
		limit=5,
	)
	context.recent_invoices = [
		{
			"name": i.name,
			"date": _format_date(i.posting_date),
			"total": i.grand_total or 0,
			"outstanding": i.outstanding_amount or 0,
			"status": i.status or "",
			"currency": i.currency or "",
		}
		for i in invs
	]

	# Lab reports already uploaded for this patient (stored as File rows
	# attached to Patient). Newest first.
	context.lab_reports = _collect_lab_reports(pat.name)

	# Timeline — last 10 encounters as compact cards
	context.encounter_timeline = [
		{
			"name": e.name,
			"date": _format_datetime(e.encounter_date, e.encounter_time),
			"practitioner": e.practitioner_name or e.practitioner,
			"chief_complaint": (e.ai_chief_complaint or "").strip(),
			"urgency": (e.ai_urgency or "").strip().lower(),
			"is_submitted": e.docstatus == 1,
			"summary_url": f"/encounter-summary?e={e.name}",
		}
		for e in encs
	]

	return context


# ---------------------------------------------------------------------------

def _set_blank(context):
	context.patient = None
	context.patient_name = ""
	context.patient_initials = "?"
	context.patient_sex = ""
	context.patient_dob = ""
	context.patient_age = ""
	context.patient_blood_group = ""
	context.patient_mobile = ""
	context.patient_email = ""
	context.patient_customer = ""
	context.patient_allergies = ""
	context.patient_medical_history = ""
	context.ai_summary = ""
	context.ai_summary_updated = ""
	context.ai_summary_status = ""
	context.last_encounter = None
	context.encounter_count = 0
	context.upcoming_visits = []
	context.next_visit = None
	context.recent_prescriptions = []
	context.recent_invoices = []
	context.lab_reports = []
	context.encounter_timeline = []


def _compute_age(dob):
	if not dob:
		return ""
	try:
		d = getdate(dob)
	except Exception:
		return ""
	today = date.today()
	years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
	return f"{years} yr" if years >= 1 else ""


def _summary_is_stale(pat):
	updated = pat.get("ai_profile_summary_updated_on")
	if not updated:
		return True
	try:
		return (now_datetime() - get_datetime(updated)) > timedelta(days=7)
	except Exception:
		return True


def _shape_last_encounter(enc):
	if not enc:
		return None
	rec = _safe_json(enc.get("ai_recommendation_json"), {})
	possible = rec.get("possible_assessment") or []
	if isinstance(possible, str):
		possible = _lines(possible)
	transcript = (enc.get("ai_transcript") or "").strip()
	if len(transcript) > 560:
		transcript = transcript[:560].rsplit(" ", 1)[0] + "…"
	return {
		"name": enc.name,
		"when": _format_datetime(enc.encounter_date, enc.encounter_time),
		"practitioner": enc.practitioner_name or enc.practitioner or "",
		"chief_complaint": (enc.ai_chief_complaint or "").strip(),
		"summary": (enc.ai_summary or "").strip(),
		"urgency": (enc.ai_urgency or "").strip().lower(),
		"assessment": possible,
		"tests": _lines(enc.get("ai_suggested_tests")),
		"meds": _lines(enc.get("ai_suggested_medications")),
		"transcript_preview": transcript,
		"summary_url": f"/encounter-summary?e={enc.name}",
		"is_submitted": enc.docstatus == 1,
	}


def _collect_prescriptions(encs):
	items = []
	for e in encs:
		drug_rows = frappe.get_all(
			"Drug Prescription",
			filters={"parent": e.name},
			fields=["drug_name", "dosage", "period", "interval", "dosage_form"],
			order_by="idx asc",
		)
		for r in drug_rows:
			items.append({
				"drug_name": r.drug_name or "",
				"dosage": r.dosage or "",
				"period": r.period or "",
				"interval": r.interval or "",
				"dosage_form": r.dosage_form or "",
				"encounter": e.name,
				"when": _format_date(e.encounter_date),
			})
	return items[:10]


def _collect_lab_reports(patient_name):
	# Match File attached to Patient OR explicitly tagged with ?p=<patient>
	# in the file_name (our uploader uses attached_to_doctype=Patient).
	rows = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Patient",
			"attached_to_name": patient_name,
		},
		fields=["name", "file_name", "file_url", "creation", "file_size", "content_hash"],
		order_by="creation desc",
		limit=10,
	)
	out = []
	for r in rows:
		analysis = frappe.db.get_value(
			"File",
			r.name,
			"description",
		) or ""
		out.append({
			"name": r.name,
			"file_name": r.file_name or "",
			"file_url": r.file_url or "",
			"uploaded": _format_datetime(r.creation),
			"size_kb": round((r.file_size or 0) / 1024, 1) if r.file_size else 0,
			"analysis": analysis,
		})
	return out
