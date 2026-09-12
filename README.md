
---
1. Project Overview
VERIGUARD is an AI-assisted web-based document and identity screening system designed to help security or screening officers analyze identity documents in a faster, more standardized, and more auditable way.
The system combines OCR, document validation, image integrity analysis, face verification, structured risk assessment, officer authentication, MongoDB-based case storage, and audit logging in a single officer-facing console.
The intended screening flow is:
```text
Officer Login
      ↓
Secure Document Upload
      ↓
OCR + Field Extraction
      ↓
Document Validation
      ↓
Reference Verification
      ↓
Tampering / Integrity Analysis
      ↓
Person Face vs Document Printed Face Verification
      ↓
Risk Assessment
      ↓
Screening Result
      ↓
Case ID + MongoDB Storage
      ↓
History + Audit Trail
```
VERIGUARD is designed as a decision-support system. AI output should support officer review rather than being treated as an automatic legal determination of fraud.
---
2. Problem Statement
Manual identity-document screening can require several repetitive steps:
Reading document information manually
Checking whether extracted information is structurally valid
Inspecting suspicious image regions
Comparing the person with the photograph printed on the document
Maintaining screening records
Keeping track of which officer performed the screening
Standardizing risk-based decisions
The objective of VERIGUARD is to combine these activities into one structured digital workflow.
---
3. Proposed Solution
VERIGUARD creates an integrated screening pipeline in which a document is treated as a collection of evidence signals.
The major solution components are:
```text
1. Officer Authentication
2. Secure Document Upload
3. OCR and Field Extraction
4. Document Validation
5. Reference Database Verification
6. Tampering / Integrity Analysis
7. Face Verification
8. Structured Risk Assessment
9. Screening History
10. Audit Trail
11. Analytics and Reporting
```
Instead of showing only a single final result, the system is intended to expose the important evidence contributing to the result.
Example:
```text
Risk Score: 67 / 100
Risk Level: HIGH
Decision: MANUAL REVIEW

Contributing Factors:
- Validation concern
- Face mismatch contribution
- Suspicious image-region signals
- Reference mismatch
```
---
4. SIH Problem Alignment
Requirement	VERIGUARD Approach
Reduce screening time	OCR + automated validation + AI-assisted analysis
Detect suspicious documents	Multi-signal integrity/tampering analysis
Standardize screening	Structured fields, risk levels and decisions
Verify identity	Person-photo vs printed-document-face comparison
Maintain digital records	MongoDB screening cases
Secure officer access	Authentication and session management
Preserve accountability	Officer-linked records and audit logs
---
5. System Architecture
```text
                           ┌──────────────────────┐
                           │       OFFICER        │
                           └──────────┬───────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │ React + Vite Console │
                           └──────────┬───────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │ FastAPI Auth Layer   │
                           └──────────┬───────────┘
                                      │
                                      ▼
                     ┌────────────────────────────────┐
                     │ Screening Orchestration Layer  │
                     └───────────────┬────────────────┘
                                     │
             ┌───────────────────────┼────────────────────────┐
             │                       │                        │
             ▼                       ▼                        ▼
      ┌─────────────┐        ┌───────────────┐        ┌──────────────┐
      │ Tesseract   │        │ Validation    │        │ Tampering    │
      │ OCR         │        │ Engine        │        │ Analysis     │
      └──────┬──────┘        └───────┬───────┘        └──────┬───────┘
             │                       │                       │
             └───────────────┬───────┴───────────────────────┘
                             │
                             ▼
                    ┌───────────────────┐
                    │ Face Verification │
                    │ YuNet + SFace     │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Risk Assessment   │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Screening Case    │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │     MongoDB       │
                    └───────────────────┘
```
---
6. End-to-End Workflow
```text
┌─────────────────────────┐
│ 1. Officer Login        │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 2. Upload Document      │
│    + Optional Person    │
│      Photo              │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 3. OCR Extraction       │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 4. Structured Fields    │
│    Name / DOB / ID etc. │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 5. Document Validation  │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 6. Reference Check      │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 7. Tampering Analysis   │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 8. Face Verification    │
│    Person vs Document   │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 9. Risk Engine          │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 10. Result + Case ID    │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 11. MongoDB Storage     │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 12. History + Audit     │
└─────────────────────────┘
```
---
7. Core Modules
7.1 Officer Authentication
VERIGUARD uses authentication as an outer security layer around the screening system.
The intended model is:
```text
Officer
   ↓
Username + Password
   ↓
MongoDB Officer Record
   ↓
Password Hash Verification
   ↓
Session Creation
   ↓
Protected Screening Console
```
Features implemented:
Pre-created officer accounts
Password hashing
Officer profile
Login
Logout
Session/token handling
Protected APIs
Session expiry
Login success/failure logging
Officer-linked screening records
The current password hashing implementation uses PBKDF2-HMAC-SHA256 with 310,000 iterations.
---
7.2 Document Upload
The document screening interface supports image-based document uploads with upload security checks.
Security measures include:
File type validation
Size restrictions
Actual-format verification
Filename sanitization
Malicious/decompression-bomb protection
Controlled image processing
Supported screening scenarios include:
Passport
Visa
National ID / Identity Card
Driving Licence / Driving License
Permits
Other identity-document style inputs
---
8. OCR and Field Extraction
Technology
```text
Tesseract OCR
pytesseract
Pillow
```
OCR converts the uploaded document image into machine-readable text.
The extraction layer is designed for:
Full name
Date of birth
Document ID / number
Validity
Nationality
Gender
Passport-specific fields
Visa-specific fields
Example structured result:
```json
{
  "full_name": "SHIVAM SINGH",
  "dob": "17 Nov, 2004",
  "document_id": "24AI0321",
  "validity": "2024-2027",
  "nationality": "INDIAN",
  "gender": "M"
}
```
The OCR confidence and extracted-field quality can be used as supporting risk signals.
---
9. Document Validation
The document validation layer checks whether extracted information follows expected rules.
Validation checks
```text
Document type
Document number / ID format
Required fields
Date parsing
DOB validity
Expiry state
Validity period
Start date vs expiry date
Nationality / country consistency
Document-specific patterns
```
Typical outcomes
```text
VALID
INVALID
EXPIRED
NOT_YET_VALID
REVIEW
UNKNOWN
```
The validation result is stored with the screening case.
---
10. Reference Database Verification
For passport-oriented screening, VERIGUARD can compare extracted information with a MongoDB reference collection.
Possible outcomes:
```text
MATCH
PARTIAL_MATCH
MISMATCH
NO_MATCH
```
The reference database is intended to support screening, not to be treated as a complete national identity registry.
The current prototype uses synthetic passport reference data.
---
11. Tampering and Integrity Detection
VERIGUARD uses a multi-signal approach rather than relying on a single image metric.
Global ELA
Error Level Analysis can help highlight areas that behave differently under recompression.
```text
Input Image
    ↓
ELA Processing
    ↓
Global Signal
```
Local Region Analysis
The image can be divided into multiple regions and inspected for abnormal local behavior.
Signals include:
ELA variation
Laplacian / sharpness variation
Edge density
Robust median / MAD comparison
Text Region Analysis
Potential inconsistencies around text regions can be inspected.
Photo Region Analysis
The photo area on the document can be analyzed relative to nearby image regions.
Metadata Analysis
The system can inspect available metadata and editing-software indicators when metadata is present.
Combined result
```text
Global ELA
    +
Local Regions
    +
Text Region
    +
Photo Region
    +
Metadata
    ↓
Multi-Signal Integrity Score
    ↓
Evidence Count
    ↓
Tampering Classification
```
Typical classification:
```text
NORMAL
LOW_RISK
REVIEW
HIGH_RISK
```
Important: integrity analysis is a screening signal and can produce false positives. Threshold calibration with representative labeled examples is required before production deployment.
---
12. Face Verification
Objective
The face-verification module is specifically designed around:
```text
Person / Live Photo
          ↕
Printed Face on Uploaded Document
```
It is not intended to compare the person with arbitrary faces from the reference database.
Technologies
```text
OpenCV YuNet
OpenCV SFace
Cosine Similarity
```
Processing
```text
Document Image
      ↓
YuNet Face Detection
      ↓
Printed Document Face
      │
      │
Person Photo
      ↓
YuNet Face Detection
      ↓
Primary Person Face
      ↓
SFace Feature Extraction
      ↓
Feature Comparison
      ↓
Similarity Score
      ↓
MATCH / PARTIAL MATCH / MISMATCH
```
Robustness features
Camera access
Live face capture
Uploaded person-photo fallback
Visual face guide
Tighter central crop
Document face detection
Person face detection
Centered primary-face selection
Multiple-background-face handling
SFace feature comparison
Similarity score
Face-result contribution to risk
The frontend capture guide is primarily a user-assistance feature; final face detection occurs in the backend pipeline.
---
13. Risk Assessment Engine
The risk engine combines multiple signals into a structured screening score.
Conceptually:
```text
Validation Risk
        +
Reference Verification Risk
        +
Face Verification Risk
        +
Tampering Risk
        +
OCR / Field Quality
        +
Image Quality
        +
Document-specific Policy
        ↓
Overall Risk Score
```
Risk levels
Score	Level	Typical decision
80–100	CRITICAL	REJECT / ESCALATE
60–79	HIGH	MANUAL REVIEW
35–59	MEDIUM	MANUAL REVIEW
20–34	LOW-RISK REVIEW	SECONDARY CHECK

0–19	LOW	PASS / CLEAR
Explainable result
A useful result is structured like:
```text
Risk Score: 67 / 100
Risk Level: HIGH
Decision: MANUAL REVIEW

Reasons:
- Validation concern
- Face mismatch contribution
- Suspicious local regions
- Reference mismatch
```
Some prototype-specific policies can intentionally increase risk for selected demonstration scenarios. Such rules represent operational/demo policy and are not standalone proof that a document is fraudulent.
---
14. Case Management
Every completed screening can be represented as a structured case.
Example:
```text
Case ID: VG-20260911-000001

Officer:
  MARK01

Document:
  Type
  Number
  Name
  DOB
  Validity
  Nationality
  Gender

Validation:
  Result
  Findings

Tampering:
  Score
  Classification
  Evidence Count
  Findings

Face:
  Document Face
  Person Face
  Similarity
  Result

Risk:
  Score
  Level
  Decision
  Reasons

Audit:
  Officer
  Timestamp
  Event
```
---
15. Case ID System
Case IDs are generated through a MongoDB-backed atomic counter.
Example format:
```text
VG-20260911-000001
VG-20260911-000002
VG-20260911-000003
```
The design provides a unique, readable identifier for screening records.
---
16. MongoDB Architecture
Database:
```text
veriguard
```
Collections:
```text
veriguard
├── reference_passports
├── screening_cases
├── dataset_metadata
├── officers
├── auth_sessions
├── audit_logs
└── case_counters
```
Collection responsibilities
reference_passports
Synthetic passport reference records.
screening_cases
Completed screening cases and results.
dataset_metadata
Metadata associated with imported reference datasets.
officers
Officer login and profile data.
auth_sessions
Authenticated session records with expiration.
audit_logs
Security and screening events.
case_counters
Atomic case-ID generation.
---
17. Audit Trail
The audit system is intended to answer:
```text
Who?
What?
When?
Which case?
What event?
```
Examples of logged events:
```text
LOGIN_SUCCESS
LOGIN_FAILED
LOGOUT
SCREENING_COMPLETED
```
The audit trail is intended to improve accountability and make the screening workflow traceable.
---
18. Dashboard and User Interface
The web console includes the following main areas:
```text
Dashboard
Document Screening
Screening History
Risk Analytics
Reports
Settings
Help
Audit Trail
```
Dashboard
Provides a high-level operational view of the screening system.
Document Screening
Main operational workflow:
```text
Upload
  ↓
Analyze
  ↓
Review
  ↓
Risk
  ↓
Case Result
```
Screening History
Supports:
Search
Filters
Status
Risk information
Case details
Officer information
Risk Analytics
Provides a foundation for:
Risk distribution
Document-type statistics
Tampering statistics
Face mismatch statistics
Officer-wise statistics
Date-wise trends
Reports
Provides report-oriented result views and can be extended to downloadable individual case reports.
Settings
Includes:
Officer profile
Appearance
Dark / Light theme
Readability settings
Security session information
System status
Help / Support
---
19. Frontend Structure
```text
frontend/
├── src/
│   ├── App.jsx
│   └── App.css
├── public/
├── package.json
├── package-lock.json
├── index.html
└── vite.config.js
```
The UI is built as a single officer-oriented React application with security-dashboard styling.
---
20. Backend Structure
```text
backend/
├── main.py
├── db.py
├── field_extraction_service.py
├── import_dataset.py
├── seed_officer.py
├── models/
│   └── face/
└── venv/
```
Main responsibilities
```text
main.py
    FastAPI application
    Authentication
    Upload pipeline
    Screening orchestration
    OCR
    Validation
    Tampering
    Face verification
    Risk engine
    History / analytics / reports

db.py
    MongoDB connection
    Collections
    Indexes
    Case IDs
    Data helpers
    Retention helpers
    Sanitization

field_extraction_service.py
    Enhanced field extraction
    Passport fields
    Visa fields
    Nationality
    Gender
    Document-specific parsing

import_dataset.py
    Synthetic reference-data import

seed_officer.py
    Officer account creation / seeding
```
---
21. Technology Stack
Frontend
```text
React
Vite
JavaScript
CSS
```
Backend
```text
Python
FastAPI
Uvicorn
```
OCR
```text
Tesseract OCR
pytesseract
Pillow
```
Computer Vision
```text
OpenCV
NumPy
YuNet
SFace
```
Database
```text
MongoDB
PyMongo
dnspython
```
Configuration
```text
python-dotenv
```
Dataset / Utilities
```text
Hugging Face datasets
Hugging Face Hub
Requests
```
Security
```text
PBKDF2-HMAC-SHA256
Session tokens
Protected APIs
File validation
Filename sanitization
Upload security
```
---
22. Dependencies
Backend package installation used in the prototype:
```bash
pip install fastapi uvicorn python-multipart
pip install pytesseract pillow
pip install opencv-contrib-python==4.10.0.84
pip install numpy
pip install pymongo dnspython
pip install python-dotenv
pip install datasets requests huggingface_hub
```
Frontend installation:
```bash
npm install
```
---
23. Local Setup
Step 1 — Clone repository
```bash
git clone https://github.com/prakhar2865/MARK-01.git
cd MARK-01
```
Step 2 — Backend environment
```bash
cd backend
python -m venv venv
source venv/Scripts/activate
```
On Windows Git Bash:
```bash
source venv/Scripts/activate
```
Step 3 — Install backend dependencies
```bash
pip install fastapi uvicorn python-multipart
pip install pytesseract pillow
pip install opencv-contrib-python==4.10.0.84
pip install numpy
pip install pymongo dnspython
pip install python-dotenv
pip install datasets requests huggingface_hub
```
Step 4 — Start backend
```bash
uvicorn main:app --reload
```
Backend:
```text
http://127.0.0.1:8000
```
Step 5 — Start frontend
Open another terminal:
```bash
cd frontend
npm install
npm run dev
```
Open the Vite development URL shown by the terminal.
---
24. MongoDB Setup
Default local connection:
```text
mongodb://localhost:27017
```
Database:
```text
veriguard
```
MongoDB should be running before starting the backend.
Example health response:
```json
{
  "status": "healthy",
  "mongodb": "connected",
  "screening_cases": 10
}
```
The exact case count depends on the current database contents.
---
25. Tesseract Setup
Windows installation path used in development:
```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```
Example version used during development:
```text
Tesseract 5.5.3
```
Python package:
```text
pytesseract
```
---
26. Face Model Setup
The face verification pipeline uses OpenCV Zoo models.
YuNet
```text
face_detection_yunet_2023mar.onnx
```
SFace
```text
face_recognition_sface_2021dec.onnx
```
The backend stores the models under:
```text
backend/models/face/
```
These model files are normally excluded from Git using `.gitignore` and can be downloaded when needed.
---
27. Reference Dataset
The prototype uses the following synthetic dataset:
```text
ud-synthetic/indian-passports
```
Source:
```text
https://huggingface.co/datasets/ud-synthetic/indian-passports
```
The available dataset is synthetic/fictional and should not be represented as a real-person national identity or biometric database.
---
28. Example Screening Result
Example prototype output:
```text
Document Type:
Student ID

Full Name:
Shivam Singh

DOB:
17 Nov, 2004

Document ID:
24AI0321

Validity:
2024–2027

Validation:
VALID

Face Verification:
MATCH

Similarity:
75.7 / 100

Document Face:
DETECTED

Person Face:
DETECTED

OCR:
COMPLETED

ELA:
REVIEW

Metadata:
LIMITED

Risk Score:
35 / 100
```
Exact values vary according to the uploaded document and screening scenario.
---
29. Demo Scenarios
Scenario A — Clean document
Expected behavior:
```text
OCR              COMPLETED
Validation       VALID
Face             MATCH
Tampering        NORMAL / REVIEW
Risk             LOW
Decision         PASS / CLEAR
```
Scenario B — Face mismatch
```text
Document Face     DETECTED
Person Face       DETECTED
Similarity        LOW
Face Result       MISMATCH
Risk              ELEVATED
Decision          MANUAL REVIEW / ESCALATE
```
Scenario C — Tampered image
```text
Global ELA        REVIEW
Local Regions     SUSPICIOUS
Text Region       REVIEW / SUSPICIOUS
Photo Region      REVIEW
Metadata          LIMITED
Risk              ELEVATED
Decision          MANUAL REVIEW
```
Scenario D — Demonstration risk policy
A selected document scenario can intentionally be routed into a higher review category by a prototype-specific operational policy.
The UI should distinguish between:
```text
AI / evidence signal
```
and
```text
Operational policy
```
so that a business rule is not misunderstood as proof of fraud.
---
30. Security Design
VERIGUARD's security design contains multiple controls.
```text
                    SECURITY
                       │
       ┌───────────────┼────────────────┐
       │               │                │
       ▼               ▼                ▼
 Authentication    Upload Security   Auditability
       │               │                │
 Password Hashing   File Validation   Login Events
 Session Control   Size Limits        Screening Events
 Protected APIs    MIME Checks        Officer ID
 Logout            Filename Rules     Timestamp
 Session Expiry    Decompression      Case ID
```
---
31. Sensitive Data Principles
The system is designed around the principle that operational screening data should remain in controlled application/database infrastructure.
For future blockchain use, documents and face images should not be stored on-chain.
---
32. Blockchain Extension
The current prototype does not contain a live blockchain implementation.
A practical future extension is to use blockchain only for an integrity proof.
Proposed flow:
```text
Screening Case
      ↓
Canonicalized Result
      ↓
SHA-256 Hash
      ↓
Immutable Ledger / Blockchain
```
MongoDB would continue storing operational case data, while the blockchain would store a compact integrity proof.
Possible blockchain record:
```text
Case ID
Result Hash
Timestamp
Officer/System Reference
```
This preserves the separation between:
```text
Operational Data
```
and
```text
Immutable Integrity Proof
```
A suitable presentation line is:
> Cybersecurity protects the screening system, while blockchain can provide an immutable audit and integrity layer for screening evidence.
---
33. Data Privacy and Deployment Considerations
Before real-world deployment, additional controls would be required.
Recommended future work includes:
```text
Encryption at rest
Encryption in transit
Role-based access control
Secrets management
Production MongoDB authentication
Rate limiting
Security monitoring
Privacy controls
Retention policies
Consent / legal review
Model governance
Threshold calibration
Bias / false-positive assessment
```
---
34. Testing Plan
Authentication
```text
[ ] Correct login
[ ] Wrong password
[ ] Unknown officer
[ ] Inactive officer
[ ] Session expiry
[ ] Logout
[ ] Unauthenticated protected API
```
OCR
```text
[ ] Clear document
[ ] Low-quality document
[ ] Different layouts
[ ] Name extraction
[ ] DOB extraction
[ ] Document ID extraction
[ ] Validity extraction
[ ] Nationality extraction
[ ] Gender extraction
[ ] Passport fields
[ ] Visa fields
```
Validation
```text
[ ] Valid document
[ ] Invalid number
[ ] Expired document
[ ] Future DOB
[ ] Missing field
[ ] Unsupported pattern
```
Tampering
```text
[ ] Clean image
[ ] Compression-only image
[ ] Text edit
[ ] Photo replacement
[ ] Local paste
[ ] Metadata variation
[ ] False-positive testing
```
Face
```text
[ ] MATCH
[ ] MISMATCH
[ ] NO FACE
[ ] Low light
[ ] Blur
[ ] Multiple background faces
[ ] Different distances
[ ] Uploaded photo
```
Database
```text
[ ] MongoDB available
[ ] MongoDB unavailable
[ ] Unique case ID
[ ] History record
[ ] Officer-linked case
[ ] Audit event
[ ] Analytics
[ ] Reports
```
---
35. Current Implementation Status
Completed
```text
✓ React + Vite frontend
✓ FastAPI backend
✓ Backend ↔ Frontend connection
✓ MongoDB connection
✓ MongoDB Compass setup
✓ Project structure
✓ CORS
✓ Login page
✓ Officer credentials in MongoDB
✓ Password hashing
✓ Login API
✓ Session/token system
✓ Logout
✓ Protected APIs
✓ Officer profile
✓ Audit trail
✓ Secure upload
✓ File type/size restrictions
✓ Tesseract OCR
✓ Basic field extraction
✓ Document validation
✓ Reference passport collection
✓ Expiry validation
✓ Number-format validation
✓ ELA
✓ Metadata analysis
✓ Text consistency
✓ Image-quality analysis
✓ Multi-signal tampering analysis
✓ Local-region analysis
✓ Text-region analysis
✓ Photo-region analysis
✓ Evidence count
✓ Explainable tampering findings
✓ YuNet face detection
✓ SFace recognition
✓ Person photo capture
✓ Person photo upload fallback
✓ Similarity score
✓ Multiple-face handling
✓ Risk scoring
✓ Screening history
✓ Analytics page
✓ Reports page
✓ Settings
✓ Dark/light UI
✓ Upload security
✓ Case-ID generation
✓ MongoDB indexing / retention helpers
```
Implemented but needs broader testing
```text
~ Passport-specific OCR fields
~ Visa-specific OCR fields
~ Nationality extraction improvement
~ Gender extraction improvement
~ Passport number extraction improvement
~ Visa number/type/entry/stay validation
~ YuNet/SFace robustness across broader conditions
~ Structured Risk Engine calibration
```
Future improvements
```text
- Password change
- Stronger session invalidation
- Better photo replacement detection
- Better text manipulation detection
- Stamp/signature analysis
- Better metadata detection
- Tampering heatmaps
- Representative tampered-document calibration
- False-positive testing
- Expanded risk analytics
- Individual downloadable PDF reports
- Detailed case timeline
- Loading/error/empty states
- Rate limiting
- Production security configuration
- End-to-end testing
- Performance testing
- Liveness / anti-spoofing
- More document types
- Blockchain integrity extension
```
---
36. Production Roadmap
```text
PHASE 1
Prototype
  └─ Core screening workflow

PHASE 2
Model and threshold calibration
  └─ Realistic labeled test sets

PHASE 3
Security hardening
  └─ Production authentication / secrets / monitoring

PHASE 4
Operational reporting
  └─ Signed case reports / advanced analytics

PHASE 5
Advanced identity protection
  └─ Liveness / anti-spoofing / advanced document forensics

PHASE 6
Integrity infrastructure
  └─ Immutable result-hash / blockchain layer
```
---
37. Suggested SIH Demo Flow
A clean presentation sequence:
```text
1. Login as Officer
        ↓
2. Open Dashboard
        ↓
3. Go to Document Screening
        ↓
4. Upload Sample Document
        ↓
5. Show OCR Fields
        ↓
6. Show Validation
        ↓
7. Show Tampering / Integrity Signals
        ↓
8. Capture Person Face
        ↓
9. Show Face MATCH / MISMATCH
        ↓
10. Show Risk Score
        ↓
11. Show Case ID
        ↓
12. Open Screening History
        ↓
13. Open Audit Trail
```
---
38. Key Differentiators
VERIGUARD combines several capabilities into a single screening flow:
```text
OCR
  +
Document Rules
  +
Reference Verification
  +
Image Forensics
  +
Face Verification
  +
Risk Engine
  +
Officer Authentication
  +
Audit Trail
  +
MongoDB Case Management
```
The focus is not only on “detecting a fake document” but on producing a more structured screening package for an authorized officer.
---
39. Important Engineering Notes
VERIGUARD is a prototype and not a certified government identity-verification platform.
AI signals can produce false positives and false negatives.
Face verification depends on pose, lighting, blur, occlusion and printed-photo quality.
OCR quality depends strongly on image clarity and document layout.
Tampering algorithms require representative calibration data.
Synthetic reference data must not be represented as real national identity data.
Any production implementation should undergo security, privacy, legal and operational review.
High-impact decisions should include appropriate human oversight.
---
40. Repository
GitHub repository:
```text
https://github.com/prakhar2865/MARK-01
```
Project:
```text
VERIGUARD
```
Problem Statement:
```text
SIH26188
AI-Based Fake Identity & Document Screening System
```
---
41. Final Project Summary
VERIGUARD is an integrated AI-assisted identity and document screening prototype that brings together:
```text
Secure Officer Authentication
            +
OCR
            +
Document Validation
            +
Reference Verification
            +
Tampering / Integrity Analysis
            +
Printed-Face Verification
            +
Risk Assessment
            +
MongoDB Case Management
            +
Audit Trail
```
The intended final outcome is a structured case in which an officer can understand:
```text
WHAT was uploaded
        ↓
WHAT was extracted
        ↓
WHAT was validated
        ↓
WHAT looked suspicious
        ↓
WHETHER the person's face matched
        ↓
WHY the risk level was assigned
        ↓
WHO performed the screening
        ↓
WHEN it happened
```
---
VERIGUARD
VERIFY • ANALYZE • ASSESS • AUDIT
AI-assisted identity and document screening for security operations.
