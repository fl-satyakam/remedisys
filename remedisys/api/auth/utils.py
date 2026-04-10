import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.twofactor import authenticate_for_2factor, confirm_otp_token, should_run_2fa


def build_response(status: str, message: str, status_code: int = 200, **data) -> dict:
    frappe.local.response["http_status_code"] = status_code
    response = {
        "status": status,
        "message": message,
    }
    response.update(data)
    return response


def success_response(message: str, status_code: int = 200, **data) -> dict:
    return build_response("sucess", message, status_code=status_code, **data)


def error_response(message: str, status_code: int = 400, **data) -> dict:
    return build_response("error", message, status_code=status_code, **data)
    

def get_user_data(user_id: str | None = None) -> dict:
    user_id = user_id or frappe.session.user
    if not user_id or user_id == "Guest":
        return {}

    user = frappe.get_cached_value(
        "User",
        user_id,
        ["name", "email", "first_name", "last_name", "full_name", "user_type", "enabled"],
        as_dict=True,
    )
    data = dict(user or {})
    data["roles"] = frappe.get_roles(user_id)
    return data


def login_user(usr: str, pwd: str) -> str:
    frappe.clear_cache(user=usr)

    login_manager = getattr(frappe.local, "login_manager", None) or LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)

    if login_manager.force_user_to_reset_password():
        frappe.throw(_("Password reset is required"), frappe.AuthenticationError)

    if should_run_2fa(login_manager.user):
        authenticate_for_2factor(login_manager.user)
        if not confirm_otp_token(login_manager):
            frappe.throw(_("Two-factor authentication is required"), frappe.AuthenticationError)

    frappe.form_dict.pop("pwd", None)
    login_manager.post_login()
    frappe.local.login_manager = login_manager
    return frappe.session.sid


def unexpected_error(
    context: str,
    message: str = _("Something went wrong. Please try again."),
) -> dict:
    frappe.log_error(frappe.get_traceback(), context)
    return error_response(message, status_code=500)
