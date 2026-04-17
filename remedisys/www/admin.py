"""
Stub required by Frappe's website router.

Frappe's template_page.py only wires up get_context() for a .html page when
a SIBLING .py file exists on disk. The real controller lives in the
admin/ package's __init__.py (because Python's import resolution prefers
the package over this file when resolving `remedisys.www.admin`).

Do not add logic here — it will never run. Edit admin/__init__.py instead.
"""

# Re-export so any stray `from remedisys.www.admin import X` hits the package.
from remedisys.www.admin import (  # noqa: F401
	ADMIN_ROLES,
	get_context,
	guard,
	no_cache,
)
