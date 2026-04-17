"""
/queue — doctor's daily patient list.

Two tables: Pending (not yet seen today) and Completed (done today).
Date defaults to today, arrows + picker navigate.

Page is a plain website route so there's no desk sidebar / navbar clutter.
Authenticated Physicians only. Guests get bounced to /login.
"""

from datetime import date, datetime, timedelta

import frappe
from frappe import _


no_cache = 1  # always fresh — status changes multiple times per day


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/queue"
		raise frappe.Redirect

	selected = _parse_date(frappe.form_dict.get("d"))
	practitioner = _resolve_practitioner(frappe.session.user)

	if not practitioner:
		context.no_practitioner = True
		context.selected_date = selected
		context.selected_date_iso = selected.isoformat()
		context.selected_date_human = selected.strftime("%a, %b %d %Y")
		context.prev_date_iso = (selected - timedelta(days=1)).isoformat()
		context.next_date_iso = (selected + timedelta(days=1)).isoformat()
		context.is_today = selected == date.today()
		context.pending = []
		context.completed = []
		return context

	rows = _fetch_appointments(practitioner, selected)
	pending, completed = [], []
	for r in rows:
		_enrich(r, practitioner)
		(completed if r["is_completed"] else pending).append(r)

	context.no_practitioner = False
	context.practitioner_name = frappe.db.get_value(
		"Healthcare Practitioner", practitioner, "practitioner_name"
	) or practitioner
	context.selected_date = selected
	context.selected_date_iso = selected.isoformat()
	context.selected_date_human = selected.strftime("%a, %b %d %Y")
	context.prev_date_iso = (selected - timedelta(days=1)).isoformat()
	context.next_date_iso = (selected + timedelta(days=1)).isoformat()
	context.is_today = selected == date.today()
	context.pending = pending
	context.completed = completed
	return context


PENDING_STATUSES = ("Scheduled", "Open", "Confirmed", "Checked In")
COMPLETED_STATUSES = ("Checked Out", "Closed")


def _format_time(value):
	"""MariaDB TIME comes back as datetime.timedelta in Frappe v16; older
	rows may have time/datetime. Format as '6:05 AM' for all shapes."""
	if value is None:
		return ""
	if isinstance(value, timedelta):
		secs = int(value.total_seconds()) % 86400
		h, rem = divmod(secs, 3600)
		m = rem // 60
		suffix = "AM" if h < 12 else "PM"
		hour12 = h % 12 or 12
		return f"{hour12}:{m:02d} {suffix}"
	try:
		return value.strftime("%I:%M %p").lstrip("0")
	except AttributeError:
		return str(value)


def _parse_date(value):
	if not value:
		return date.today()
	try:
		return datetime.strptime(value, "%Y-%m-%d").date()
	except (TypeError, ValueError):
		return date.today()


def _resolve_practitioner(user):
	return frappe.db.get_value(
		"Healthcare Practitioner",
		{"user_id": user, "status": "Active"},
		"name",
	)


def _fetch_appointments(practitioner, selected):
	return frappe.get_all(
		"Patient Appointment",
		filters={
			"practitioner": practitioner,
			"appointment_date": selected,
			"status": ("not in", ("Cancelled", "No Show")),
		},
		fields=[
			"name",
			"patient",
			"patient_name",
			"patient_age",
			"patient_sex",
			"appointment_time",
			"appointment_datetime",
			"status",
			"notes",
			"appointment_based_on_check_in",
			"ref_sales_invoice",
		],
		order_by="appointment_time asc",
	)


def _enrich(row, practitioner):
	row["is_completed"] = row["status"] in COMPLETED_STATUSES
	row["walk_in"] = bool(row.get("appointment_based_on_check_in"))
	row["time_label"] = _format_time(row.get("appointment_time"))

	prior = frappe.db.count(
		"Patient Appointment",
		filters={
			"patient": row["patient"],
			"practitioner": practitioner,
			"name": ("!=", row["name"]),
			"status": ("in", COMPLETED_STATUSES),
		},
	)
	row["is_new"] = prior == 0
	row["last_visit"] = None
	if prior:
		last = frappe.get_all(
			"Patient Appointment",
			filters={
				"patient": row["patient"],
				"practitioner": practitioner,
				"name": ("!=", row["name"]),
				"status": ("in", COMPLETED_STATUSES),
			},
			fields=["appointment_date"],
			order_by="appointment_date desc",
			limit=1,
		)
		if last:
			row["last_visit"] = last[0].appointment_date.strftime("%b %d, %Y")

	row["encounter"] = frappe.db.get_value(
		"Patient Encounter",
		{"appointment": row["name"], "docstatus": ("<", 2)},
		"name",
	)

	if row["is_completed"]:
		upcoming = frappe.get_all(
			"Patient Appointment",
			filters={
				"patient": row["patient"],
				"practitioner": practitioner,
				"appointment_date": (">", row.get("appointment_datetime") or datetime.now()),
				"status": ("in", ("Scheduled", "Open", "Confirmed")),
			},
			fields=["appointment_date"],
			order_by="appointment_date asc",
			limit=1,
		)
		row["next_visit"] = (
			upcoming[0].appointment_date.strftime("%b %d, %Y") if upcoming else None
		)
	else:
		row["next_visit"] = None
