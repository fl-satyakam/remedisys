# Remedisys — Module & Workspace Strip

The clinic-only experience we want for a doctor is not what ERPNext or
Healthcare ship with by default. This doc explains what we hide, where
the lever is, and how to un-hide when a phase needs it back.

## What's hidden

### ERPNext (10 workspaces)

`Buying`, `CRM`, `Manufacturing`, `Projects`, `Quality`, `Selling`,
`Stock`, `Subcontracting`, `Support`, `Assets`.

These aren't relevant to a clinic's daily workflow. The modules stay
installed (so reporting, audit, and upstream migrations keep working);
only the sidebar entries disappear.

### Healthcare / Marley (3 workspaces)

- **Inpatient** — out of scope until Phase 3 (admissions).
- **Insurance** — out of scope until Phase 4 (front-office + billing).
- **Rehabilitation** — not on the roadmap; re-enable only if a specific
  clinic requests it.

### Still visible

`Home`, `Healthcare`, `Outpatient`, `Diagnostics`, `Setup` (healthcare),
`Users`, `Build`, `Welcome`, `ERPNext Settings`, `Invoicing`,
`Financial Reports`, `Integrations`, `Website`.

## Where the lever is

`remedisys/setup_cleanup.py` — edit the `HIDDEN_WORKSPACES` tuple.

```python
HIDDEN_WORKSPACES = (
    "Buying",
    ...
)
```

After editing:

```bash
bench --site remedisys.localhost migrate
```

`after_migrate` calls `hide_unused_workspaces()`, which sets
`public = 0` on every workspace in the tuple. The function is idempotent
— running it twice does nothing extra.

## How to un-hide

Two options:

1. **Permanently, for everyone**: remove the workspace name from
   `HIDDEN_WORKSPACES` and `bench migrate`. Then manually flip it back:

   ```bash
   bench --site remedisys.localhost execute \
     frappe.db.set_value \
     --kwargs "{'doctype': 'Workspace', 'name': 'Insurance', 'fieldname': 'public', 'value': 1}"
   ```

2. **Temporarily, for one user**: the user can go to their profile
   → "Sidebar Items" and add the workspace back for themselves.

## Why not delete modules?

- Uninstalling ERPNext sub-modules is unsupported and breaks migrations.
- Uninstalling Healthcare sub-areas would break DocType links across
  the graph (e.g. `Patient Encounter` → `Inpatient Record`).
- `public = 0` is the exact bit Frappe already uses for "hide this from
  the sidebar" — we're not bypassing any framework concern.

## Scope creep checklist

Before adding a workspace to `HIDDEN_WORKSPACES`:

- [ ] Confirmed the module is not on the Phase 0-3 execution plan.
- [ ] Confirmed no DocType we edit has a hard dependency on it (Link
      fields resolve fine even if the target workspace is hidden).
- [ ] Added a comment in `setup_cleanup.py` pointing to the phase that
      will re-enable it.
