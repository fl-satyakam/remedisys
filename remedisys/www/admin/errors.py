"""
/admin/errors — recent Error Log entries tagged with medical_agent.
"""

import frappe

from remedisys.api.admin import recent_error_logs
from remedisys.www.admin import guard


no_cache = 1


def get_context(context):
	if not guard(context):
		return context

	try:
		context.rows = recent_error_logs(limit=50)
	except Exception as e:
		frappe.log_error(f"admin errors page failed: {e}", "Remedisys Admin")
		context.rows = []
	return context
