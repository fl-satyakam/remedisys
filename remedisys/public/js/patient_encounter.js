/**
 * Remedisys — Medical AI Assistant
 * Injects an "AI Assistant" button into the Patient Encounter form.
 * Clicking it opens a dialog that records mic audio in 10-second chunks,
 * sends each chunk to the backend for transcription, Spanish translation,
 * and clinical recommendation.
 */

frappe.ui.form.on("Patient Encounter", {
	refresh(frm) {
		// Add a primary "AI Assistant" button at the top of the form
		frm.add_custom_button(
			__("🤖 AI Assistant"),
			() => open_ai_assistant_dialog(frm),
		);

		// Make it stand out
		frm.change_custom_button_type(__("🤖 AI Assistant"), null, "primary");
	},
});

/* -----------------------------------------------------------------------
 * Dialog
 * ----------------------------------------------------------------------- */

function open_ai_assistant_dialog(frm) {
	const visitId = frm.doc.name || frappe.utils.get_random(10);

	const d = new frappe.ui.Dialog({
		title: __("🤖 Medical AI Assistant"),
		size: "extra-large",
		minimizable: true,
		fields: build_dialog_fields(visitId),
		on_page_show: () => {
			d.$wrapper.find(".modal-dialog").addClass("ai-assistant-dialog");
		},
	});

	// ---- State ----
	let mediaRecorder = null;
	let mediaStream = null;
	let chunkInterval = null;
	let seqNum = 0;
	let isRecording = false;
	let processingCount = 0;

	// ---- DOM refs ----
	const $status = () => d.fields_dict.status_html.$wrapper;
	const $transcriptEn = () => d.fields_dict.transcript_en_html.$wrapper;
	const $transcriptEs = () => d.fields_dict.transcript_es_html.$wrapper;
	const $recommendation = () => d.fields_dict.recommendation_html.$wrapper;

	// ---- Helpers ----
	function setStatus(text, type = "blue") {
		$status().html(
			`<div class="ai-status ai-status--${type}">
				<span class="indicator-pill ${type}"></span> ${text}
			</div>`
		);
	}

	function renderTranscript(selector, label, text) {
		selector().html(
			`<div class="ai-panel">
				<h5 class="ai-panel__title">${label}</h5>
				<div class="ai-panel__body">${frappe.utils.escape_html(text) || '<span class="text-muted">Waiting for audio…</span>'}</div>
			</div>`
		);
	}

	function renderRecommendation(rec) {
		if (!rec || !rec.chief_complaint) {
			$recommendation().html(
				`<div class="ai-panel">
					<h5 class="ai-panel__title">${__("Recommendation Draft")}</h5>
					<div class="ai-panel__body text-muted">${__("No recommendation yet.")}</div>
				</div>`
			);
			return;
		}

		const urgencyColors = {
			low: "green",
			moderate: "orange",
			high: "red",
			emergent: "darkred",
		};
		const urgColor = urgencyColors[rec.urgency] || "gray";

		const listHtml = (items) =>
			(items || [])
				.map((i) => `<li>${frappe.utils.escape_html(i)}</li>`)
				.join("") || "<li class='text-muted'>None</li>";

		$recommendation().html(`
			<div class="ai-panel">
				<h5 class="ai-panel__title">${__("Recommendation Draft")}</h5>
				<div class="ai-panel__body">
					<div class="ai-rec-grid">
						<div class="ai-rec-item">
							<strong>${__("Chief Complaint")}:</strong>
							<span>${frappe.utils.escape_html(rec.chief_complaint)}</span>
						</div>
						<div class="ai-rec-item">
							<strong>${__("Urgency")}:</strong>
							<span class="ai-badge" style="background:${urgColor};">
								${(rec.urgency || "").toUpperCase()}
							</span>
						</div>
					</div>

					<div class="ai-rec-section">
						<strong>${__("Summary")}</strong>
						<p>${frappe.utils.escape_html(rec.summary)}</p>
					</div>

					<div class="ai-rec-section">
						<strong>${__("Possible Assessment")}</strong>
						<ul>${listHtml(rec.possible_assessment)}</ul>
					</div>

					<div class="ai-rec-section">
						<strong>${__("Follow-up Questions")}</strong>
						<ul>${listHtml(rec.recommended_follow_up_questions)}</ul>
					</div>

					<div class="ai-rec-section">
						<strong>${__("Suggested Next Steps")}</strong>
						<ul>${listHtml(rec.suggested_next_steps)}</ul>
					</div>

					<div class="ai-rec-section ai-rec-section--flags">
						<strong>🚩 ${__("Red Flags")}</strong>
						<ul>${listHtml(rec.red_flags)}</ul>
					</div>

					<div class="ai-rec-section">
						<strong>🇪🇸 ${__("Patient-Facing Spanish Summary")}</strong>
						<p>${frappe.utils.escape_html(rec.patient_facing_spanish_summary)}</p>
					</div>

					<div class="ai-disclaimer">
						⚠️ ${frappe.utils.escape_html(rec.safety_disclaimer)}
					</div>
				</div>
			</div>
		`);
	}

	// ---- Recording ----
	// We stop/restart the recorder every 10 seconds so each chunk
	// is a self-contained webm file with proper headers.
	function _createRecorder(stream) {
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
				uploadChunk(blob);
			}
		};

		return rec;
	}

	async function startRecording() {
		try {
			setStatus(__("Requesting microphone…"), "blue");

			mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

			seqNum = 0;
			isRecording = true;

			// Start the first recorder
			mediaRecorder = _createRecorder(mediaStream);
			mediaRecorder.start();

			setStatus(
				`<span class="ai-pulse"></span> ${__("Listening… (chunks every 10 s)")}`,
				"green"
			);
			d.fields_dict.btn_start_html.$wrapper.find("button").prop("disabled", true);
			d.fields_dict.btn_stop_html.$wrapper.find("button").prop("disabled", false);

			// Every 10 seconds, stop current recorder and start a new one
			chunkInterval = setInterval(() => {
				if (!isRecording || !mediaStream) return;

				// Stop current — triggers onstop which uploads the chunk
				if (mediaRecorder && mediaRecorder.state === "recording") {
					mediaRecorder.stop();
				}

				// Start a fresh recorder for the next 10 seconds
				mediaRecorder = _createRecorder(mediaStream);
				mediaRecorder.start();
			}, 10000);
		} catch (err) {
			console.error(err);
			setStatus(`${__("Mic error")}: ${err.message || err}`, "red");
		}
	}

	function stopRecording() {
		try {
			isRecording = false;

			if (chunkInterval) {
				clearInterval(chunkInterval);
				chunkInterval = null;
			}

			if (mediaRecorder && mediaRecorder.state !== "inactive") {
				mediaRecorder.stop(); // will trigger final upload
			}

			if (mediaStream) {
				mediaStream.getTracks().forEach((t) => t.stop());
				mediaStream = null;
			}

			if (processingCount === 0) {
				setStatus(__("Stopped"), "orange");
			}
			d.fields_dict.btn_start_html.$wrapper.find("button").prop("disabled", false);
			d.fields_dict.btn_stop_html.$wrapper.find("button").prop("disabled", true);
		} catch (err) {
			console.error(err);
		}
	}

	async function uploadChunk(blob) {
		processingCount++;
		seqNum++;
		const currentSeq = seqNum;

		setStatus(
			`${__("Processing chunk")} #${currentSeq}…`,
			"blue"
		);

		try {
			const form = new FormData();
			form.append("visit_id", visitId);
			form.append("sequence_number", String(currentSeq));
			form.append("language_hint", d.get_value("language_hint") || "");
			form.append("audio_chunk", blob, `chunk-${currentSeq}.webm`);

			const resp = await fetch(
				"/api/method/remedisys.api.medical_agent.process_audio_chunk",
				{
					method: "POST",
					body: form,
					credentials: "include",
					headers: {
						"X-Frappe-CSRF-Token": frappe.csrf_token,
					},
				}
			);

			const json = await resp.json();
			const payload = json.message || json;

			if (!payload.ok) {
				throw new Error(
					payload._server_messages || payload.exc || "Chunk processing failed"
				);
			}

			renderTranscript($transcriptEn, __("Transcript (English)"), payload.full_transcript_en);
			renderTranscript($transcriptEs, __("Spanish Translation"), payload.full_transcript_es);
			renderRecommendation(payload.recommendation);

			if (isRecording) {
				setStatus(
					`<span class="ai-pulse"></span> ${__("Listening… chunk")} #${currentSeq} ${__("done")}`,
					"green"
				);
			} else {
				setStatus(`${__("Chunk")} #${currentSeq} ${__("processed")}`, "green");
			}
		} catch (err) {
			console.error(err);
			setStatus(`${__("Error")}: ${err.message || err}`, "red");
		} finally {
			processingCount--;
		}
	}

	async function resetSession() {
		stopRecording();
		try {
			await frappe.xcall(
				"remedisys.api.medical_agent.clear_visit_state",
				{ visit_id: visitId }
			);
		} catch (_) {
			// ignore
		}
		seqNum = 0;
		renderTranscript($transcriptEn, __("Transcript (English)"), "");
		renderTranscript($transcriptEs, __("Spanish Translation"), "");
		renderRecommendation(null);
		setStatus(__("Session reset"), "orange");
	}

	// ---- Wire buttons after dialog is shown ----
	d.show();

	// Initial renders
	setStatus(__("Ready — press Start Listening"), "blue");
	renderTranscript($transcriptEn, __("Transcript (English)"), "");
	renderTranscript($transcriptEs, __("Spanish Translation"), "");
	renderRecommendation(null);

	// Button bindings
	d.fields_dict.btn_start_html.$wrapper
		.find("button")
		.on("click", () => startRecording());

	d.fields_dict.btn_stop_html.$wrapper
		.find("button")
		.prop("disabled", true)
		.on("click", () => stopRecording());

	d.fields_dict.btn_reset_html.$wrapper
		.find("button")
		.on("click", () => resetSession());

	// Clean up on close
	d.onhide = () => stopRecording();
}

/* -----------------------------------------------------------------------
 * Dialog field definitions
 * ----------------------------------------------------------------------- */

function build_dialog_fields(visitId) {
	return [
		// ---- Controls row ----
		{
			fieldtype: "Section Break",
			label: __("Controls"),
		},
		{
			fieldtype: "HTML",
			fieldname: "visit_id_html",
			options: `<div class="ai-field">
				<label class="control-label">${__("Visit ID")}</label>
				<div class="control-value">${visitId}</div>
			</div>`,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Select",
			fieldname: "language_hint",
			label: __("Language Hint"),
			options: "\nen\nes",
			default: "",
			description: __("Leave blank for auto-detect"),
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "HTML",
			fieldname: "btn_start_html",
			options: `<button class="btn btn-primary btn-sm btn-ai-start" id="ai-btn-start">
				🎙️ ${__("Start Listening")}
			</button>`,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "HTML",
			fieldname: "btn_stop_html",
			options: `<button class="btn btn-danger btn-sm btn-ai-stop" id="ai-btn-stop">
				⏹️ ${__("Stop")}
			</button>`,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "HTML",
			fieldname: "btn_reset_html",
			options: `<button class="btn btn-default btn-sm btn-ai-reset" id="ai-btn-reset">
				🔄 ${__("Reset")}
			</button>`,
		},

		// ---- Status ----
		{ fieldtype: "Section Break" },
		{
			fieldtype: "HTML",
			fieldname: "status_html",
			options: "",
		},

		// ---- Transcripts side by side ----
		{
			fieldtype: "Section Break",
			label: __("Transcripts"),
		},
		{
			fieldtype: "HTML",
			fieldname: "transcript_en_html",
			options: "",
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "HTML",
			fieldname: "transcript_es_html",
			options: "",
		},

		// ---- Recommendation ----
		{
			fieldtype: "Section Break",
			label: __("Clinical Recommendation"),
		},
		{
			fieldtype: "HTML",
			fieldname: "recommendation_html",
			options: "",
		},
	];
}
