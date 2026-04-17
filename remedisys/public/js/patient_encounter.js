/**
 * Remedisys — Medical AI Assistant
 * Adds an "AI Assistant" button to Patient Encounter that opens
 * a right-side panel with live transcription, Spanish translation,
 * interactive clinical recommendations, and encounter auto-population.
 *
 * Data is auto-saved to the encounter after each audio chunk, so
 * it survives page reloads and can be reviewed later.
 */

frappe.ui.form.on("Patient Encounter", {
	refresh(frm) {
		// Add AI Assistant button with border-beam effect
		frm.add_custom_button(
			__("AI Assistant"),
			() => toggleAIPanel(frm),
		);

		// Style the AI Assistant button with border-beam wrapper
		setTimeout(() => {
			const $btn = frm.$wrapper.find('.btn-custom:contains("AI Assistant")');
			if ($btn.length && !$btn.parent().hasClass("ai-btn-beam-wrapper")) {
				$btn.wrap('<div class="ai-btn-beam-wrapper"></div>');
				$btn.addClass("ai-btn-beam");
			}
		}, 100);

		// Hide irrelevant sections for AI-first workflow
		const fieldsToHide = [
			"inpatient_record", "inpatient_status",
			"google_meet_link",
			"invoiced", "submit_orders_on_save",
			"sb_source", "source", "referring_practitioner",
			"insurance_section", "insurance_policy", "insurance_coverage",
			"insurance_payor", "coverage_status",
			"codification", "codification_table",
			"rehabilitation_section", "therapies",
		];
		fieldsToHide.forEach(f => {
			if (frm.fields_dict[f]) frm.toggle_display(f, false);
		});
	},
});

let aiPanelInstance = null;

function toggleAIPanel(frm) {
	if (aiPanelInstance) {
		aiPanelInstance.destroy();
		aiPanelInstance = null;
		return;
	}
	aiPanelInstance = new AIAssistantPanel(frm);
}

class AIAssistantPanel {
	constructor(frm) {
		this.frm = frm;
		this.visitId = frm.doc.name || frappe.utils.get_random(10);
		this.mediaRecorder = null;
		this.mediaStream = null;
		this.chunkInterval = null;
		this.seqNum = 0;
		this.isRecording = false;
		this.processingCount = 0;
		this.lastRecommendation = null;
		this.render();
		this._loadSavedState();
	}

	render() {
		this.$overlay = $('<div class="ai-overlay"></div>').appendTo("body");
		this.$panel = $(`
			<div class="ai-panel">
				<!-- Header -->
				<div class="ai-panel__header">
					<div class="ai-panel__header-left">
						<div class="ai-panel__logo">
							<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>
						</div>
						<div>
							<div class="ai-panel__title">${__("AI Assistant")}</div>
							<div class="ai-panel__subtitle">${__("Medical Transcription & Analysis")}</div>
						</div>
					</div>
					<button class="ai-panel__close" title="${__("Close")}">
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
					</button>
				</div>

				<!-- Recording Controls -->
				<div class="ai-panel__controls">
					<div class="ai-panel__mic-row">
						<button class="ai-panel__mic-btn ai-panel__mic-btn--record" title="${__("Start Recording")}">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
							<span>${__("Start Recording")}</span>
						</button>
						<button class="ai-panel__mic-btn ai-panel__mic-btn--stop" disabled title="${__("Stop Recording")}">
							<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
							<span>${__("Stop")}</span>
						</button>
					</div>
					<div class="ai-panel__controls-secondary">
						<button class="ai-panel__icon-btn ai-panel__reset-btn" title="${__("Reset Session")}">
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
							<span>${__("Reset")}</span>
						</button>
						<div class="ai-panel__lang-wrapper">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
							<select class="ai-panel__lang-select">
								<option value="">${__("Auto-detect")}</option>
								<option value="en">English</option>
								<option value="es">Spanish</option>
							</select>
						</div>
					</div>
				</div>

				<!-- Status -->
				<div class="ai-panel__status">
					<span class="ai-panel__status-dot ready"></span>
					<span class="ai-panel__status-text">${__("Ready to record")}</span>
					<span class="ai-panel__visit-id">${this.visitId}</span>
				</div>

				<!-- Content cards -->
				<div class="ai-panel__body">
					<div class="ai-panel__card" data-section="transcript-en">
						<div class="ai-panel__card-header">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
							<span>${__("Patient Problem")}</span>
							<svg class="ai-collapse-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
						</div>
						<div class="ai-panel__card-body">
							<p class="ai-panel__empty-state">${__("Start recording to capture the conversation...")}</p>
						</div>
					</div>

					<div class="ai-panel__card" data-section="transcript-es">
						<div class="ai-panel__card-header">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
							<span>${__("Spanish Translation")}</span>
							<svg class="ai-collapse-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
						</div>
						<div class="ai-panel__card-body">
							<p class="ai-panel__empty-state">${__("Appears automatically after transcription...")}</p>
						</div>
					</div>

					<div class="ai-panel__card" data-section="recommendation">
						<div class="ai-panel__card-header">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
							<span>${__("AI Recommendations")}</span>
							<svg class="ai-collapse-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
						</div>
						<div class="ai-panel__card-body">
							<p class="ai-panel__empty-state">${__("AI-powered recommendations will appear here...")}</p>
						</div>
					</div>

					<!-- Action buttons (hidden until recommendations exist) -->
					<div class="ai-panel__actions" style="display:none;">
						<button class="ai-panel__action-btn ai-panel__action-btn--populate">
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
							${__("Populate Encounter")}
						</button>
						<button class="ai-panel__action-btn ai-panel__action-btn--prescription">
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
							${__("Prepare Prescription")}
						</button>
					</div>
				</div>
			</div>
		`).appendTo("body");

		requestAnimationFrame(() => {
			this.$panel.addClass("ai-panel--open");
			this.$overlay.addClass("ai-overlay--visible");
		});

		this.$panel.find(".ai-panel__close").on("click", () => this.destroy());
		this.$overlay.on("click", () => this.destroy());
		this.$panel.find(".ai-panel__mic-btn--record").on("click", () => this.startRecording());
		this.$panel.find(".ai-panel__mic-btn--stop").on("click", () => this.stopRecording());
		this.$panel.find(".ai-panel__reset-btn").on("click", () => this.resetSession());
		this.$panel.find(".ai-panel__action-btn--populate").on("click", () => this.populateEncounter());
		this.$panel.find(".ai-panel__action-btn--prescription").on("click", () => this.openPrescriptionModal());

		// Collapse/expand card sections
		this.$panel.on("click", ".ai-panel__card-header", function (e) {
			// Don't collapse if user clicked a checkbox inside the card
			if ($(e.target).is("input")) return;
			$(this).closest(".ai-panel__card").toggleClass("ai-card--collapsed");
		});
	}

	/**
	 * Load previously saved AI state from the encounter document.
	 * This restores transcripts and recommendations on panel reopen / page reload.
	 */
	_loadSavedState() {
		const doc = this.frm.doc;

		// Restore transcript
		if (doc.ai_transcript) {
			this.updateTranscriptEn(doc.ai_transcript);
		}
		if (doc.ai_transcript_es) {
			this.updateTranscriptEs(doc.ai_transcript_es);
		}

		// Restore recommendation from saved JSON
		if (doc.ai_recommendation_json) {
			try {
				const rec = JSON.parse(doc.ai_recommendation_json);
				if (rec && rec.chief_complaint) {
					this.updateRecommendation(rec);
					this.setStatus(__("Loaded saved AI analysis"), "done");
				}
			} catch (_) {
				// JSON parse failed, ignore
			}
		}
	}

	/**
	 * Auto-save current AI state to the encounter document.
	 * Called after each successful chunk upload.
	 */
	_autoSave(transcriptEn, transcriptEs, recommendation) {
		const encounterName = this.frm.doc.name;
		if (!encounterName || encounterName.startsWith("new-")) return;

		frappe.xcall("remedisys.api.medical_agent.save_ai_state", {
			encounter_name: encounterName,
			full_transcript_en: transcriptEn || "",
			full_transcript_es: transcriptEs || "",
			recommendation: recommendation || {},
		}).catch((err) => {
			console.warn("Auto-save failed:", err);
		});
	}

	destroy() {
		this.stopRecording();
		this.$panel.removeClass("ai-panel--open");
		this.$overlay.removeClass("ai-overlay--visible");
		setTimeout(() => { this.$panel.remove(); this.$overlay.remove(); }, 300);
		aiPanelInstance = null;
	}

	setStatus(text, type = "ready") {
		this.$panel.find(".ai-panel__status-dot").attr("class", `ai-panel__status-dot ${type}`);
		this.$panel.find(".ai-panel__status-text").text(text);
	}

	updateTranscriptEn(text) {
		const $b = this.$panel.find('[data-section="transcript-en"] .ai-panel__card-body');
		$b.html(text
			? `<p class="ai-panel__transcript-text">${frappe.utils.escape_html(text)}</p>`
			: `<p class="ai-panel__empty-state">${__("Start recording to capture the conversation...")}</p>`
		);
	}

	updateTranscriptEs(text) {
		const $b = this.$panel.find('[data-section="transcript-es"] .ai-panel__card-body');
		$b.html(text
			? `<p class="ai-panel__transcript-text">${frappe.utils.escape_html(text)}</p>`
			: `<p class="ai-panel__empty-state">${__("Appears automatically after transcription...")}</p>`
		);
	}

	updateRecommendation(rec) {
		const $b = this.$panel.find('[data-section="recommendation"] .ai-panel__card-body');
		if (!rec || !rec.chief_complaint) {
			$b.html(`<p class="ai-panel__empty-state">${__("AI-powered recommendations will appear here...")}</p>`);
			this.$panel.find(".ai-panel__actions").hide();
			return;
		}

		this.lastRecommendation = rec;
		const esc = frappe.utils.escape_html;
		const urgClasses = { low: "ai-badge--low", moderate: "ai-badge--moderate", high: "ai-badge--high", emergent: "ai-badge--emergent" };
		const urgClass = urgClasses[rec.urgency] || "ai-badge--moderate";

		const checkList = (items, group) => (items || []).map((item, i) =>
			`<label class="ai-check-item">
				<input type="checkbox" checked data-group="${group}" data-index="${i}" value="${esc(item)}">
				<span>${esc(item)}</span>
			</label>`
		).join("") || `<p class="ai-panel__empty-state">${__("None")}</p>`;

		const bulletList = (items) => (items || []).map(i => `<li>${esc(i)}</li>`).join("") || `<li class="ai-panel__empty-state">${__("None")}</li>`;

		// Patient info badge
		const pi = rec.patient_info || {};
		const patientInfoHtml = (pi.name || pi.age || pi.sex) ? `
			<div class="ai-rec__patient-info">
				${pi.name ? `<span class="ai-rec__pi-tag">${esc(pi.name)}</span>` : ""}
				${pi.age ? `<span class="ai-rec__pi-tag">${esc(pi.age)}</span>` : ""}
				${pi.sex ? `<span class="ai-rec__pi-tag">${esc(pi.sex)}</span>` : ""}
				${pi.allergies ? `<span class="ai-rec__pi-tag ai-rec__pi-tag--warn">${__("Allergies")}: ${esc(pi.allergies)}</span>` : ""}
			</div>` : "";

		$b.html(`
			<div class="ai-rec">
				${patientInfoHtml}
				<div class="ai-rec__header">
					<span class="ai-rec__complaint">${esc(rec.chief_complaint)}</span>
					<span class="ai-badge ${urgClass}">${(rec.urgency || "").toUpperCase()}</span>
				</div>
				<p class="ai-rec__summary">${esc(rec.summary)}</p>

				<div class="ai-rec__section">
					<div class="ai-rec__label">${__("Assessment")}</div>
					<ul>${bulletList(rec.possible_assessment)}</ul>
				</div>

				<div class="ai-rec__section">
					<div class="ai-rec__label">${__("Suggested Lab Tests")}</div>
					<div class="ai-rec__checklist">${checkList(rec.suggested_lab_tests, "tests")}</div>
				</div>

				<div class="ai-rec__section">
					<div class="ai-rec__label">${__("Suggested Medications")}</div>
					<div class="ai-rec__checklist">${checkList(rec.suggested_medications, "meds")}</div>
				</div>

				<div class="ai-rec__section">
					<div class="ai-rec__label">${__("Follow-up Questions")}</div>
					<ul>${bulletList(rec.recommended_follow_up_questions)}</ul>
				</div>

				<div class="ai-rec__section">
					<div class="ai-rec__label">${__("Next Steps")}</div>
					<ul>${bulletList(rec.suggested_next_steps)}</ul>
				</div>

				${(rec.red_flags && rec.red_flags.length) ? `
				<div class="ai-rec__section ai-rec__flags">
					<div class="ai-rec__label">${__("Red Flags")}</div>
					<ul>${bulletList(rec.red_flags)}</ul>
				</div>` : ""}

				<div class="ai-rec__section ai-rec__spanish">
					<div class="ai-rec__label">${__("Patient Summary (Spanish)")}</div>
					<p>${esc(rec.patient_facing_spanish_summary)}</p>
				</div>

				<div class="ai-rec__disclaimer">${esc(rec.safety_disclaimer)}</div>
			</div>
		`);

		// Show action buttons
		this.$panel.find(".ai-panel__actions").show();
	}

	_getSelectedItems(group) {
		const items = [];
		this.$panel.find(`input[data-group="${group}"]:checked`).each(function () {
			items.push($(this).val());
		});
		return items;
	}

	populateEncounter() {
		const rec = this.lastRecommendation;
		if (!rec) {
			frappe.show_alert({ message: __("No recommendations yet"), indicator: "orange" });
			return;
		}

		const frm = this.frm;

		// Set AI custom fields on the form
		frm.set_value("ai_chief_complaint", rec.chief_complaint || "");
		frm.set_value("ai_summary", rec.summary || "");
		frm.set_value("ai_suggested_tests", this._getSelectedItems("tests").join("\n"));
		frm.set_value("ai_suggested_medications", this._getSelectedItems("meds").join("\n"));
		frm.set_value("ai_red_flags", (rec.red_flags || []).join("\n"));
		frm.set_value("ai_followup_questions", (rec.recommended_follow_up_questions || []).join("\n"));
		frm.set_value("ai_urgency", (rec.urgency || "").charAt(0).toUpperCase() + (rec.urgency || "").slice(1));

		// Also populate encounter_comment with summary
		if (!frm.doc.encounter_comment) {
			frm.set_value("encounter_comment", rec.summary || "");
		}

		frm.dirty();
		frappe.show_alert({ message: __("AI data populated into encounter fields"), indicator: "green" });
	}

	openPrescriptionModal() {
		const rec = this.lastRecommendation;
		if (!rec) {
			frappe.show_alert({ message: __("No recommendations yet"), indicator: "orange" });
			return;
		}

		const selectedTests = this._getSelectedItems("tests");
		const selectedMeds = this._getSelectedItems("meds");
		const pi = rec.patient_info || {};
		const frm = this.frm;
		const visitId = this.visitId;

		const d = new frappe.ui.Dialog({
			title: __("Prepare Prescription Summary"),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "patient_summary_html",
					options: `
						<div style="margin-bottom:16px;">
							<h5 style="margin:0 0 8px; font-size:14px; font-weight:600; color:#1f272e;">${__("Patient Information")}</h5>
							<div style="display:flex; gap:8px; flex-wrap:wrap;">
								${pi.name ? `<span class="indicator-pill whitespace-nowrap blue">${frappe.utils.escape_html(pi.name)}</span>` : ""}
								${pi.age ? `<span class="indicator-pill whitespace-nowrap gray">${__("Age")}: ${frappe.utils.escape_html(pi.age)}</span>` : ""}
								${pi.sex ? `<span class="indicator-pill whitespace-nowrap gray">${frappe.utils.escape_html(pi.sex)}</span>` : ""}
								${frm.doc.patient_name ? `<span class="indicator-pill whitespace-nowrap green">${frappe.utils.escape_html(frm.doc.patient_name)}</span>` : ""}
							</div>
							${pi.allergies ? `<div style="margin-top:8px; padding:8px 12px; background:#fef2f2; border:1px solid #fecaca; border-radius:6px; font-size:12px; color:#dc2626;"><strong>${__("Allergies")}:</strong> ${frappe.utils.escape_html(pi.allergies)}</div>` : ""}
						</div>
						<hr style="border:none; border-top:1px solid #eaeaea; margin:12px 0;">
					`,
				},
				{
					fieldtype: "HTML",
					fieldname: "chief_complaint_html",
					options: `
						<div style="margin-bottom:12px;">
							<h5 style="margin:0 0 4px; font-size:13px; font-weight:600; color:#374151;">${__("Chief Complaint")}</h5>
							<p style="margin:0; font-size:13px; color:#6b7280;">${frappe.utils.escape_html(rec.chief_complaint || "")}</p>
						</div>
					`,
				},
				{
					fieldtype: "HTML",
					fieldname: "summary_html",
					options: `
						<div style="margin-bottom:12px;">
							<h5 style="margin:0 0 4px; font-size:13px; font-weight:600; color:#374151;">${__("Summary")}</h5>
							<p style="margin:0; font-size:12px; color:#6b7280; line-height:1.5;">${frappe.utils.escape_html(rec.summary || "")}</p>
						</div>
					`,
				},
				{
					fieldtype: "HTML",
					fieldname: "tests_html",
					options: `
						<div style="margin-bottom:12px;">
							<h5 style="margin:0 0 6px; font-size:13px; font-weight:600; color:#374151;">${__("Selected Lab Tests")} (${selectedTests.length})</h5>
							${selectedTests.length
								? `<ul style="margin:0; padding-left:18px; font-size:12px; color:#374151;">${selectedTests.map(t => `<li style="margin-bottom:3px;">${frappe.utils.escape_html(t)}</li>`).join("")}</ul>`
								: `<p style="margin:0; font-size:12px; color:#9ca3af; font-style:italic;">${__("No tests selected")}</p>`
							}
						</div>
					`,
				},
				{
					fieldtype: "HTML",
					fieldname: "meds_html",
					options: `
						<div style="margin-bottom:12px;">
							<h5 style="margin:0 0 6px; font-size:13px; font-weight:600; color:#374151;">${__("Selected Medications")} (${selectedMeds.length})</h5>
							${selectedMeds.length
								? `<ul style="margin:0; padding-left:18px; font-size:12px; color:#374151;">${selectedMeds.map(m => `<li style="margin-bottom:3px;">${frappe.utils.escape_html(m)}</li>`).join("")}</ul>`
								: `<p style="margin:0; font-size:12px; color:#9ca3af; font-style:italic;">${__("No medications selected")}</p>`
							}
						</div>
					`,
				},
				{
					fieldtype: "HTML",
					fieldname: "red_flags_html",
					options: (rec.red_flags && rec.red_flags.length) ? `
						<div style="margin-bottom:12px; padding:10px 12px; background:#fef2f2; border:1px solid #fecaca; border-radius:8px;">
							<h5 style="margin:0 0 6px; font-size:13px; font-weight:600; color:#dc2626;">${__("Red Flags")}</h5>
							<ul style="margin:0; padding-left:18px; font-size:12px; color:#991b1b;">${rec.red_flags.map(f => `<li style="margin-bottom:2px;">${frappe.utils.escape_html(f)}</li>`).join("")}</ul>
						</div>
					` : "",
				},
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Text",
					fieldname: "doctor_notes",
					label: __("Doctor's Notes"),
					description: __("Add your own observations, modifications, or instructions"),
				},
				{
					fieldtype: "HTML",
					fieldname: "disclaimer_html",
					options: `
						<div style="margin-top:8px; padding:8px 12px; background:#fffbeb; border:1px solid #fde68a; border-radius:6px; font-size:11px; color:#b45309; line-height:1.5;">
							${frappe.utils.escape_html(rec.safety_disclaimer || "AI-generated — must be reviewed by a licensed clinician.")}
						</div>
					`,
				},
			],
			primary_action_label: __("Save to Encounter"),
			primary_action: (values) => {
				// Push to encounter fields
				this.populateEncounter();
				if (values.doctor_notes) {
					frm.set_value("ai_doctor_notes", values.doctor_notes);
				}
				frm.dirty();

				// Also save via API to persist
				frappe.xcall("remedisys.api.medical_agent.populate_encounter", {
					encounter_name: frm.doc.name,
					visit_id: visitId,
					doctor_notes: values.doctor_notes || "",
					selected_tests: selectedTests,
					selected_meds: selectedMeds,
				}).then(() => {
					frappe.show_alert({ message: __("Encounter updated with AI data"), indicator: "green" });
					frm.reload_doc();
				}).catch((err) => {
					frappe.show_alert({ message: __("Error saving: ") + (err.message || err), indicator: "red" });
				});

				d.hide();
			},
		});
		d.show();
	}

	_createRecorder(stream) {
		const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
		const rec = new MediaRecorder(stream, { mimeType });
		const chunks = [];
		rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
		rec.onstop = () => { if (chunks.length > 0) this.uploadChunk(new Blob(chunks, { type: mimeType })); };
		return rec;
	}

	async startRecording() {
		try {
			this.setStatus(__("Requesting microphone..."), "processing");
			this.mediaStream = await navigator.mediaDevices.getUserMedia({
				audio: {
					echoCancellation: true,
					noiseSuppression: true,
					autoGainControl: true,
					channelCount: 1,
					sampleRate: 16000,
				},
			});
			this.seqNum = 0;
			this.isRecording = true;
			this.mediaRecorder = this._createRecorder(this.mediaStream);
			this.mediaRecorder.start();
			this.setStatus(__("Recording in progress"), "recording");
			this.$panel.find(".ai-panel__mic-btn--record").prop("disabled", true);
			this.$panel.find(".ai-panel__mic-btn--stop").prop("disabled", false);
			this.$panel.addClass("ai-panel--recording");
			this.chunkInterval = setInterval(() => {
				if (!this.isRecording || !this.mediaStream) return;
				if (this.mediaRecorder && this.mediaRecorder.state === "recording") this.mediaRecorder.stop();
				this.mediaRecorder = this._createRecorder(this.mediaStream);
				this.mediaRecorder.start();
			}, 10000);
		} catch (err) {
			console.error(err);
			this.setStatus(`${__("Microphone error")}: ${err.message}`, "error");
		}
	}

	stopRecording() {
		try {
			this.isRecording = false;
			this.$panel.removeClass("ai-panel--recording");
			if (this.chunkInterval) { clearInterval(this.chunkInterval); this.chunkInterval = null; }
			if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") this.mediaRecorder.stop();
			if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
			if (this.processingCount === 0) this.setStatus(__("Recording stopped"), "stopped");
			this.$panel.find(".ai-panel__mic-btn--record").prop("disabled", false);
			this.$panel.find(".ai-panel__mic-btn--stop").prop("disabled", true);
		} catch (err) { console.error(err); }
	}

	async uploadChunk(blob) {
		this.processingCount++;
		this.seqNum++;
		const seq = this.seqNum;
		this.setStatus(`${__("Processing chunk")} #${seq}...`, "processing");
		try {
			const form = new FormData();
			form.append("visit_id", this.visitId);
			form.append("sequence_number", String(seq));
			form.append("language_hint", this.$panel.find(".ai-panel__lang-select").val() || "");
			form.append("audio_chunk", blob, `chunk-${seq}.webm`);
			const resp = await fetch("/api/method/remedisys.api.medical_agent.process_audio_chunk", { method: "POST", body: form, credentials: "include", headers: { "X-Frappe-CSRF-Token": frappe.csrf_token } });
			const json = await resp.json();
			const p = json.message || json;
			if (!p.ok) throw new Error(p._server_messages || p.exc || "Failed");
			this.updateTranscriptEn(p.full_transcript_en);
			this.updateTranscriptEs(p.full_transcript_es);
			this.updateRecommendation(p.recommendation);

			// Auto-save to encounter document
			this._autoSave(p.full_transcript_en, p.full_transcript_es, p.recommendation);

			this.setStatus(this.isRecording ? `${__("Recording")} (${seq})` : `${__("Completed")} - ${seq} ${__("chunks")}`, this.isRecording ? "recording" : "done");
		} catch (err) {
			console.error(err);
			this.setStatus(`${__("Error")}: ${err.message}`, "error");
		} finally { this.processingCount--; }
	}

	async resetSession() {
		this.stopRecording();
		try { await frappe.xcall("remedisys.api.medical_agent.clear_visit_state", { visit_id: this.visitId }); } catch (_) {}
		this.seqNum = 0;
		this.lastRecommendation = null;
		this.updateTranscriptEn("");
		this.updateTranscriptEs("");
		this.updateRecommendation(null);
		this.setStatus(__("Session reset"), "stopped");
	}
}
