# 2026-04-17 — Healthcare-Unified Landing

## What changed

### 1. Physicians land on the Healthcare workspace, not a filtered list

**Before**: `on_session_creation` sent doctors to
`/app/patient-appointment/view/list?appointment_date=Today&practitioner=<theirs>`.

**After**: `/app/healthcare` — Marley Health's unified workspace.

Files:

- `remedisys/session_hooks.py` — `ROLE_WORKSPACES` maps role → Workspace
  name, `_workspace_url` derives the URL via `frappe.scrub`. The old
  `_physician_filters` / `_build_list_url` helpers are gone; the new
  landing doesn't need filters because the workspace is the surface.

### 2. Duplicate healthcare workspaces are hidden

**Before**: sidebar showed `Healthcare`, `Outpatient`, `Inpatient`,
`Diagnostics`, `Insurance`, `Rehabilitation`, `Setup` — seven entries,
most with overlapping content.

**After**: sidebar shows only the ones that are *not* subsets of
Healthcare:

| Workspace        | State   | Reason                                        |
|------------------|---------|-----------------------------------------------|
| Healthcare       | visible | Primary surface. Has Patient Encounter, Patient Appointment, Masters, Orders, Diagnostics, Insurance, Rehabilitation, Nursing, Inpatient, etc. — 14 groups. |
| Setup            | visible | Medical codes, templates, facility setup — distinct from clinical workflow. |
| Outpatient       | hidden  | Its 5 links (Patient Appointment, Patient Encounter, Vital Signs, Clinical Note, Nursing Task) are **all** present inside Healthcare's `Outpatient` group. |
| Diagnostics      | hidden  | Same story — every link is inside Healthcare's `Diagnostic Module` group. |
| Inpatient        | hidden  | Content present under Healthcare's `Inpatient` group. Re-visible in Phase 3 when admissions flow goes live. |
| Insurance        | hidden  | Content under Healthcare's `Insurance` group. Re-visible in Phase 4 (billing). |
| Rehabilitation   | hidden  | Content under Healthcare's `Rehabilitation and Physiotherapy` group. Deferred; re-enable on demand. |

Files:

- `remedisys/setup_cleanup.py` — `Outpatient`, `Diagnostics` added to
  `HIDDEN_WORKSPACES`. The hide helper flips `Workspace.public` to 0,
  which removes the sidebar entry without deleting the workspace, its
  DocTypes, or its data.

### 3. Marley Health module-picker dialog stops appearing

**Before**: clicking the "Marley Health" app card on `/desk` opened a
modal listing the seven healthcare modules (screenshot attached in
original issue). Doctors had to click a second time to get into any
useful screen.

**After**: users never see that modal during normal flow because login
now routes them straight to `/app/healthcare`, bypassing the
app-picker screen at `/desk`.

The modal is framework-level behavior (shown whenever an app has
multiple Module Defs) and we don't override it directly — we just
don't put the doctor on the path that triggers it. If a user manually
navigates to `/desk` and clicks the Marley Health card, the modal
still shows; that's intentional (admins may want it).

## Why this shape

The Healthcare workspace already contains the full Marley Health link
graph. Everything the other six workspaces expose is a subset that was
duplicated for role-based sidebar presentation — a pattern that makes
sense when you have dedicated receptionists, OPD desks, and therapists,
but that *adds* friction for a doctor who wants one surface.

We chose to keep the workspaces installed (not uninstall Marley's
modules) so that:

- Future phases can re-enable a workspace with a single line change.
- Link fields on other DocTypes that point into these modules keep
  resolving.
- Marley Health migrations don't hit "missing module" errors.

The hide is reversible: delete the name from `HIDDEN_WORKSPACES` and
run `bench migrate`. A user can also re-enable a workspace for
themselves via their profile "Sidebar Items".

## How to verify locally

```bash
pkill -f "bench serve" || true
bench --site remedisys.localhost clear-cache
bench start     # or: bench serve --port 8000 &

curl -s -X POST "http://remedisys.localhost:8000/api/method/login" \
    -d "usr=saty@remedisys.local&pwd=Doctor@Remedisys2026" | python3 -m json.tool
# expect: "home_page": "/app/healthcare"
```

Open the URL in a browser, hard-refresh, and confirm:

- Sidebar on the Healthcare workspace shows `Patient`,
  `Healthcare Practitioner`, ..., and under "Outpatient":
  `Patient Appointment`, `Patient Encounter`, `Vital Signs`,
  `Clinical Procedure`, `Fee Validity`.
- `/desk` (if manually visited) shows only three app cards
  (Framework, Quality, Marley Health) — no Outpatient / Diagnostics
  tiles in the picker.

## Reverting any single change

| Want back                     | Change                                                   |
|-------------------------------|----------------------------------------------------------|
| Filtered Patient Appointment  | In `session_hooks.py`, restore `_physician_filters` and pass them through to `_build_list_url("Patient Appointment", ...)`. |
| Outpatient sidebar entry      | Remove `"Outpatient"` from `HIDDEN_WORKSPACES` and `bench migrate`. |
| All healthcare workspaces     | Remove the whole Healthcare block from `HIDDEN_WORKSPACES` and `bench migrate`. |

No data migration is required for any of these — it's all config.
