"""
Session hooks for Remedisys.

Role-based post-login landing.

Clinicians land on `/queue` — a minimal custom web page showing today's
pending + completed patients. Lives at `remedisys/www/queue.py`.

Wiring:
    frappe/auth.py:login() -> make_session() -> on_session_creation trigger
    frappe/auth.py:login() -> set_user_info() -> get_home_page()

`set_user_info` runs AFTER the hook and overwrites `response["home_page"]`
via `get_home_page()`. That helper returns `frappe.local.flags.home_page`
early when set, so the flag is the durable hook point — we set both the
flag and the response for belt-and-suspenders.
"""

import frappe


PHYSICIAN_ROLE = "Physician"
NURSE_ROLE = "Nursing User"

# role -> post-login landing URL.
ROLE_LANDING = {
	PHYSICIAN_ROLE: "/queue",
	NURSE_ROLE: "/queue",
}


def on_session_creation(login_manager):
	user = login_manager.user
	if user in ("Administrator", "Guest"):
		return

	roles = set(frappe.get_roles(user))
	landing = None
	for role, url in ROLE_LANDING.items():
		if role in roles:
			landing = url
			break

	if not landing:
		return

	# See module docstring for why we set both.
	frappe.local.flags.home_page = landing
	frappe.local.response["home_page"] = landing
