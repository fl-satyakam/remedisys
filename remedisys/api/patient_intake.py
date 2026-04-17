"""
Patient intake endpoints for the /queue page's "Add Patient" modal.

Two flows:
- Existing patient  -> search_patients(q) -> add_patient(mode="old", patient=...)
- New patient       -> add_patient(mode="new", first_name=..., age=..., ...)

Both flows end with a Patient Appointment for the caller's practitioner on
the requested date, marked as a walk-in / checked-in so it shows up in the
Pending table immediately.
"""

from datetime import datetime

import frappe
from frappe import _

_WALKIN_APPT_TYPE = "Walk-in"


def _ensure_walkin_type():
	"""Idempotently return a default Appointment Type for walk-in visits.
	Healthcare requires a non-null appointment_type on every Patient Appointment."""
	if frappe.db.exists("Appointment Type", _WALKIN_APPT_TYPE):
		return _WALKIN_APPT_TYPE
	doc = frappe.new_doc("Appointment Type")
	doc.appointment_type = _WALKIN_APPT_TYPE
	doc.default_duration = 15
	doc.color = "#2563eb"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def search_patients(q=None):
	"""Fuzzy-search existing Patient records by name, patient id, or mobile.
	Returns up to 10 matches. Used by the Add Patient modal."""
	if not q:
		return []
	q = (q or "").strip()
	if len(q) < 2:
		return []

	like = f"%{q}%"
	rows = frappe.db.sql(
		"""
		SELECT name, patient_name, sex, dob, mobile
		FROM `tabPatient`
		WHERE patient_name LIKE %(q)s
		   OR name LIKE %(q)s
		   OR mobile LIKE %(q)s
		ORDER BY modified DESC
		LIMIT 10
		""",
		{"q": like},
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def add_patient(
	mode,
	date_iso=None,
	patient=None,
	first_name=None,
	last_name=None,
	age=None,
	sex=None,
	mobile=None,
	complaint=None,
):
	"""Create a Patient Appointment for an existing or new Patient.

	mode="old": `patient` must be an existing Patient.name.
	mode="new": creates a Patient from first_name/age/sex/mobile first.

	The appointment is always walk-in / Checked In on `date_iso` (default
	today), at the current time, so it lands in /queue's Pending table.
	"""
	practitioner = frappe.db.get_value(
		"Healthcare Practitioner",
		{"user_id": frappe.session.user, "status": "Active"},
		["name", "department"],
		as_dict=True,
	)
	if not practitioner:
		frappe.throw(_("No active Healthcare Practitioner linked to this user."))

	appt_date = (
		datetime.strptime(date_iso, "%Y-%m-%d").date()
		if date_iso
		else frappe.utils.getdate(frappe.utils.today())
	)

	if mode == "old":
		if not patient:
			frappe.throw(_("Select an existing patient."))
		if not frappe.db.exists("Patient", patient):
			frappe.throw(_("Patient {0} not found.").format(patient))
		patient_label = frappe.db.get_value("Patient", patient, "patient_name") or patient
	elif mode == "new":
		if not first_name:
			frappe.throw(_("First name is required for a new patient."))
		patient_doc = frappe.new_doc("Patient")
		patient_doc.first_name = first_name.strip()
		if last_name:
			patient_doc.last_name = last_name.strip()
		patient_doc.sex = sex or "Male"
		if age:
			try:
				years = int(age)
				patient_doc.dob = frappe.utils.add_years(
					frappe.utils.today(), -years
				)
			except (TypeError, ValueError):
				pass
		if mobile:
			patient_doc.mobile = mobile.strip()
		patient_doc.flags.ignore_permissions = True
		patient_doc.insert(ignore_permissions=True)
		patient = patient_doc.name
		patient_label = (
			f"{first_name} {last_name}".strip() if last_name else first_name
		)
	else:
		frappe.throw(_("Invalid mode. Use 'old' or 'new'."))

	now_time = datetime.now().time().replace(microsecond=0)

	appt = frappe.new_doc("Patient Appointment")
	appt.patient = patient
	appt.practitioner = practitioner["name"]
	appt.department = practitioner.get("department")
	appt.appointment_type = _ensure_walkin_type()
	appt.appointment_date = appt_date
	appt.appointment_time = now_time
	appt.duration = 15
	appt.company = frappe.db.get_single_value(
		"Global Defaults", "default_company"
	) or frappe.db.get_value("Company", {}, "name")
	appt.status = "Checked In"
	appt.notes = (complaint or "").strip()
	appt.appointment_based_on_check_in = 1
	appt.appointment_for = "Practitioner"
	appt.flags.ignore_permissions = True
	appt.flags.ignore_validate = True
	appt.insert(ignore_permissions=True)

	frappe.db.commit()

	return {
		"patient": patient,
		"patient_name": patient_label,
		"appointment": appt.name,
	}
