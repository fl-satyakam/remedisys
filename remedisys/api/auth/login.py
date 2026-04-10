import frappe
from frappe import _
from remedisys.api.auth.utils import error_response, get_user_data, login_user, success_response, unexpected_error


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(usr: str | None = None, pwd: str | None = None):
    """Authenticate a user and create a session."""
    usr = usr or frappe.form_dict.get("usr")
    pwd = pwd or frappe.form_dict.get("pwd")

    if not usr or not pwd:
        return error_response(_("usr and pwd are required"), status_code=400)

    frappe.local.form_dict["usr"] = usr
    frappe.local.form_dict["pwd"] = pwd

    try:
        sid = login_user(usr, pwd)
    except frappe.AuthenticationError:
        return error_response(_("Invalid login credentials"), status_code=401)
    except Exception:
        return unexpected_error("RemediSys Auth Login")

    return success_response(
        _("Logged in successfully"),
        # sid=sid,
        user=get_user_data(frappe.session.user),
    )


@frappe.whitelist(methods=["POST"])
def logout():
    """Log out the current session."""
    if frappe.session.user == "Guest":
        return success_response(_("Already logged out"))

    try:
        frappe.local.login_manager.logout()
        frappe.db.commit()
    except Exception:
        return unexpected_error("RemediSys Auth Logout")

    return success_response(_("Logged out successfully"))
