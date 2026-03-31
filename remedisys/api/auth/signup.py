import frappe
from frappe import _
from frappe.core.doctype.user.user import sign_up
from remedisys.api.auth.utils import error_response, get_user_data, login_user, success_response, unexpected_error


def _split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


@frappe.whitelist(allow_guest=True, methods=["POST"])
def signup(
    email: str | None = None,
    password: str | None = None,
    full_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
):
    """Create a website user account and log the user in."""
    email = (email or frappe.form_dict.get("email") or "").strip().lower()
    password = password or frappe.form_dict.get("password")
    full_name = (full_name or frappe.form_dict.get("full_name") or "").strip()
    first_name = (first_name or frappe.form_dict.get("first_name") or "").strip()
    last_name = (last_name or frappe.form_dict.get("last_name") or "").strip()

    if not email or not password:
        return error_response(_("email and password are required"), status_code=400)

    if not (full_name or first_name):
        return error_response(_("full_name or first_name is required"), status_code=400)

    if not full_name:
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()

    try:
        result_code, message = sign_up(email=email, full_name=full_name, redirect_to="")
        user = frappe.get_doc("User", email)

        if result_code == 0:
            return error_response(message, status_code=409, user=get_user_data(user.name))

        if first_name or last_name:
            derived_first_name, derived_last_name = _split_name(full_name)
            user.first_name = first_name or derived_first_name
            user.last_name = last_name or derived_last_name
        user.new_password = password
        user.flags.ignore_permissions = True
        user.save()
        frappe.db.commit()

        frappe.local.form_dict["usr"] = email
        frappe.local.form_dict["pwd"] = password
        sid = login_user(email, password)
    except frappe.AuthenticationError:
        return error_response(_("Account created, but automatic login failed"), status_code=401)
    except Exception:
        return unexpected_error("RemediSys Auth Signup")

    return success_response(
        _("Signup successful"),
        signup_message=message,
        sid=sid,
        user=get_user_data(frappe.session.user),
    )
