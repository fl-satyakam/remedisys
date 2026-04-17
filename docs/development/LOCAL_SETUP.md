# Remedisys — Local Development Setup

Run the full stack (Frappe + ERPNext + Healthcare + Remedisys) on your
machine in under 30 minutes. Written for an engineer joining the project
for the first time.

---

## 1. Prerequisites

| Tool       | Version         | Install hint                                  |
|------------|-----------------|-----------------------------------------------|
| Python     | 3.10 – 3.14     | `brew install python@3.12`                    |
| Node.js    | 20 LTS          | `brew install node@20`                        |
| MariaDB    | 10.6+           | `brew install mariadb` then `brew services start mariadb` |
| Redis      | 7+              | `brew install redis` (bench starts its own instance) |
| wkhtmltopdf| 0.12.6          | See frappe docs — optional, PDFs only         |
| git        | any             | preinstalled                                  |

MariaDB must allow `utf8mb4` and have the `frappe` user creatable. Follow
the [Frappe prerequisites guide](https://frappeframework.com/docs/user/en/installation)
for the one-time `my.cnf` tuning.

## 2. Install `bench`

```bash
pipx install frappe-bench
# or, if you don't use pipx:
pip install --user frappe-bench
```

## 3. Create the bench

```bash
cd ~  # or wherever you keep code
bench init --frappe-branch version-16 frappe-bench
cd frappe-bench
```

## 4. Get a site

```bash
bench new-site remedisys.localhost \
    --mariadb-root-password <your-root-pwd> \
    --admin-password <pick-one>
bench use remedisys.localhost
```

## 5. Install apps (order matters)

```bash
bench get-app --branch version-16 erpnext
bench get-app --branch version-16 healthcare
bench get-app remedisys git@github.com:fl-satyakam/remedisys.git

bench --site remedisys.localhost install-app erpnext
bench --site remedisys.localhost install-app healthcare
bench --site remedisys.localhost install-app remedisys
```

Installing `remedisys` runs `after_install`, which:

- Adds AI custom fields to Patient Encounter (15 fields under an
  `AI Assistant` section, see `remedisys/setup.py`).
- Creates the default Physician user `saty@remedisys.local` with roles
  `Physician` + `Healthcare Administrator`.
- Links that user to a `Healthcare Practitioner` record
  (`HLC-PRAC-2026-00001` on a fresh site).
- Hides 13 ERPNext and Healthcare workspaces that the clinician doesn't
  need — see `remedisys/setup_cleanup.py`.

## 6. Configure site secrets

Edit `sites/remedisys.localhost/site_config.json` and add:

```json
{
    "openai_api_key": "sk-...",
    "encryption_key": "<generated-by-bench>"
}
```

The OpenAI key lives in the shared `.secrets.local.md` (ask the team lead
— do not commit it).

## 7. Tune `common_site_config.json`

Open `sites/common_site_config.json` and ensure:

```json
{
    "gunicorn_workers": 3,
    "session_expiry": "168:00:00",
    "session_expiry_mobile": "720:00:00"
}
```

(`gunicorn_workers: 21` is a known bad default we corrected. Seven-day
sessions keep the doctor logged in across shifts.)

## 8. Run the stack

```bash
bench start
```

This boots Frappe's web server, the socketio worker, three background
workers (short / long / default), and its own Redis. Visit
<http://remedisys.localhost:8000>.

Log in as:

```
Email:    saty@remedisys.local
Password: Doctor@Remedisys2026
```

Physicians land on
`/app/patient-appointment/view/list?appointment_date=Today&practitioner=<theirs>`
— see `remedisys/session_hooks.py`. Administrator sees the default desk.

## 9. Day-to-day commands

| Task                         | Command                                              |
|------------------------------|------------------------------------------------------|
| Apply code changes           | `bench --site remedisys.localhost migrate`           |
| Rebuild JS/CSS               | `bench build --app remedisys`                        |
| Python console with Frappe   | `bench --site remedisys.localhost console`           |
| Run a function inline        | `bench --site remedisys.localhost execute remedisys.<mod>.<fn>` |
| Clear cache                  | `bench --site remedisys.localhost clear-cache`       |
| View errors                  | `bench --site remedisys.localhost show-logs` or `tail -f sites/remedisys.localhost/logs/web.log` |

## 10. Editing `remedisys` in place

`remedisys` is installed editable. Changes to Python take effect after
`bench restart` (or the file-watcher in `bench start` reloads
automatically). JS/CSS changes require `bench build --app remedisys` and
a hard browser refresh (Cmd+Shift+R).

## 11. Verifying the install is healthy

```bash
bench --site remedisys.localhost list-apps
# Expect: frappe, erpnext, healthcare, remedisys

bench --site remedisys.localhost doctor
# Expect: no errors
```

If you see a hung request, see `docs/development/TROUBLESHOOTING.md`.
