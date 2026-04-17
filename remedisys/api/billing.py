"""
Billing + prescription generation endpoints for the /encounter-summary page.

Both endpoints consume a finalized Patient Encounter and produce (or reuse)
an editable Frappe document, returning a /app/... URL the summary page then
navigates to.

- create_invoice_from_encounter(encounter):
	Builds a prefilled Sales Invoice for the practitioner's OP consulting
	charge. Reuses existing invoice if the encounter already has one.

- create_prescription_from_encounter(encounter):
	Populates the Patient Encounter's drug_prescription / lab_test_prescription
	child tables from the AI-suggested (doctor-accepted) lists, so clicking
	Print on the Encounter produces a proper prescription slip.
"""

import frappe
from frappe import _


APP_URL_ENCOUNTER = "/app/patient-encounter/{name}"
APP_URL_SALES_INVOICE = "/app/sales-invoice/{name}"


def _lines(raw):
	if not raw:
		return []
	return [s.strip() for s in str(raw).splitlines() if s.strip()]


def _require_permission(encounter_doc):
	"""Physicians, practitioners who own the encounter, and Healthcare Admins
	may generate billing/prescription docs. Everyone else gets 403."""
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Remedisys Admin", "Healthcare Administrator", "Physician"}:
		return
	frappe.throw(_("You don't have permission to generate billing for this encounter."), frappe.PermissionError)


def _drug_item_group():
	"""Pick a non-group Item Group suitable for medicines. Prefer an existing
	'Drug' / 'Medicine' group, else fall back to any leaf group."""
	for candidate in ("Drug", "Drugs", "Medicine", "Medicines", "Pharmaceuticals"):
		name = frappe.db.get_value("Item Group", {"item_group_name": candidate, "is_group": 0}, "name")
		if name:
			return name
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"


def _ensure_drug_item(name):
	"""Look up an Item by name for the given medication; create a minimal
	non-stock Item if none exists. Required because Patient Encounter.validate
	enforces drug_code (Link → Item) on every drug_prescription row."""
	clean = (name or "").strip()[:140]
	if not clean:
		return None
	existing = (
		frappe.db.get_value("Item", {"item_name": clean}, "name")
		or frappe.db.get_value("Item", {"item_code": clean}, "name")
	)
	if existing:
		return existing
	code = clean.upper().replace(" ", "-")[:140]
	if frappe.db.exists("Item", code):
		return code
	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = clean
	item.item_group = _drug_item_group()
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.is_purchase_item = 0
	item.flags.ignore_permissions = True
	item.insert(ignore_permissions=True)
	return item.name


def _default_company():
	return (
		frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.db.get_value("Company", {}, "name")
	)


@frappe.whitelist()
def create_invoice_from_encounter(encounter=None):
	"""Create (or reuse) a draft Sales Invoice for the encounter's consultation
	charge. Returns {'ok': True, 'redirect': '/app/sales-invoice/<name>'}.

	We never submit — the doctor/cashier reviews and submits in desk."""
	if not encounter:
		frappe.throw(_("encounter is required"))
	if not frappe.db.exists("Patient Encounter", encounter):
		frappe.throw(_("Encounter {0} not found.").format(encounter))

	enc = frappe.get_doc("Patient Encounter", encounter)
	_require_permission(enc)

	# If a draft invoice already references this encounter, hand it back.
	existing = frappe.db.get_value(
		"Sales Invoice",
		{"ref_practitioner": enc.practitioner, "patient": enc.patient, "docstatus": 0, "remarks": ("like", f"%{enc.name}%")},
		"name",
	)
	if existing:
		return {"ok": True, "reused": True, "invoice": existing, "redirect": APP_URL_SALES_INVOICE.format(name=existing)}

	patient_doc = frappe.get_doc("Patient", enc.patient)
	customer = patient_doc.customer
	if not customer:
		# Auto-create a Customer so the flow doesn't dead-end. Frappe
		# Healthcare normally creates one on first invoice anyway.
		cust = frappe.new_doc("Customer")
		cust.customer_name = patient_doc.patient_name or enc.patient
		cust.customer_group = (
			frappe.db.get_single_value("Selling Settings", "customer_group")
			or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		)
		cust.territory = (
			frappe.db.get_single_value("Selling Settings", "territory")
			or frappe.db.get_value("Territory", {"is_group": 0}, "name")
		)
		cust.flags.ignore_permissions = True
		cust.insert(ignore_permissions=True)
		customer = cust.name
		frappe.db.set_value("Patient", enc.patient, "customer", customer)

	# Practitioner's OP consulting charge + item. Fall back to a generic
	# "Consultation" item if none configured, so the invoice still opens.
	pr = frappe.get_doc("Healthcare Practitioner", enc.practitioner)
	item_code = pr.get("op_consulting_charge_item")
	rate = pr.get("op_consulting_charge") or 0

	if not item_code:
		item_code = frappe.db.get_value("Item", {"item_name": "Consultation"}, "name")
		if not item_code:
			# Last-resort: create a non-stock Service item so the form opens.
			item = frappe.new_doc("Item")
			item.item_code = "CONSULTATION"
			item.item_name = "Consultation"
			item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "Services"
			item.stock_uom = "Nos"
			item.is_stock_item = 0
			item.is_sales_item = 1
			item.flags.ignore_permissions = True
			item.insert(ignore_permissions=True)
			item_code = item.name

	company = enc.company or _default_company()

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.patient = enc.patient
	si.ref_practitioner = enc.practitioner
	si.due_date = frappe.utils.today()
	si.remarks = _("Consultation — Encounter {0} · {1}").format(
		enc.name, pr.practitioner_name or enc.practitioner
	)
	si.append("items", {
		"item_code": item_code,
		"qty": 1,
		"rate": rate,
		"description": si.remarks,
	})
	si.flags.ignore_permissions = True
	si.insert(ignore_permissions=True)

	# Link back from the encounter so we find it next time.
	frappe.db.set_value("Patient Encounter", enc.name, "invoiced", 1)
	frappe.db.commit()

	return {
		"ok": True,
		"invoice": si.name,
		"reused": False,
		"redirect": APP_URL_SALES_INVOICE.format(name=si.name),
	}


@frappe.whitelist()
def create_prescription_from_encounter(encounter=None):
	"""Populate the encounter's drug_prescription + lab_test_prescription child
	tables from the doctor-accepted AI suggestions, then redirect to the
	encounter form for final review + print.

	Existing child rows are preserved — we only append missing items, so this
	is safe to call more than once."""
	if not encounter:
		frappe.throw(_("encounter is required"))
	if not frappe.db.exists("Patient Encounter", encounter):
		frappe.throw(_("Encounter {0} not found.").format(encounter))

	enc = frappe.get_doc("Patient Encounter", encounter)
	_require_permission(enc)

	if enc.docstatus == 1:
		# Submitted encounters are locked — just send the doctor to the form.
		return {
			"ok": True,
			"encounter": enc.name,
			"appended_drugs": 0,
			"appended_tests": 0,
			"redirect": APP_URL_ENCOUNTER.format(name=enc.name),
		}

	meds = _lines(enc.get("ai_suggested_medications"))
	tests = _lines(enc.get("ai_suggested_tests"))

	existing_drug_names = {
		(r.get("drug_name") or "").strip().lower()
		for r in (enc.get("drug_prescription") or [])
	}
	existing_test_names = {
		(r.get("lab_test_name") or "").strip().lower()
		for r in (enc.get("lab_test_prescription") or [])
	}

	# Patient Encounter.validate() requires drug_code (Item link) + dosage_form
	# + period on every drug_prescription row, so populate reasonable defaults
	# the doctor can edit before submitting.
	default_dosage_form = (
		frappe.db.get_value("Dosage Form", {"name": "Tablet"})
		or frappe.db.get_value("Dosage Form", {}, "name")
	)
	default_period = (
		frappe.db.get_value("Prescription Duration", {"name": "5 Day"})
		or frappe.db.get_value("Prescription Duration", {"name": "7 Day"})
		or frappe.db.get_value("Prescription Duration", {}, "name")
	)

	appended_drugs = 0
	for med in meds:
		if med.strip().lower() in existing_drug_names:
			continue
		row = enc.append("drug_prescription", {})
		row.drug_name = med[:140]
		row.drug_code = _ensure_drug_item(med)
		if default_dosage_form:
			row.dosage_form = default_dosage_form
		if default_period:
			row.period = default_period
		appended_drugs += 1

	# Lab test rows require a resolved Lab Test Template OR Observation Template
	# (Patient Encounter.validate enforces this). Creating a Lab Test Template
	# on the fly needs a Medical Department + Item Group which may not be
	# configured, so we only attach tests we can resolve and surface the rest
	# in the return payload for the doctor to add manually.
	appended_tests = 0
	skipped_tests = []
	for t in tests:
		if t.strip().lower() in existing_test_names:
			continue
		template = frappe.db.get_value(
			"Lab Test Template", {"lab_test_name": t}, "name"
		) or frappe.db.get_value(
			"Lab Test Template", {"lab_test_code": t}, "name"
		)
		if not template:
			skipped_tests.append(t)
			continue
		row = enc.append("lab_test_prescription", {})
		row.lab_test_code = template
		row.lab_test_name = t[:140]
		appended_tests += 1

	if appended_drugs or appended_tests:
		enc.flags.ignore_permissions = True
		enc.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"ok": True,
		"encounter": enc.name,
		"appended_drugs": appended_drugs,
		"appended_tests": appended_tests,
		"skipped_tests": skipped_tests,
		"redirect": APP_URL_ENCOUNTER.format(name=enc.name),
	}
