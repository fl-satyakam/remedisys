# Copyright (c) 2026, Remedisys and contributors
# For license information, please see license.txt
"""Seed the AI Module Config Single with the default 6 recommendation modules.

Runs on migrate. Idempotent: if a module with the given key already exists,
it is left alone so admin edits are preserved.
"""

import frappe


DEFAULT_SYSTEM_PROMPT = (
	"You are a clinical decision-support assistant for licensed physicians. "
	"You are not the final decision-maker. "
	"Return only valid JSON matching the provided schema."
)

DEFAULT_URGENCY_SCALE = (
	"Use one of: low, moderate, high, emergent. "
	"'emergent' means the patient needs immediate attention."
)

DEFAULT_SAFETY_DISCLAIMER = (
	"AI-generated decision support must be reviewed by a licensed clinician."
)

DEFAULT_MODULES = [
	{
		"module_key": "chief_complaint",
		"display_title": "Chief Complaint",
		"output_type": "paragraph",
		"display_order": 10,
		"prompt_fragment": "Single-line chief complaint in the patient's words.",
		"empty_state_text": "\u2014",
	},
	{
		"module_key": "summary",
		"display_title": "Summary",
		"output_type": "paragraph",
		"display_order": 20,
		"prompt_fragment": (
			"2-3 sentence clinical summary of what has been discussed so far."
		),
		"empty_state_text": "Will populate as the conversation progresses\u2026",
	},
	{
		"module_key": "possible_assessment",
		"display_title": "Possible Assessment",
		"output_type": "chip_list",
		"display_order": 30,
		"prompt_fragment": (
			"Up to 4 differential diagnoses ranked by likelihood."
		),
		"empty_state_text": "\u2014",
	},
	{
		"module_key": "suggested_lab_tests",
		"display_title": "Suggested Lab Tests",
		"output_type": "chip_list",
		"display_order": 40,
		"prompt_fragment": (
			"0-6 relevant diagnostic tests. Use specific names like 'CBC', "
			"'Lipid Panel', 'HbA1c', 'Chest X-ray'."
		),
		"empty_state_text": "\u2014",
	},
	{
		"module_key": "suggested_medications",
		"display_title": "Suggested Medications",
		"output_type": "chip_list",
		"display_order": 50,
		"prompt_fragment": (
			"0-6 candidate medications with dose hints like "
			"'Amoxicillin 500mg TID x 7 days' or 'Ibuprofen 400mg PRN'."
		),
		"empty_state_text": "\u2014",
	},
	{
		"module_key": "recommended_follow_up_questions",
		"display_title": "Follow-up Questions",
		"output_type": "chip_list",
		"display_order": 60,
		"prompt_fragment": (
			"Up to 5 questions the doctor should still ask to narrow the diagnosis."
		),
		"empty_state_text": "\u2014",
	},
	{
		"module_key": "red_flags",
		"display_title": "Red Flags",
		"output_type": "bullet_list",
		"display_order": 70,
		"card_color": "#ef4444",
		"prompt_fragment": (
			"Urgent red flags that warrant immediate attention; empty array if none."
		),
		"empty_state_text": "\u2014",
	},
]


def execute():
	doc = frappe.get_single("AI Module Config")

	if not doc.recommendation_system_prompt:
		doc.recommendation_system_prompt = DEFAULT_SYSTEM_PROMPT
	if not doc.urgency_scale:
		doc.urgency_scale = DEFAULT_URGENCY_SCALE
	if not doc.safety_disclaimer:
		doc.safety_disclaimer = DEFAULT_SAFETY_DISCLAIMER

	existing_keys = {row.module_key for row in (doc.modules or [])}
	for m in DEFAULT_MODULES:
		if m["module_key"] in existing_keys:
			continue
		row = doc.append("modules", {})
		row.module_key = m["module_key"]
		row.display_title = m["display_title"]
		row.enabled = 1
		row.display_order = m["display_order"]
		row.output_type = m["output_type"]
		row.prompt_fragment = m["prompt_fragment"]
		row.empty_state_text = m.get("empty_state_text") or "\u2014"
		if m.get("card_color"):
			row.card_color = m["card_color"]

	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.save()
	frappe.db.commit()
