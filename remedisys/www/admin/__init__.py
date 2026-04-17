"""
/admin — Remedisys operator portal landing page.

This file lives inside the admin/ package because Python's import system
prefers a package over a same-named sibling .py. Frappe's
`get_module("remedisys.www.admin")` would resolve to this package regardless
of admin.py's contents, so the controller MUST live here.

Gated to System Manager / Remedisys Admin / Administrator. Guests bounce
to /login. Authenticated users without the right role see a 403.
"""

import frappe
from frappe import _

from remedisys.api.admin import dashboard_stats


no_cache = 1


ADMIN_ROLES = {"System Manager", "Remedisys Admin"}


_STATS_DEFAULTS = {
	"chunks_today": 0,
	"avg_transcribe_ms": 0,
	"avg_recommend_ms": 0,
	"errors_24h": 0,
	"total_events_24h": 0,
	"error_rate": 0,
}


def _is_admin(user):
	if user == "Guest":
		return False
	if user == "Administrator":
		return True
	return bool(ADMIN_ROLES & set(frappe.get_roles(user)))


def guard(context):
	"""Shared guard used by every /admin* route. Returns True if allowed."""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/admin"
		raise frappe.Redirect
	if not _is_admin(frappe.session.user):
		context.forbidden = True
		return False
	context.forbidden = False
	return True


def get_context(context):
	context.stats = dict(_STATS_DEFAULTS)
	context.forbidden = False
	context.user = frappe.session.user

	if not guard(context):
		return context

	try:
		context.stats = dashboard_stats()
	except Exception as e:
		try:
			frappe.log_error(
				message=f"admin dashboard_stats failed: {e}",
				title="Remedisys Admin",
			)
		except Exception:
			pass
	return context
