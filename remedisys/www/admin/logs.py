"""
/admin/logs — paginated table of Medical Agent Log rows.
"""

import frappe

from remedisys.api.admin import list_agent_logs
from remedisys.www.admin import guard


no_cache = 1


EVENT_TYPES = ["transcribe", "translate", "recommend", "chat", "end_encounter", "error"]


def get_context(context):
	if not guard(context):
		return context

	event_type = frappe.form_dict.get("event_type") or ""
	visit_id = frappe.form_dict.get("visit_id") or ""
	from_date = frappe.form_dict.get("from_date") or ""
	to_date = frappe.form_dict.get("to_date") or ""
	errors_only = frappe.form_dict.get("errors_only") in ("1", "true", "on")
	try:
		page = max(int(frappe.form_dict.get("page") or 1), 1)
	except (TypeError, ValueError):
		page = 1

	page_length = 50
	start = (page - 1) * page_length

	filters = {
		"event_type": event_type,
		"visit_id": visit_id,
		"from_date": from_date,
		"to_date": to_date,
		"errors_only": errors_only,
	}

	try:
		data = list_agent_logs(filters=filters, start=start, page_length=page_length)
	except Exception as e:
		frappe.log_error(f"admin logs failed: {e}", "Remedisys Admin")
		data = {"rows": [], "total": 0, "start": 0, "page_length": page_length}

	context.rows = data["rows"]
	context.total = data["total"]
	context.page = page
	context.page_length = page_length
	context.total_pages = max(1, (data["total"] + page_length - 1) // page_length)
	context.filters = {
		"event_type": event_type,
		"visit_id": visit_id,
		"from_date": from_date,
		"to_date": to_date,
		"errors_only": errors_only,
	}
	context.event_types = EVENT_TYPES
	return context
