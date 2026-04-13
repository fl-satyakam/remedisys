# Remedisys Architecture & Module Reference

## Table of Contents
1. [System Overview](#system-overview)
2. [Module 1: Healthcare (Marley Health)](#module-1-healthcare-marley-health)
3. [Module 2: Remedisys (AI Layer)](#module-2-remedisys-ai-layer)
4. [How They Connect](#how-they-connect)
5. [GPT Conversation Context & Product Vision](#gpt-conversation-context--product-vision)
6. [Development Guide](#development-guide)

---

## System Overview

Remedisys is a four-app Frappe stack for AI-powered healthcare management:

```
Layer 4:  REMEDISYS (v0.0.1)      — AI/ML layer: Whisper, GPT-4o, clinical recommendations
Layer 3:  HEALTHCARE / Marley     — 128 doctypes: patients, encounters, labs, procedures
Layer 2:  ERPNEXT (v16.13.2)      — ERP backbone: accounting, HR, inventory, billing
Layer 1:  FRAPPE FRAMEWORK (v16)  — Core: ORM, REST API, Redis, MariaDB, permissions, UI
```

**Key insight:** Healthcare (Marley) is a pure clinical ERP with ZERO AI. Remedisys is a sibling app that hooks into Healthcare's doctypes to add AI capabilities — it does NOT modify Healthcare's code.

---

## Module 1: Healthcare (Marley Health)

**Repository:** github.com/earthians/marley (formerly frappe/health)
**Version:** 16.0.7
**Publisher:** earthians Health Informatics Pvt. Ltd.
**License:** GNU GPL V3
**Dependency:** Requires ERPNext

### What It Is

A full-featured open-source Hospital Information System (HIS) built on Frappe and ERPNext. It provides structured doctypes for managing every aspect of clinical operations — from patient registration to discharge, lab testing to therapy plans, billing to insurance claims.

### All 128 Doctypes (Categorized)

#### Patient Management (12 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Patient` | Core patient record — demographics, contact, insurance, linked ERPNext customer |
| `Patient Relation` | Family/emergency contacts |
| `Patient Medical Record` | Consolidated timeline of all medical events |
| `Patient History Settings` | Configure which documents appear in patient history |
| `Patient History Standard Document Type` | Standard document types for history |
| `Patient History Custom Document Type` | Custom document types for history |
| `Patient Care Type` | Types of care (outpatient, inpatient, emergency) |
| `Patient Insurance Policy` | Insurance policy linked to a patient |
| `Patient Insurance Coverage` | Coverage details per policy |
| `Body Part` | Anatomical body parts reference |
| `Body Part Link` | Links body parts to procedures/conditions |
| `Complaint` | Standard complaint/symptom master list |

#### Patient Encounter / Consultation (5 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Patient Encounter` | **THE core clinical visit document** — doctor records symptoms, diagnosis, prescriptions, procedures. This is where Remedisys hooks its AI Assistant |
| `Patient Encounter Symptom` | Child table: symptoms recorded during encounter |
| `Patient Encounter Diagnosis` | Child table: diagnoses recorded during encounter |
| `Diagnosis` | Master list of diagnosis codes |
| `Clinical Note` | Free-text clinical notes |
| `Clinical Note Type` | Categories for clinical notes |

#### Appointments & Scheduling (7 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Patient Appointment` | Book patient visits with practitioners |
| `Appointment Type` | Types of appointments (follow-up, new, emergency) |
| `Appointment Type Service Item` | Billable items linked to appointment types |
| `Practitioner Schedule` | Weekly schedule template for doctors |
| `Practitioner Availability` | Actual available slots |
| `Practitioner Service Unit Schedule` | Schedule per service unit/room |
| `Healthcare Schedule Time Slot` | Individual time slots |

#### Practitioners & Departments (3 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Healthcare Practitioner` | Doctor/nurse/therapist profiles |
| `Medical Department` | Departments (Cardiology, Orthopedics, etc.) |
| `Healthcare Service Unit` | Rooms, beds, wards (tree structure) |
| `Healthcare Service Unit Type` | Types of units (OPD room, ICU bed, etc.) |
| `Service Unit Type Item` | Billable items per unit type |

#### Medications & Prescriptions (12 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Medication` | Drug/medicine master |
| `Medication Class` | Drug classes (antibiotics, analgesics, etc.) |
| `Medication Class Interaction` | Known interactions between drug classes |
| `Medication Ingredient` | Active ingredients |
| `Medication Linked Item` | Link medication to ERPNext stock items |
| `Medication Request` | Order for medication (from encounter) |
| `Mediciation Override Reason Code` | Reasons for overriding medication warnings |
| `Drug Prescription` | Child table: prescription line items |
| `Drug Interaction` | Drug-drug interaction records |
| `Dosage Form` | Tablet, capsule, syrup, etc. |
| `Dosage Strength` | Strength values (500mg, 10ml, etc.) |
| `Prescription Dosage` | Dosage schedules (BID, TID, etc.) |
| `Prescription Duration` | Duration templates (7 days, 2 weeks, etc.) |

#### Laboratory (11 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Lab Test` | Ordered/completed lab test record |
| `Lab Test Template` | Template defining test parameters |
| `Lab Test Group Template` | Grouped tests (e.g., "Complete Blood Panel") |
| `Lab Test Sample` | Sample types (blood, urine, etc.) |
| `Lab Test UOM` | Units of measurement for results |
| `Lab Prescription` | Child table: lab test line items in encounter |
| `Normal Test Result` | Numeric test results |
| `Normal Test Template` | Template for numeric tests |
| `Descriptive Test Result` | Text-based test results |
| `Descriptive Test Template` | Template for descriptive tests |
| `Sample Collection` | Track physical sample collection |

#### Diagnostic Reports & Observations (8 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Diagnostic Report` | Final diagnostic report document |
| `Observation` | Clinical observations (vitals, measurements) |
| `Observation Component` | Components within an observation |
| `Observation Reference Range` | Normal reference ranges |
| `Observation Sample Collection` | Sample collection for observations |
| `Observation Template` | Templates for observation types |
| `Specimen` | Physical specimen tracking |
| `Vital Signs` | Patient vital signs record |

#### Clinical Procedures (4 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Clinical Procedure` | Scheduled/performed procedure record |
| `Clinical Procedure Template` | Procedure definitions |
| `Clinical Procedure Item` | Items consumed during procedure |
| `Procedure Prescription` | Child table: procedure line items |

#### Therapy & Rehabilitation (7 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Therapy Plan` | Rehabilitation plan for a patient |
| `Therapy Plan Detail` | Individual items in a therapy plan |
| `Therapy Plan Template` | Reusable therapy plan templates |
| `Therapy Plan Template Detail` | Items in template |
| `Therapy Session` | Individual therapy session record |
| `Therapy Type` | Types of therapy (physiotherapy, etc.) |
| `Treatment Counselling` | Pre-treatment counselling records |

#### Treatment Planning (3 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Treatment Plan Template` | Standard treatment protocols |
| `Treatment Plan Template Item` | Items in treatment plan |
| `Treatment Plan Template Practitioner` | Practitioners involved |

#### Inpatient / Hospitalization (6 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Inpatient Record` | Admission to discharge record |
| `Inpatient Record Item` | Items during inpatient stay |
| `Inpatient Occupancy` | Bed/room occupancy tracking |
| `Inpatient Medication Order` | Medication orders for admitted patients |
| `Inpatient Medication Order Entry` | Individual entries in medication order |
| `Inpatient Medication Entry` | Actual medication administration |
| `Inpatient Medication Entry Detail` | Details of administration |

#### Insurance & Billing (7 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Insurance Payor` | Insurance company master |
| `Insurance Payor Contract` | Contract terms with insurer |
| `Insurance Payor Eligibility Plan` | Eligibility rules |
| `Insurance Claim` | Filed insurance claim |
| `Insurance Claim Coverage` | Coverage details per claim |
| `Item Insurance Eligibility` | Which items are covered |
| `Healthcare Payment Record` | Payment tracking |

#### Service Orders (3 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Service Request` | Generic service order (lab, procedure, etc.) |
| `Service Request Category` | Categories of service requests |
| `Service Request Reason` | Reasons for ordering |

#### Microbiology (3 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Organism` | Microorganism master |
| `Organism Test Item` | Tests for organisms |
| `Organism Test Result` | Culture/sensitivity results |
| `Sensitivity` | Antibiotic sensitivity master |
| `Sensitivity Test Result` | Sensitivity test results |
| `Antibiotic` | Antibiotic master list |

#### Medical Coding (5 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Code System` | Coding systems (ICD-10, SNOMED, etc.) |
| `Code Value` | Individual codes |
| `Code Value Set` | Groups of codes |
| `Codification Table` | Maps diagnoses to medical codes |
| `Allergy` | Patient allergies |
| `Allergy Interaction` | Allergy-drug interactions |

#### Patient Assessment (4 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Patient Assessment` | Structured assessment record |
| `Patient Assessment Detail` | Assessment line items |
| `Patient Assessment Sheet` | Assessment worksheets |
| `Patient Assessment Template` | Templates for assessments |
| `Patient Assessment Parameter` | Parameters measured |

#### Exercise / Rehab (4 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Exercise Type` | Types of exercises |
| `Exercise Type Step` | Steps within an exercise |
| `Exercise` | Exercise records |
| `Exercise Difficulty Level` | Difficulty levels |

#### Nursing (2 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Nursing Task` | Tasks assigned to nursing staff |
| `Nursing Checklist Template` | Standard checklists |
| `Nursing Checklist Template Task` | Tasks in checklist |

#### Fee & Validity (2 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Fee Validity` | Consultation fee validity tracking |
| `Fee Validity Reference` | References for fee validity |

#### India-Specific / ABDM (2 doctypes)
| Doctype | Purpose |
|---------|---------|
| `ABDM Settings` | Ayushman Bharat Digital Mission integration settings |
| `ABDM Request` | ABDM API request logs |

#### Settings & Config (2 doctypes)
| Doctype | Purpose |
|---------|---------|
| `Healthcare Settings` | Global healthcare module configuration |
| `Healthcare Activity` | Activity logging |
| `Sample Type` | Master list of sample types |

### Key Business Logic

#### Patient Encounter Flow (the heart of the system)
1. Doctor opens a Patient Encounter (linked to appointment)
2. Records symptoms (`Patient Encounter Symptom`)
3. Records diagnoses (`Patient Encounter Diagnosis`) 
4. Prescribes medications (`Drug Prescription`)
5. Orders lab tests (`Lab Prescription`)
6. Orders procedures (`Procedure Prescription`)
7. On submit: auto-creates `Service Request`, `Medication Request`, `Therapy Plan`
8. Appointment status set to "Closed"

#### Scheduler Events
- **Every minute:** Send appointment reminders
- **Daily:** Update appointment statuses, update fee validity, bill occupied inpatient beds

#### Document Events (hooks)
- **All doctypes on submit:** Create medical record entry (patient history)
- **Sales Invoice:** Manage healthcare-specific billing
- **Company creation:** Auto-create healthcare service unit tree
- **Patient insert:** Set ABDM consent details (India)
- **Payment Entry:** Manage insurance claims

### Patient Portal
Healthcare includes a Vue.js patient portal at `/patient-portal` where patients can:
- View personal details
- See appointments
- Access lab test results
- View prescriptions

---

## Module 2: Remedisys (AI Layer)

**Repository:** github.com/Social-Angel/Remedisys
**Version:** 0.0.1
**Publisher:** Social-Angel (Tech@socialangel.org)
**License:** MIT

### What It Is

A custom Frappe app that adds AI-powered clinical decision support to the Healthcare module. It hooks into the `Patient Encounter` doctype to provide real-time audio transcription, translation, and AI recommendations during doctor-patient consultations.

### Architecture

```
Browser (Patient Encounter form)
    │
    │  Click "AI Assistant" button
    ▼
┌─────────────────────────────────┐
│   AI Side Panel (JS/CSS)        │
│   - Mic recording (MediaRecorder)│
│   - 10-sec audio chunks         │
│   - Live transcript display      │
│   - Recommendation cards         │
└──────────┬──────────────────────┘
           │ POST /api/method/remedisys.api.medical_agent.process_audio_chunk
           ▼
┌─────────────────────────────────┐
│   Frappe Backend (Python)       │
│                                 │
│   1. Save audio to temp file    │
│   2. Whisper API → transcribe   │
│   3. GPT-4o → translate to ES   │
│   4. GPT-4o → clinical JSON     │
│   5. Cache state in Redis (8hr) │
│   6. Return results to frontend │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│   OpenAI API                    │
│   - whisper-1 (transcription)   │
│   - gpt-4o (translation +      │
│     structured recommendations) │
└─────────────────────────────────┘
```

### Files

| File | Purpose |
|------|---------|
| `hooks.py` | Injects CSS globally + JS into Patient Encounter doctype |
| `api/medical_agent.py` | Core AI backend — transcribe, translate, recommend |
| `api/auth/login.py` | Custom login endpoint with 2FA support |
| `api/auth/signup.py` | Custom signup endpoint |
| `api/auth/utils.py` | Auth helpers — session management, user data |
| `public/js/patient_encounter.js` | AI Assistant side panel UI with recording logic |
| `public/css/medical_agent.css` | Panel styling with dark mode support |

### API Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `remedisys.api.medical_agent.process_audio_chunk` | POST | Required | Receive 10-sec audio, return transcript + translation + recommendation |
| `remedisys.api.medical_agent.get_visit_state` | GET | Required | Get current visit session state from Redis |
| `remedisys.api.medical_agent.clear_visit_state` | POST | Required | Reset visit session |
| `remedisys.api.auth.login.login` | POST | Guest | Custom login |
| `remedisys.api.auth.login.logout` | POST | Required | Custom logout |
| `remedisys.api.auth.signup.signup` | POST | Guest | Custom signup |

### AI Pipeline (per 10-sec chunk)

1. **Transcription** (Whisper-1)
   - Receives audio blob (webm format)
   - Sends to OpenAI Audio API
   - Returns English text

2. **Translation** (GPT-4o)
   - Takes full accumulated English transcript
   - Translates to medically-faithful Spanish
   - Rules: preserve medical meaning, no fabrication

3. **Clinical Recommendation** (GPT-4o with Structured Output)
   - Analyzes full transcript
   - Returns JSON with strict schema:
     - `chief_complaint` — primary reason for visit
     - `summary` — visit summary
     - `possible_assessment` — differential diagnoses
     - `recommended_follow_up_questions` — what doctor should ask
     - `suggested_next_steps` — tests, referrals, treatment
     - `red_flags` — urgent concerns
     - `urgency` — low/moderate/high/emergent
     - `patient_facing_spanish_summary` — plain-language Spanish for patient
     - `safety_disclaimer` — mandatory AI disclaimer

### Session State (Redis)
Each visit maintains state in Redis with 8-hour TTL:
```json
{
  "chunks": [{"sequence_number": 1, "text": "..."}],
  "full_transcript_en": "accumulated English transcript",
  "full_transcript_es": "accumulated Spanish translation",
  "latest_recommendation": { /* structured JSON */ }
}
```

### Frontend — AI Assistant Panel
- **Trigger:** "AI Assistant" button added to Patient Encounter form
- **UI:** Slide-in right panel (400px) with overlay
- **Sections:**
  - Patient Problem (English transcript)
  - Spanish Translation
  - Suggestions for Doctor (structured recommendation cards)
- **Controls:** Start/Stop recording, language hint selector, reset
- **Recording:** MediaRecorder API, 10-sec intervals, auto-restart
- **Styling:** Responsive, dark mode aware, urgency color-coded badges

---

## How They Connect

```python
# In remedisys/hooks.py — this is the bridge:

# 1. CSS loaded globally on every page
app_include_css = "/assets/remedisys/css/medical_agent.css"

# 2. JS loaded ONLY on Patient Encounter (Healthcare's doctype)
doctype_js = {"Patient Encounter": "public/js/patient_encounter.js"}
```

This means:
- Remedisys does NOT modify any Healthcare file
- It uses Frappe's hook system to inject its AI panel into Healthcare's Patient Encounter
- Both apps share the same site, database, and Redis
- The AI panel uses the `Patient Encounter` document name as `visit_id`

**The separation is clean:** Healthcare handles structured clinical data (patients, diagnoses, prescriptions). Remedisys adds an AI layer on top for real-time transcription and decision support during the encounter.

---

## GPT Conversation Context & Product Vision

### Origin (from gptscript.md)

The product was conceived by **Deepak Sharma** (Social-Angel/Remedisys org) in a ChatGPT group conversation (March 26-27, 2026) with team members **uxanant** and **Sarvesh Shahi**.

### Original Prompt
> "I need to create agent to run on frappe that would listen to conversation and translate in Spanish using openai models and also give medical recommendation."

### ChatGPT Designed the Architecture
The conversation produced the complete architecture that Remedisys implements:
1. Browser captures mic audio via MediaRecorder
2. 10-second chunks sent to Frappe backend
3. OpenAI Whisper for transcription
4. OpenAI text model for Spanish translation
5. Structured JSON clinical recommendations
6. Redis session state per visit
7. Vue.js frontend (later simplified to vanilla Frappe JS)

### Production Recommendations from the Conversation

#### Data Model Additions Suggested (Not Yet Built)
- **Clinical Visit Session** doctype — persist visit data beyond Redis TTL
- **Clinical Audio Chunk** doctype — audit trail for audio chunks

#### Performance Optimizations Suggested
- Run recommendation every 2-3 chunks instead of every chunk
- Rolling summary memory every 1 minute
- Final structured pass at visit end

#### Compliance Hardening Suggested
- Encrypt stored transcripts
- Define retention policy
- Access control by clinician role
- Log every recommendation generation
- HIPAA/BAA compliance verification

#### UX Enhancements Suggested
- Live mic waveform
- Confidence indicator
- Copy buttons for transcript/summary
- Doctor review mode (Accept/Edit/Save to chart)
- "Finalize note" button generating SOAP note + AVS + billing summary

#### Phased Build Plan from Conversation
| Phase | Scope |
|-------|-------|
| Phase 1 (Done) | Audio chunking, transcription, Spanish translation |
| Phase 2 (Partially done) | Structured recommendations, red flags, visit state |
| Phase 3 (Not started) | SOAP notes, EHR integration, compliance, human review workflow |

---

## Development Guide

### Where to Make Changes

| What | Where | How |
|------|-------|-----|
| Add AI features | `apps/remedisys/` | Add Python APIs + JS hooks |
| Add new doctypes | `apps/remedisys/` | `bench new-doctype` in remedisys app |
| Modify Healthcare behavior | `apps/remedisys/hooks.py` | Use `doc_events`, `doctype_js`, `override_whitelisted_methods` |
| Add custom fields to Healthcare doctypes | Frappe Custom Field | No code change needed |
| Frontend changes | `apps/remedisys/remedisys/public/` | JS + CSS files |

### Key Commands
```bash
# Start bench
cd ~/Desktop/frappe-bench && bench start

# Rebuild assets after JS/CSS changes
bench build --app remedisys

# Create new doctype
bench new-doctype "Clinical Visit Session" --module Remedisys

# Run Python changes (auto-reload in dev mode)
# Just save the file — bench auto-reloads

# Access shell
bench console

# MariaDB shell
bench mariadb
```

### API Development Pattern
```python
# In remedisys/api/your_module.py

import frappe
from frappe import _

@frappe.whitelist(methods=["POST"])
def your_endpoint():
    """Your docstring."""
    data = frappe.form_dict
    # ... your logic ...
    return {"ok": True, "result": data}
```

Accessible at: `POST /api/method/remedisys.api.your_module.your_endpoint`

### Extending Healthcare Doctypes (without modifying them)
```python
# In remedisys/hooks.py

doc_events = {
    "Patient Encounter": {
        "after_insert": "remedisys.api.hooks.on_encounter_created",
        "on_update": "remedisys.api.hooks.on_encounter_updated",
        "on_submit": "remedisys.api.hooks.on_encounter_submitted",
    },
    "Patient": {
        "after_insert": "remedisys.api.hooks.on_patient_created",
    }
}

# Add JS to more doctypes
doctype_js = {
    "Patient Encounter": "public/js/patient_encounter.js",
    "Patient": "public/js/patient.js",
    "Patient Appointment": "public/js/patient_appointment.js",
}
```
