"""
Reversible UI cleanup for Remedisys.

Goal: present the doctor with a lean sidebar. We *hide* (not delete) ERPNext
and Healthcare workspaces the clinician doesn't need. Anything hidden here
can be re-enabled by removing it from the lists below and running
`bench --site <site> migrate`.

Called from `setup.after_install` and `setup.after_migrate`, so a fresh
clone gets the same lean UI after a single migrate.

Why `Workspace.public = 0`:
    Setting public=0 removes the workspace from every user's sidebar without
    touching the DocTypes, permissions, or data behind it. Flipping back to
    public=1 restores it instantly. This is the lightest-weight reversible
    hide Frappe offers.
"""

import frappe


# Workspaces to hide from every user's sidebar. The underlying DocTypes and
# modules remain installed; only the sidebar entry disappears.
HIDDEN_WORKSPACES = (
    # ERPNext modules the clinic does not use in Phase 0-3
    "Buying",
    "CRM",
    "Manufacturing",
    "Projects",
    "Quality",
    "Selling",
    "Stock",
    "Subcontracting",
    "Support",
    "Assets",
    # Healthcare (Marley) areas out of scope for the Physician role right now.
    # Re-surface when the matching phase lights up:
    #   Inpatient      -> Phase 3 (admissions)
    #   Insurance      -> Phase 4 (front-office + billing)
    #   Rehabilitation -> deferred; not in the clinical roadmap
    "Inpatient",
    "Insurance",
    "Rehabilitation",
    # Duplicates of the unified Healthcare workspace. Their link sets are
    # subsets of Healthcare's, so showing them splits the doctor's focus
    # and lets Frappe's "pick a module" modal reappear. Keep the
    # workspaces installed (other apps may Link to them) — just hide.
    "Outpatient",
    "Diagnostics",
)


def hide_unused_workspaces() -> list[str]:
    """Flip `public` to 0 on every workspace in HIDDEN_WORKSPACES.

    Returns the list of workspace names actually updated (useful for logs).
    Idempotent — a second run is a no-op.
    """
    updated: list[str] = []
    for ws_name in HIDDEN_WORKSPACES:
        if not frappe.db.exists("Workspace", ws_name):
            continue
        if frappe.db.get_value("Workspace", ws_name, "public") == 0:
            continue
        frappe.db.set_value("Workspace", ws_name, "public", 0)
        updated.append(ws_name)

    if updated:
        frappe.clear_cache()
    return updated
