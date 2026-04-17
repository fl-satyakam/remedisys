frappe.provide("remedisys.breadcrumbs");

remedisys.breadcrumbs.HIDDEN_WORKSPACES = new Set([
	"Outpatient",
	"Diagnostics",
	"Inpatient",
	"Insurance",
	"Rehabilitation",
]);
remedisys.breadcrumbs.PREFERRED_WORKSPACE = "Healthcare";

$(document).on("app_ready", () => {
	if (!frappe.breadcrumbs || !frappe.breadcrumbs.set_workspace) return;

	const original = frappe.breadcrumbs.set_workspace.bind(frappe.breadcrumbs);

	frappe.breadcrumbs.set_workspace = function (breadcrumbs) {
		const meta = frappe.get_meta(breadcrumbs.doctype);
		const workspaces = meta?.__workspaces;
		if (Array.isArray(workspaces) && workspaces.length > 1) {
			const hasPreferred = workspaces.includes(
				remedisys.breadcrumbs.PREFERRED_WORKSPACE,
			);
			if (hasPreferred) {
				meta.__workspaces = [
					remedisys.breadcrumbs.PREFERRED_WORKSPACE,
					...workspaces.filter(
						(w) =>
							w !== remedisys.breadcrumbs.PREFERRED_WORKSPACE &&
							!remedisys.breadcrumbs.HIDDEN_WORKSPACES.has(w),
					),
				];
			}
		}
		return original(breadcrumbs);
	};
});
