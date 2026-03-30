/**
 * Remedisys — Medical AI Assistant
 * Adds an "AI Assistant" button to Patient Encounter that opens
 * a right-side panel with live transcription, Spanish translation,
 * and clinical recommendations.
 */

frappe.ui.form.on("Patient Encounter", {
	refresh(frm) {
		frm.add_custom_button(
			__("🤖 AI Assistant"),
			() => toggleAIPanel(frm),
		);
		frm.change_custom_button_type(__("🤖 AI Assistant"), null, "primary");
	},
});

/* -----------------------------------------------------------------------
 * Right-side panel
 * ----------------------------------------------------------------------- */

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

		this.render();
	}

	render() {
		// Create overlay + panel
		this.$overlay = $('<div class="ai-panel-overlay"></div>').appendTo("body");
		this.$panel = $(`
			<div class="ai-side-panel">
				<div class="ai-sp-header">
					<div class="ai-sp-header-left">
						<span class="ai-sp-icon">🤖</span>
						<h4>${__("AI Assistant")}</h4>
					</div>
					<button class="btn btn-sm ai-sp-close" title="${__("Close")}">✕</button>
				</div>

				<div class="ai-sp-controls">
					<div class="ai-sp-visit-id">
						<small class="text-muted">${__("Visit")}</small>
						<span>${this.visitId}</span>
					</div>
					<div class="ai-sp-buttons">
						<button class="btn btn-primary btn-xs ai-btn-start">🎙️ ${__("Start")}</button>
						<button class="btn btn-danger btn-xs ai-btn-stop" disabled>⏹️ ${__("Stop")}</button>
						<button class="btn btn-default btn-xs ai-btn-reset">🔄</button>
					</div>
					<div class="ai-sp-lang">
						<select class="form-control input-xs ai-lang-select">
							<option value="">${__("Auto")}</option>
							<option value="en">EN</option>
							<option value="es">ES</option>
						</select>
					</div>
				</div>

				<div class="ai-sp-status">
					<span class="indicator-pill blue"></span>
					${__("Ready — press Start")}
				</div>

				<div class="ai-sp-body">
					<div class="ai-sp-section ai-sp-transcript-en">
						<div class="ai-sp-section-title">📝 ${__("Patient Problem")}</div>
						<div class="ai-sp-section-body text-muted">${__("Listening for patient…")}</div>
					</div>

					<div class="ai-sp-section ai-sp-transcript-es">
						<div class="ai-sp-section-title">🇪🇸 ${__("Spanish Translation")}</div>
						<div class="ai-sp-section-body text-muted">${__("Waiting…")}</div>
					</div>

					<div class="ai-sp-section ai-sp-recommendation">
						<div class="ai-sp-section-title">💡 ${__("Suggestions for Doctor")}</div>
						<div class="ai-sp-section-body text-muted">${__("No suggestions yet.")}</div>
					</div>
				</div>
			</div>
		`).appendTo("body");

		// Animate in
		requestAnimationFrame(() => {
			this.$panel.addClass("ai-sp-open");
			this.$overlay.addClass("ai-overlay-show");
		});

		// Events
		this.$panel.find(".ai-sp-close").on("click", () => this.destroy());
		this.$overlay.on("click", () => this.destroy());
		this.$panel.find(".ai-btn-start").on("click", () => this.startRecording());
		this.$panel.find(".ai-btn-stop").on("click", () => this.stopRecording());
		this.$panel.find(".ai-btn-reset").on("click", () => this.resetSession());
	}

	destroy() {
		this.stopRecording();
		this.$panel.removeClass("ai-sp-open");
		this.$overlay.removeClass("ai-overlay-show");
		setTimeout(() => {
			this.$panel.remove();
			this.$overlay.remove();
		}, 300);
		aiPanelInstance = null;
	}

	setStatus(text, type = "blue") {
		this.$panel.find(".ai-sp-status").html(
			`<span class="indicator-pill ${type}"></span> ${text}`
		);
	}

	updateTranscriptEn(text) {
		this.$panel.find(".ai-sp-transcript-en .ai-sp-section-body").html(
			frappe.utils.escape_html(text) || `<span class="text-muted">${__("Listening for patient…")}</span>`
		);
	}

	updateTranscriptEs(text) {
		this.$panel.find(".ai-sp-transcript-es .ai-sp-section-body").html(
			frappe.utils.escape_html(text) || `<span class="text-muted">${__("Waiting…")}</span>`
		);
	}

	updateRecommendation(rec) {
		const $body = this.$panel.find(".ai-sp-recommendation .ai-sp-section-body");

		if (!rec || !rec.chief_complaint) {
			$body.html(`<span class="text-muted">${__("No suggestions yet.")}</span>`);
			return;
		}

		const urgColors = { low: "#38a169", moderate: "#dd6b20", high: "#e53e3e", emergent: "#9b2c2c" };
		const urgColor = urgColors[rec.urgency] || "#718096";

		const listHtml = (items) =>
			(items || []).map(i => `<li>${frappe.utils.escape_html(i)}</li>`).join("")
			|| `<li class="text-muted">${__("None")}</li>`;

		$body.html(`
			<div class="ai-rec-header">
				<span class="ai-rec-complaint">${frappe.utils.escape_html(rec.chief_complaint)}</span>
				<span class="ai-badge" style="background:${urgColor};">${(rec.urgency || "").toUpperCase()}</span>
			</div>

			<p class="ai-rec-summary">${frappe.utils.escape_html(rec.summary)}</p>

			<div class="ai-rec-block">
				<strong>🔍 ${__("Assessment")}</strong>
				<ul>${listHtml(rec.possible_assessment)}</ul>
			</div>

			<div class="ai-rec-block">
				<strong>❓ ${__("Ask the Patient")}</strong>
				<ul>${listHtml(rec.recommended_follow_up_questions)}</ul>
			</div>

			<div class="ai-rec-block">
				<strong>➡️ ${__("Next Steps")}</strong>
				<ul>${listHtml(rec.suggested_next_steps)}</ul>
			</div>

			${(rec.red_flags && rec.red_flags.length) ? `
			<div class="ai-rec-block ai-rec-flags">
				<strong>🚩 ${__("Red Flags")}</strong>
				<ul>${listHtml(rec.red_flags)}</ul>
			</div>` : ""}

			<div class="ai-rec-block ai-rec-es-summary">
				<strong>🇪🇸 ${__("For Patient (Spanish)")}</strong>
				<p>${frappe.utils.escape_html(rec.patient_facing_spanish_summary)}</p>
			</div>

			<div class="ai-rec-disclaimer">
				⚠️ ${frappe.utils.escape_html(rec.safety_disclaimer)}
			</div>
		`);
	}

	// ---- Recording ----
	_createRecorder(stream) {
		const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
			? "audio/webm;codecs=opus"
			: "audio/webm";

		const rec = new MediaRecorder(stream, { mimeType });
		const chunks = [];

		rec.ondataavailable = (e) => {
			if (e.data && e.data.size > 0) chunks.push(e.data);
		};

		rec.onstop = () => {
			if (chunks.length > 0) {
				const blob = new Blob(chunks, { type: mimeType });
				this.uploadChunk(blob);
			}
		};

		return rec;
	}

	async startRecording() {
		try {
			this.setStatus(__("Requesting microphone…"), "blue");
			this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
			this.seqNum = 0;
			this.isRecording = true;

			this.mediaRecorder = this._createRecorder(this.mediaStream);
			this.mediaRecorder.start();

			this.setStatus(
				`<span class="ai-pulse"></span> ${__("Listening…")}`,
				"green"
			);
			this.$panel.find(".ai-btn-start").prop("disabled", true);
			this.$panel.find(".ai-btn-stop").prop("disabled", false);

			this.chunkInterval = setInterval(() => {
				if (!this.isRecording || !this.mediaStream) return;
				if (this.mediaRecorder && this.mediaRecorder.state === "recording") {
					this.mediaRecorder.stop();
				}
				this.mediaRecorder = this._createRecorder(this.mediaStream);
				this.mediaRecorder.start();
			}, 10000);
		} catch (err) {
			console.error(err);
			this.setStatus(`${__("Mic error")}: ${err.message}`, "red");
		}
	}

	stopRecording() {
		try {
			this.isRecording = false;
			if (this.chunkInterval) {
				clearInterval(this.chunkInterval);
				this.chunkInterval = null;
			}
			if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
				this.mediaRecorder.stop();
			}
			if (this.mediaStream) {
				this.mediaStream.getTracks().forEach(t => t.stop());
				this.mediaStream = null;
			}
			if (this.processingCount === 0) {
				this.setStatus(__("Stopped"), "orange");
			}
			this.$panel.find(".ai-btn-start").prop("disabled", false);
			this.$panel.find(".ai-btn-stop").prop("disabled", true);
		} catch (err) {
			console.error(err);
		}
	}

	async uploadChunk(blob) {
		this.processingCount++;
		this.seqNum++;
		const currentSeq = this.seqNum;

		this.setStatus(`${__("Processing chunk")} #${currentSeq}…`, "blue");

		try {
			const langHint = this.$panel.find(".ai-lang-select").val() || "";
			const form = new FormData();
			form.append("visit_id", this.visitId);
			form.append("sequence_number", String(currentSeq));
			form.append("language_hint", langHint);
			form.append("audio_chunk", blob, `chunk-${currentSeq}.webm`);

			const resp = await fetch(
				"/api/method/remedisys.api.medical_agent.process_audio_chunk",
				{
					method: "POST",
					body: form,
					credentials: "include",
					headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
				}
			);

			const json = await resp.json();
			const payload = json.message || json;

			if (!payload.ok) {
				throw new Error(payload._server_messages || payload.exc || "Failed");
			}

			this.updateTranscriptEn(payload.full_transcript_en);
			this.updateTranscriptEs(payload.full_transcript_es);
			this.updateRecommendation(payload.recommendation);

			if (this.isRecording) {
				this.setStatus(
					`<span class="ai-pulse"></span> ${__("Listening…")} (${currentSeq} ${__("chunks")})`,
					"green"
				);
			} else {
				this.setStatus(`${__("Done")} — ${currentSeq} ${__("chunks processed")}`, "green");
			}
		} catch (err) {
			console.error(err);
			this.setStatus(`${__("Error")}: ${err.message}`, "red");
		} finally {
			this.processingCount--;
		}
	}

	async resetSession() {
		this.stopRecording();
		try {
			await frappe.xcall(
				"remedisys.api.medical_agent.clear_visit_state",
				{ visit_id: this.visitId }
			);
		} catch (_) {}
		this.seqNum = 0;
		this.updateTranscriptEn("");
		this.updateTranscriptEs("");
		this.updateRecommendation(null);
		this.setStatus(__("Session reset"), "orange");
	}
}
