"""
Admin Portal backend endpoints.

All endpoints in this module require the caller to hold either the
``System Manager`` role OR the ``Remedisys Admin`` role OR be the
Administrator user. Guests are rejected.

Nothing in this module writes to the live encounter flow — it only
reads state, lists logs, and exposes a force-clear of Redis state
(delegated to the medical_agent endpoint).
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe import _


ADMIN_ROLES = {"System Manager", "Remedisys Admin"}


def _require_admin():
    """Raise 403/redirect if the caller isn't an admin."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)
    user_roles = set(frappe.get_roles(frappe.session.user))
    if frappe.session.user == "Administrator":
        return
    if ADMIN_ROLES & user_roles:
        return
    frappe.throw(_("Admin role required"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_agent_logs(filters=None, start=0, page_length=50):
    """Return a paginated slice of Medical Agent Log rows.

    ``filters`` is an optional dict of {event_type, visit_id, from_date,
    to_date, errors_only}. All optional.
    """
    _require_admin()
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except ValueError:
            filters = {}
    filters = filters or {}

    query_filters = {}
    if filters.get("event_type"):
        query_filters["event_type"] = filters["event_type"]
    if filters.get("visit_id"):
        query_filters["visit_id"] = filters["visit_id"]
    if filters.get("errors_only"):
        query_filters["event_type"] = "error"

    from_date = filters.get("from_date") or None
    to_date = f"{filters['to_date']} 23:59:59" if filters.get("to_date") else None
    if from_date and to_date:
        query_filters["creation"] = ["between", [from_date, to_date]]
    elif from_date:
        query_filters["creation"] = [">=", from_date]
    elif to_date:
        query_filters["creation"] = ["<=", to_date]

    try:
        start = max(int(start), 0)
    except (TypeError, ValueError):
        start = 0
    try:
        page_length = max(min(int(page_length), 200), 1)
    except (TypeError, ValueError):
        page_length = 50

    rows = frappe.get_all(
        "Medical Agent Log",
        filters=query_filters,
        fields=[
            "name", "creation", "event_type", "visit_id", "appointment",
            "sequence_number", "duration_ms", "provider", "speaker_count",
            "text_length", "error_message",
        ],
        order_by="creation desc",
        start=start,
        page_length=page_length,
    )
    total = frappe.db.count("Medical Agent Log", filters=query_filters)
    return {"rows": rows, "total": total, "start": start, "page_length": page_length}


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def dashboard_stats():
    """Return small headline metrics for /admin."""
    _require_admin()
    today = frappe.utils.today()
    twenty_four_hours_ago = frappe.utils.now_datetime() - timedelta(hours=24)

    chunks_today = frappe.db.count(
        "Medical Agent Log",
        filters={"event_type": "transcribe", "creation": (">=", today)},
    )

    avg_transcribe_ms = _avg_duration("transcribe", limit=100)
    avg_recommend_ms = _avg_duration("recommend", limit=100)

    total_24h = frappe.db.count(
        "Medical Agent Log",
        filters={"creation": (">=", twenty_four_hours_ago)},
    )
    errors_24h = frappe.db.count(
        "Medical Agent Log",
        filters={
            "event_type": "error",
            "creation": (">=", twenty_four_hours_ago),
        },
    )
    error_rate = (errors_24h / total_24h) if total_24h else 0

    return {
        "chunks_today": chunks_today,
        "avg_transcribe_ms": avg_transcribe_ms,
        "avg_recommend_ms": avg_recommend_ms,
        "errors_24h": errors_24h,
        "total_events_24h": total_24h,
        "error_rate": round(error_rate, 4),
    }


def _avg_duration(event_type: str, limit: int = 100):
    rows = frappe.get_all(
        "Medical Agent Log",
        filters={"event_type": event_type, "duration_ms": (">", 0)},
        fields=["duration_ms"],
        order_by="creation desc",
        limit=limit,
    )
    if not rows:
        return 0
    return int(sum(r.duration_ms or 0 for r in rows) / len(rows))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

LIVE_CACHE_PATTERN = "medical_agent:visit:*"


def live_visit_keys():
    """Return the list of visit_ids that currently have a Redis state.

    Guarded because some cache backends don't support KEYS(pattern).
    """
    try:
        redis = frappe.cache().get_redis_connection()
        # Frappe prefixes cache keys with the site/namespace. Use the
        # same pattern handling as frappe.cache internals.
        raw_keys = redis.keys(_pattern_for_redis(LIVE_CACHE_PATTERN))
        ids = []
        for k in raw_keys:
            if isinstance(k, bytes):
                k = k.decode("utf-8", errors="ignore")
            # key looks like: <prefix>|medical_agent:visit:<appt>
            if "medical_agent:visit:" in k:
                ids.append(k.split("medical_agent:visit:", 1)[1])
        return ids
    except Exception:
        return []


def _pattern_for_redis(pattern: str) -> str:
    """Frappe cache prepends a site-specific prefix to every key. Use the
    wildcard version so KEYS returns every site key matching the pattern.
    """
    try:
        prefix = frappe.cache().make_key("")
        if isinstance(prefix, bytes):
            prefix = prefix.decode("utf-8", errors="ignore")
        return f"{prefix}{pattern}"
    except Exception:
        return f"*{pattern}"


def load_visit_state(visit_id: str) -> dict:
    """Read-only mirror of medical_agent._load_state so /admin doesn't
    import the main module (avoid circular-ish edits)."""
    raw = frappe.cache().get_value(f"medical_agent:visit:{visit_id}")
    if not raw:
        return {}
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return {}


@frappe.whitelist()
def recent_error_logs(limit=50):
    """Return recent Error Log entries that look like they came from medical_agent."""
    _require_admin()
    try:
        limit = max(min(int(limit), 200), 1)
    except (TypeError, ValueError):
        limit = 50

    rows = frappe.db.sql(
        """
        SELECT name, creation, method, error
        FROM `tabError Log`
        WHERE (method LIKE %(pat)s OR error LIKE %(pat)s)
        ORDER BY creation DESC
        LIMIT %(lim)s
        """,
        {"pat": "%medical_agent%", "lim": limit},
        as_dict=True,
    )
    return rows


@frappe.whitelist()
def delete_error_log(name):
    _require_admin()
    if not name:
        frappe.throw(_("name is required"))
    try:
        frappe.delete_doc("Error Log", name, ignore_permissions=True)
        frappe.db.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
