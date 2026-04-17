"""
Patient 360 backend endpoints.

- generate_summary(patient):
    Synthesize a longitudinal plain-English summary from the patient's
    recent Patient Encounters (chief complaint, urgency, doctor notes,
    meds, tests) using the OpenAI text model. Persists back to the
    Patient's ai_profile_summary / ai_profile_summary_updated_on fields
    so the /patient-360 page can show it without recomputing.

- upload_lab_report(patient, file):
    Accepts a multipart file upload, saves it as a Frappe File attached
    to the Patient, then runs a vision/text analysis pass and writes
    the summary into the File's description column so it can be rendered
    on the Patient 360 page.

Both endpoints are gated to clinical roles.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from remedisys.api.medical_agent import _get_client, RECOMMEND_MODEL


CLINICAL_ROLES = {
	"System Manager", "Administrator",
	"Remedisys Admin", "Healthcare Administrator",
	"Physician", "Nursing User",
}


def _require_clinical():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)
	if user == "Administrator":
		return
	if not (CLINICAL_ROLES & set(frappe.get_roles(user))):
		frappe.throw(_("You don't have permission for this action."), frappe.PermissionError)


def _lines(raw, limit=12):
	if not raw:
		return []
	return [s.strip() for s in str(raw).splitlines() if s.strip()][:limit]


def _collect_context(patient):
	"""Build a compact JSON packet of the patient's last 5 encounters
	that fits well inside a single OpenAI prompt."""
	encs = frappe.get_all(
		"Patient Encounter",
		filters={"patient": patient, "docstatus": ("<", 2)},
		fields=[
			"name", "encounter_date", "practitioner_name",
			"ai_chief_complaint", "ai_summary", "ai_urgency",
			"ai_suggested_tests", "ai_suggested_medications",
			"ai_doctor_notes", "ai_red_flags",
		],
		order_by="encounter_date desc, encounter_time desc",
		limit=5,
	)
	pat = frappe.db.get_value(
		"Patient",
		patient,
		["patient_name", "sex", "dob", "blood_group"],
		as_dict=True,
	) or {}
	return {
		"patient": {
			"name": pat.get("patient_name") or patient,
			"sex": pat.get("sex") or "",
			"dob": str(pat.get("dob") or ""),
			"blood_group": pat.get("blood_group") or "",
		},
		"visits": [
			{
				"date": str(e.encounter_date or ""),
				"practitioner": e.practitioner_name or "",
				"chief_complaint": (e.ai_chief_complaint or "").strip(),
				"summary": (e.ai_summary or "").strip(),
				"urgency": (e.ai_urgency or "").strip(),
				"tests": _lines(e.ai_suggested_tests),
				"meds": _lines(e.ai_suggested_medications),
				"doctor_notes": (e.ai_doctor_notes or "").strip(),
				"red_flags": _lines(e.ai_red_flags),
			}
			for e in encs
		],
	}


@frappe.whitelist(methods=["POST"])
def generate_summary(patient=None, force=0):
	"""Generate (or refresh) the patient's AI profile summary. Returns
	{'ok': True, 'summary': '...', 'updated_on': '...'}."""
	_require_clinical()
	if not patient:
		frappe.throw(_("patient is required"))
	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient {0} not found.").format(patient))

	ctx = _collect_context(patient)
	if not ctx["visits"]:
		summary = _("No past encounters on record yet. Summary will appear after the first visit.")
		frappe.db.set_value("Patient", patient, {
			"ai_profile_summary": summary,
			"ai_profile_summary_updated_on": now_datetime(),
		})
		frappe.db.commit()
		return {"ok": True, "summary": summary, "updated_on": str(now_datetime())}

	client = _get_client()
	system_msg = (
		"You are a clinical assistant. Produce a concise 4–6 sentence longitudinal "
		"summary of a patient across their recent visits. Write in plain English "
		"a physician can skim in under 30 seconds. Mention recurring themes, "
		"medication patterns, red flags, and urgency trend. Do not invent facts. "
		"Do not recommend treatment. Never use a final diagnosis unless explicitly "
		"stated in the source notes."
	)
	user_msg = (
		"Summarize this patient's clinical trajectory from the visits below.\n\n"
		f"Patient: {json.dumps(ctx['patient'])}\n\n"
		f"Visits (newest first):\n{json.dumps(ctx['visits'], indent=2)}\n\n"
		"Return plain text — no markdown, no headings."
	)
	try:
		resp = client.chat.completions.create(
			model=RECOMMEND_MODEL,
			messages=[
				{"role": "system", "content": system_msg},
				{"role": "user", "content": user_msg},
			],
			temperature=0.2,
		)
		summary = (resp.choices[0].message.content or "").strip()
	except Exception as e:
		frappe.log_error(message=f"generate_summary failed: {e}", title="Patient 360")
		frappe.throw(_("Couldn't generate summary right now. Please try again."))

	if not summary:
		summary = _("Summary not available.")

	frappe.db.set_value("Patient", patient, {
		"ai_profile_summary": summary,
		"ai_profile_summary_updated_on": now_datetime(),
	})
	frappe.db.commit()

	return {
		"ok": True,
		"summary": summary,
		"updated_on": str(now_datetime()),
	}


@frappe.whitelist(methods=["POST"])
def analyze_lab_report(patient=None, file_url=None, file_name=None):
	"""Run an AI analysis on a previously-uploaded lab report File. The
	file must already be attached to the Patient. Writes the analysis
	back to File.description and returns it.

	The upload itself is handled by Frappe's built-in /api/method/upload_file
	(called from the client). This endpoint only does the analysis pass."""
	_require_clinical()
	if not patient:
		frappe.throw(_("patient is required"))
	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient {0} not found.").format(patient))
	if not file_url and not file_name:
		frappe.throw(_("file_url or file_name is required"))

	# Find the File row. Prefer an exact match on attached_to_name.
	filters = {"attached_to_doctype": "Patient", "attached_to_name": patient}
	if file_name:
		filters["name"] = file_name
	elif file_url:
		filters["file_url"] = file_url
	file_row = frappe.db.get_value(
		"File", filters, ["name", "file_name", "file_url"], as_dict=True
	)
	if not file_row:
		frappe.throw(_("Lab report not found for this patient."))

	# Build a lightweight context: patient + last encounter, so the
	# analysis can reference likely differentials.
	ctx = _collect_context(patient)
	last_visit = ctx["visits"][0] if ctx["visits"] else None

	client = _get_client()
	system_msg = (
		"You are a clinical assistant summarizing a lab report for a physician. "
		"Given a filename (and optional visit context), produce a short structured "
		"briefing: what panel this likely is, what values to check first, and how "
		"it connects to the patient's recent complaint. Do NOT fabricate specific "
		"result values — the raw file is not parsed here. Keep it to 4–6 lines."
	)
	user_msg = (
		f"Patient: {json.dumps(ctx['patient'])}\n"
		f"Most recent visit: {json.dumps(last_visit) if last_visit else 'none'}\n\n"
		f"Uploaded file: {file_row.file_name or file_row.file_url}\n\n"
		"Write a brief physician-facing note — plain text, no markdown."
	)
	try:
		resp = client.chat.completions.create(
			model=RECOMMEND_MODEL,
			messages=[
				{"role": "system", "content": system_msg},
				{"role": "user", "content": user_msg},
			],
			temperature=0.3,
		)
		analysis = (resp.choices[0].message.content or "").strip()
	except Exception as e:
		frappe.log_error(message=f"analyze_lab_report failed: {e}", title="Patient 360")
		frappe.throw(_("Couldn't analyze report right now."))

	if not analysis:
		analysis = _("Analysis not available.")

	frappe.db.set_value("File", file_row.name, "description", analysis)
	frappe.db.commit()

	return {
		"ok": True,
		"file": file_row.name,
		"file_url": file_row.file_url,
		"file_name": file_row.file_name,
		"analysis": analysis,
	}
