# Remedisys — Auth & Role-Based Landing

Frappe's stock `/login` page handles credentials; we override the
post-login landing to drop each role on a page that's already filtered
for their day.

## The flow

```
POST /api/method/login
  └─ LoginManager.login()
      ├─ make_session()              ← runs on_session_creation hook
      │   └─ remedisys.session_hooks.on_session_creation
      │         sets frappe.local.flags.home_page = "<role-specific path>"
      └─ set_user_info()
          └─ frappe.local.response["home_page"] = get_home_page()
                get_home_page() returns flags.home_page early  ← our value wins
```

The login response now carries a `home_page` field that the desk JS
redirects the browser to. Physicians land on
`/app/patient-appointment/view/list?appointment_date=Today&practitioner=<theirs>`.

## The two hook points

**`session_hooks.py`** — runs on every fresh login:

```python
def on_session_creation(login_manager):
    user = login_manager.user
    roles = set(frappe.get_roles(user))
    if PHYSICIAN_ROLE in roles:
        frappe.local.flags.home_page = _physician_landing(user)
        frappe.local.response["home_page"] = ...
```

Why set `flags.home_page` *and* `response["home_page"]`? Because
`set_user_info()` runs *after* the hook and overwrites
`response["home_page"]` via `get_home_page()`. Setting
`flags.home_page` makes `get_home_page()` return early with our value,
so the overwrite is effectively a no-op that preserves what we want.
Writing both keeps the code robust if the internal order ever flips.

**Include the `/app/` prefix.** The login page JS uses
`r.home_page` verbatim as `window.location.href`. A path like
`patient-appointment/view/list` without the prefix resolves to
`/patient-appointment/...`, which is a website route — 404 on a desk-only
app. Always return full paths starting with `/app/`.

**`hooks.py`** — static fallback:

```python
on_session_creation = ["remedisys.session_hooks.on_session_creation"]
role_home_page = {
    "Physician": "patient-appointment/view/list",
}
```

`role_home_page` is the plain Frappe setting. It kicks in when a user
lacks a practitioner link (so the query-string filters can't be built)
or when the hook raises. It never produces per-physician filtering —
that's the whole point of the hook.

## Session persistence

Configured in `sites/common_site_config.json`:

```json
"session_expiry": "168:00:00",
"session_expiry_mobile": "720:00:00"
```

- Desktop sessions last 7 days.
- Mobile app sessions last 30 days.
- The `sid` cookie expiry matches these values; the browser handles
  renewal on every authenticated request.

## Adding a new role

1. Add the role to `DEFAULT_DOCTOR_ROLES` in `setup.py` (if it's a
   bootstrap user), or create the role via the UI (Desk → Roles).
2. Add a branch to `on_session_creation` in `session_hooks.py`:
   ```python
   if NURSE_ROLE in roles:
       frappe.local.flags.home_page = _nurse_queue(user)
       frappe.local.response["home_page"] = ...
   ```
3. Add a fallback in `hooks.py` → `role_home_page`.
4. Restart bench: `pkill -f "bench serve" && bench start`.

## Default user

`after_install` / `after_migrate` guarantees these exist on a fresh
site (see `setup.ensure_doctor_user`):

| Field        | Value                           |
|--------------|---------------------------------|
| Email        | `saty@remedisys.local`          |
| Password     | `Doctor@Remedisys2026`          |
| Roles        | Physician, Healthcare Administrator |
| Practitioner | `HLC-PRAC-2026-<N>` (first unlinked, else created) |

The bootstrap is idempotent — running `after_migrate` again is safe.
Changing the password is a manual `bench --site remedisys.localhost
set-user-password saty@remedisys.local <new>`.
