# Remedisys — UI Conventions

One rule: **use Frappe UI primitives for every new piece of desk UI**.

## Why

- Frappe ships a consistent design system (dialogs, controls, buttons,
  grids) that already respects the user's theme (light/dark), locale,
  and accessibility settings.
- Hand-rolled jQuery widgets drift — from ERPNext on both sides — and
  force every engineer to re-solve focus traps, escape handlers,
  keyboard nav, and RTL layout.
- Anything we build with `frappe.ui.*` is testable via Cypress the same
  way ERPNext tests its own screens.

## Primitives to reach for first

| Need                         | Use                                          |
|------------------------------|----------------------------------------------|
| Modal form                   | `frappe.ui.Dialog({...})`                    |
| Confirm / yes-no             | `frappe.confirm(msg, on_yes, on_no)`         |
| Quick prompt                 | `frappe.prompt(fields, callback, title)`     |
| Inline message               | `frappe.msgprint({...})`                     |
| Toast                        | `frappe.show_alert({message, indicator})`    |
| Form field / control         | `frappe.ui.form.make_control({...})`         |
| Button on a DocType form     | `frm.add_custom_button(label, cb, group)`    |
| Sidebar action               | `frm.page.add_menu_item(label, cb)`          |
| Table / grid                 | `frappe.ui.form.Grid` or `frappe.views.ListView` |
| Modal that renders a list    | `frappe.views.QuickEntryForm`                |

Reference: <https://docs.frappe.io/framework/user/en/api/form>.

## The existing AI Assistant panel

`public/js/patient_encounter.js` renders a custom right-side panel with
vanilla jQuery template literals and a companion CSS file
(`public/css/medical_agent.css`). It predates this convention.

**Status**: tolerated, but freeze-on-sight.

- Any **new** feature added to Patient Encounter must go through a
  `frappe.ui.Dialog` (or a proper Frappe form section) — not a new
  hand-rolled panel.
- Bug fixes to the AI panel keep the existing shape; don't rewrite
  around them.
- The panel is tracked for a future refactor in Phase 3 of the
  execution plan, once the DocType persistence lands and the panel
  stops being a stateful client-only blob.

## Styling new UI

If you must write CSS (rare — most Frappe components are themed
already):

- BEM naming: `.block__element--modifier` (matches existing
  `medical_agent.css`).
- Hardcoded hex backgrounds with `!important` — Frappe's CSS variables
  are sometimes overwritten by theme caches.
- **No gradients**. Flat white `#ffffff` or light gray `#f7f8fa` for
  containers.
- Include `[data-theme="dark"]` overrides for every major element.
- Buttons: 42px primary, 32px secondary, 14px/12px font.

The full rulebook lives in `.claude/CLAUDE.md` — read it before touching
styling.
