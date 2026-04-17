# Remedisys — Developer Docs

Short, specific guides for engineers working on this app. The broader
product specs and architecture papers live in the parent
`remedisys-docs/` repo.

## Start here

### Development

| Doc                                      | Read when                                     |
|------------------------------------------|-----------------------------------------------|
| [development/LOCAL_SETUP.md](development/LOCAL_SETUP.md) | Joining the project — bench install + first login |
| [development/AUTH.md](development/AUTH.md)               | Touching login, session, or role-based landing |
| [development/UI_CONVENTIONS.md](development/UI_CONVENTIONS.md) | Building any desk UI                |
| [development/MODULE_STRIP.md](development/MODULE_STRIP.md)     | Hiding or re-enabling an ERPNext / Healthcare workspace |

### Deployment

| Doc                                           | Read when                                        |
|-----------------------------------------------|--------------------------------------------------|
| [deployment/GCP_DEPLOYMENT.md](deployment/GCP_DEPLOYMENT.md) | Understanding prod topology, rollback, backups, secrets |
| [deployment/CICD.md](deployment/CICD.md)                     | Touching GitHub Actions, rotating secrets, debugging a red build |

### Change log

Dated notes on user-visible changes — what changed, why, and how to
revert. Newest first:

- [2026-04-17 — Healthcare-Unified Landing](changes/2026-04-17-healthcare-unified-landing.md)
  — physicians land on `/app/healthcare`; Outpatient/Diagnostics
  workspaces hidden as duplicates; Marley Health module-picker modal
  bypassed.

## Where the code lives

```
remedisys/
  hooks.py              — Frappe registration (hooks, fields, routes)
  setup.py              — after_install / after_migrate bootstraps
  setup_cleanup.py      — reversible workspace hiding
  session_hooks.py      — role-based post-login redirect
  api/
    auth/               — login / user helpers
    medical_agent.py    — Whisper + GPT-4o pipeline (AI panel backend)
  public/
    js/patient_encounter.js   — AI Assistant panel (legacy vanilla jQuery)
    css/medical_agent.css     — panel styling
```

Deeper architecture notes are in `REMEDISYS_ARCHITECTURE.md` at the app
root, and in the sibling `remedisys-docs/architecture/` folder.
