from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from PIL import Image, ImageChops, ImageEnhance, ExifTags, ImageStat
from PIL import UnidentifiedImageError
import pytesseract
from pytesseract import Output

import cv2
import numpy as np


import re
from io import BytesIO
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

# MongoDB
from db import (
    reference_passports, screening_cases, db, audit_logs,
    generate_case_id, sanitize_screening_case,
)

# Authentication collections. Existing screening collections remain unchanged.
officers = db["officers"]
auth_sessions = db["auth_sessions"]


# =========================================================
# TESSERACT
# =========================================================

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="AI Document Screening System",
    version="3.0.0"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DOCUMENT TYPE
# =========================================================

def detect_document_type(text):

    text_lower = text.lower()

    if "passport" in text_lower:
        return "Passport"

    # Driving Licence detection: use several visual/OCR clues because real
    # card photographs may not OCR the main heading cleanly.
    dl_clues = [
        "driving licence",
        "driving license",
        "indian union driving",
        "validity (nt)",
        "validity(nt)",
        "date of first issue",
        "holder's signature",
        "son/daughter/wife of",
        "issued by uttar pradesh",
    ]
    if sum(clue in text_lower for clue in dl_clues) >= 1:
        return "Driving Licence"

    if (
        "voter" in text_lower
        or "election commission" in text_lower
    ):
        return "Voter ID"

    if "visa" in text_lower:
        return "Visa"

    if (
        "student id" in text_lower
        or "university" in text_lower
    ):
        return "Student ID"

    if (
        "aadhaar" in text_lower
        or "aadhar" in text_lower
    ):
        return "Aadhaar / National ID"

    return "Unknown Document"


from field_extraction_service import extract_passport_fields, extract_visa_fields, extract_nationality_enhanced, extract_gender, validate_visa_fields

# =========================================================
# NAME EXTRACTION
# =========================================================

def _clean_person_name(value):
    """Clean an OCR name candidate without swallowing neighbouring fields."""
    if not value:
        return None

    value = re.sub(r"[|]+", " ", value)
    value = re.sub(
        r"\b(?:DATE\s+OF\s+BIRTH|DOB|BLOOD\s+GROUP|ORGAN\s+DONOR|VALID(?:ITY)?|ADDRESS|FATHER(?:'S)?\s+NAME|S/O|D/O|W/O|C/O)\b.*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^[\s:;,#.\-]+|[\s:;,#.\-]+$", "", value)
    value = re.sub(r"\s+", " ", value).strip()

    # A name should contain letters and normally 1-5 words. Reject obvious
    # OCR/system/document fields and strings dominated by digits.
    if not re.search(r"[A-Za-z]", value) or re.search(r"\d", value):
        return None

    words = value.split()
    if not 1 <= len(words) <= 5:
        return None

    blocked = {
        "name", "surname", "given", "father", "mother", "date", "birth",
        "blood", "group", "organ", "donor", "driving", "licence", "license",
        "government", "india", "transport", "department", "valid", "validity",
        "address", "male", "female", "nationality", "citizenship", "passport",
        "visa", "student", "identity", "card", "number", "dob"
    }
    if all(w.lower().strip(".:") in blocked for w in words):
        return None

    # Names may contain initials (e.g. A. K. SHARMA), apostrophes and hyphens.
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
        return None

    return value


def extract_name(lines):
    """Robust name extraction, with special handling for Indian DL OCR."""
    # Explicit labels. Handles: NAME:, Name of Holder:, 1. NAME, etc.
    label_patterns = [
        r"(?:^|\b)(?:FULL\s+NAME|NAME\s+OF\s+(?:HOLDER|DRIVER|APPLICANT)|SURNAME|GIVEN\s+NAME|NAME)\s*[:#\-]?\s*(.+)$",
        r"^\s*\d+\s*[.)-]\s*(?:NAME|FULL\s+NAME)\s*[:#\-]?\s*(.+)$",
    ]

    for i, line in enumerate(lines):
        clean = line.strip()
        if not clean:
            continue

        for pattern in label_patterns:
            match = re.search(pattern, clean, re.IGNORECASE)
            if match:
                candidate = _clean_person_name(match.group(1))
                if candidate and candidate.lower() not in {"of holder", "of driver"}:
                    return candidate

                # Some OCR puts the value on the next line.
                if i + 1 < len(lines):
                    candidate = _clean_person_name(lines[i + 1].strip())
                    if candidate:
                        return candidate

        # Label and value may be split: "NAME" on one line, value next line.
        if re.fullmatch(r"(?:FULL\s+)?NAME(?:\s+OF\s+(?:HOLDER|DRIVER|APPLICANT))?\s*[:#\-]?", clean, re.IGNORECASE):
            if i + 1 < len(lines):
                candidate = _clean_person_name(lines[i + 1].strip())
                if candidate:
                    return candidate

    # Driving licence cards often have "S/O", "D/O" etc. immediately near
    # the holder's name. If the line before a relation marker looks like a
    # normal person name, use it.
    for i, line in enumerate(lines):
        if re.search(r"\b(?:S/O|D/O|W/O|C/O)\b", line, re.IGNORECASE):
            before = re.split(r"\b(?:S/O|D/O|W/O|C/O)\b", line, maxsplit=1, flags=re.IGNORECASE)[0]
            candidate = _clean_person_name(before)
            if candidate:
                return candidate
            if i > 0:
                candidate = _clean_person_name(lines[i - 1].strip())
                if candidate:
                    return candidate

    # Conservative fallback. Never accept lines that clearly belong to other
    # document fields (the previous fallback incorrectly returned "Date of Birth").
    ignored_terms = (
        "date of birth", "dob", "blood group", "organ donor", "validity",
        "valid until", "expiry", "expiration", "driving licence", "driving license",
        "government", "transport", "department", "address", "nationality",
        "citizenship", "passport", "visa", "student id", "identity card",
        "document", "license", "licence", "number", "no."
    )

    candidates = []
    for line in lines:
        clean = line.strip()
        lower = clean.lower()
        if not clean or any(term in lower for term in ignored_terms):
            continue

        # Reject date-like / identifier-like lines before the name regex.
        if re.search(r"\d{1,4}[./-]\d{1,4}[./-]\d{2,4}", clean):
            continue
        if re.search(r"\b[A-Z]{2}\d{2}[\s/-]?\d{4}[\s/-]?\d{4,8}\b", clean.upper()):
            continue

        candidate = _clean_person_name(clean)
        if candidate and 2 <= len(candidate.split()) <= 4:
            candidates.append(candidate)

    # Prefer the first plausible multi-word person name. This is intentionally
    # conservative so unrelated OCR labels are not returned as a name.
    if candidates:
        return candidates[0]

    return None


# =========================================================
# DOB EXTRACTION
# =========================================================

def extract_dob(lines):

    patterns = [
        # 17 Nov 2004
        r"\b\d{1,2}[\s/-]+(?:[A-Za-z]{3,9}|\d{1,2})[\s,-]+\d{4}\b",

        # 17/11/2004
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b",

        # 17.11.2004
        r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"
    ]

    for i, line in enumerate(lines):

        lower = line.lower()

        if (
            "date of birth" in lower
            or "dob" in lower
            or "birth" in lower
        ):

            for pattern in patterns:

                match = re.search(
                    pattern,
                    line,
                    re.IGNORECASE
                )

                if match:
                    return match.group()

            if i + 1 < len(lines):

                next_line = lines[i + 1]

                for pattern in patterns:

                    match = re.search(
                        pattern,
                        next_line,
                        re.IGNORECASE
                    )

                    if match:
                        return match.group()

    return None


# =========================================================
# PASSPORT / ID NUMBER EXTRACTION
# =========================================================

def _normalize_dl_candidate(value):
    """Normalize common Indian driving-licence OCR variants."""
    if not value:
        return None

    value = value.upper().strip()
    # Remove OCR punctuation/spaces used between state/RTO/year/serial parts.
    compact = re.sub(r"[^A-Z0-9]", "", value)

    # Common OCR substitutions only for the numeric portion after the state code.
    # We deliberately do not globally replace O/I because that can damage letters.
    if len(compact) >= 8 and re.fullmatch(r"[A-Z]{2}[0-9A-Z]+", compact):
        state = compact[:2]
        rest = compact[2:]
        rest = rest.replace("O", "0").replace("I", "1")
        compact = state + rest

    return compact


def _is_driving_licence_number(value):
    """Indian DL number: state(2 letters)+RTO(2 digits)+year(4 digits)+serial(4-8 digits)."""
    compact = _normalize_dl_candidate(value)
    if not compact:
        return False
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}\d{4}\d{4,8}", compact))


def _extract_dl_from_text(lines):
    """High-priority extraction for Indian Driving Licence numbers."""
    joined = "\n".join(lines)

    # 1) Look close to explicit licence-number labels.
    label_patterns = [
        r"(?:DL\s*(?:NO|NUMBER)|DRIVING\s+LICEN[CS]E\s*(?:NO|NUMBER)|LICEN[CS]E\s*(?:NO|NUMBER)|LIC\.?\s*(?:NO|NUMBER))\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{8,24})",
    ]
    for pattern in label_patterns:
        for match in re.finditer(pattern, joined, re.IGNORECASE):
            raw = match.group(1).strip()
            # Stop at obvious neighbouring field labels.
            raw = re.split(r"\b(?:DOB|DATE\s+OF\s+BIRTH|NAME|VALID|VALIDITY|BLOOD|ORGAN|ADDRESS)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip(" :-")
            if _is_driving_licence_number(raw):
                return _normalize_dl_candidate(raw)

    # 2) Search for the full DL structure even when OCR drops separators.
    candidates = re.findall(
        r"\b[A-Z]{2}[\s\-/]?\d{2}[\s\-/]?\d{4}[\s\-/]?\d{4,8}\b",
        r"\b[A-Z]{2}[\s\-/]?\d{2}[\s\-/]?\d{4}[\s\-/]?\d{3,8}\b",
        joined.upper(),
    )
    for candidate in candidates:
        if _is_driving_licence_number(candidate):
            return _normalize_dl_candidate(candidate)

    # 3) OCR may insert spaces between every block. Normalize token windows.
    tokens = re.findall(r"[A-Z0-9]+", joined.upper())
    for i in range(len(tokens)):
        for width in (2, 3, 4):
            window = tokens[i:i + width]
            if len(window) != width:
                continue
            candidate = "".join(window)
            if _is_driving_licence_number(candidate):
                return _normalize_dl_candidate(candidate)

    return None


def extract_id_number(lines, document_type=None):
    """Extract a document ID with document-specific priority.

    Driving licences are handled first when detected because their long
    state/RTO/year/serial structure is easy for generic OCR extraction to miss.
    """
    joined_upper = "\n".join(lines).upper()

    if (
        document_type == "Driving Licence"
        or "DRIVING LICENCE" in joined_upper
        or "DRIVING LICENSE" in joined_upper
    ):
        dl_number = _extract_dl_from_text(lines)
        if dl_number:
            return dl_number

    # -----------------------------------------------------
    # PASSPORT-SPECIFIC EXTRACTION
    # Indian synthetic passport numbers: K2294558
    # -----------------------------------------------------
    passport_patterns = [
        r"\b[A-Z]\d{7}\b",
        r"\b[A-Z]\d{6,8}\b"
    ]

    for line in lines:
        upper = line.upper().strip()
        for pattern in passport_patterns:
            match = re.search(pattern, upper)
            if match:
                return match.group()

    # -----------------------------------------------------
    # ID-related lines
    # -----------------------------------------------------
    for line in lines:
        upper = line.upper()
        if any(x in upper for x in ["ID", "IDENTITY", "PASSPORT", "DOCUMENT", "NUMBER", "NO."]):
            candidates = re.findall(r"\b[A-Z0-9]{6,18}\b", upper)
            for candidate in candidates:
                if (
                    re.search(r"[A-Z]", candidate)
                    and re.search(r"\d", candidate)
                    and not candidate.startswith("WWW")
                    and not re.fullmatch(r"\d{1,2}(?:\d{1,2})?\d{4}", candidate)
                ):
                    return candidate

    # -----------------------------------------------------
    # General fallback
    # -----------------------------------------------------
    for line in lines:
        candidates = re.findall(r"\b[A-Z0-9]{6,18}\b", line.upper())
        for candidate in candidates:
            if (
                re.search(r"[A-Z]", candidate)
                and re.search(r"\d", candidate)
                and not candidate.startswith("WWW")
            ):
                return candidate

    return None


# =========================================================
# VALIDITY EXTRACTION
# =========================================================

def extract_validity(lines):

    patterns = [

        # 2024-2028
        r"\b\d{4}\s*[-/]\s*\d{4}\b",

        # 2024.2028
        r"\b\d{4}\s*\.\s*\d{4}\b",

        # 17 Nov 2034
        r"\b\d{1,2}[\s/-]+(?:[A-Za-z]{3,9}|\d{1,2})[\s,-]+\d{4}\b",

        # 17/11/2034
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b"
    ]

    for i, line in enumerate(lines):

        lower = line.lower()

        if (
            "validity" in lower
            or "valid until" in lower
            or "expiry" in lower
            or "expiration" in lower
            or "expires" in lower
        ):

            for pattern in patterns:

                match = re.search(
                    pattern,
                    line,
                    re.IGNORECASE
                )

                if match:
                    return match.group()

            if i + 1 < len(lines):

                next_line = lines[i + 1]

                for pattern in patterns:

                    match = re.search(
                        pattern,
                        next_line,
                        re.IGNORECASE
                    )

                    if match:
                        return match.group()

    return None


# =========================================================
# DOCUMENT VALIDATION
# =========================================================

DOCUMENT_NUMBER_PATTERNS = {
    "Passport": [
        r"^[A-Z][0-9]{7}$",          # Indian passport pattern used by reference dataset
    ],
    "Voter ID": [
        r"^[A-Z]{3}[0-9]{7}$",       # Common EPIC-style pattern
    ],
    "Aadhaar / National ID": [
        r"^[0-9]{12}$",
    ],
    "Driving Licence": [
        r"^[A-Z]{2}[0-9A-Z/-]{8,18}$",
    ],
    "Student ID": [
        r"^[A-Z0-9][A-Z0-9/-]{5,19}$",
    ],
    "Visa": [
        r"^[A-Z0-9][A-Z0-9/-]{5,19}$",
    ],
}

KNOWN_NATIONALITIES = {
    "INDIAN", "INDIA", "IND",
    "AMERICAN", "USA", "UNITED STATES", "US",
    "BRITISH", "UK", "UNITED KINGDOM",
    "CANADIAN", "CANADA", "AUSTRALIAN", "AUSTRALIA",
    "GERMAN", "GERMANY", "FRENCH", "FRANCE",
    "ITALIAN", "ITALY", "SPANISH", "SPAIN",
    "JAPANESE", "JAPAN", "CHINESE", "CHINA",
    "NEPALESE", "NEPAL", "BHUTANESE", "BHUTAN",
    "BANGLADESHI", "BANGLADESH", "PAKISTANI", "PAKISTAN",
    "SRI LANKAN", "SRI LANKA", "SINGAPOREAN", "SINGAPORE",
    "MALAYSIAN", "MALAYSIA", "EMIRATI", "UAE",
}

def normalize_field_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()

def parse_date_value(value):
    """Parse common OCR date formats into a real datetime.date."""
    if not value:
        return None

    raw = normalize_field_text(value)
    raw = raw.replace(",", " ")

    formats = [
        "%d %b %Y", "%d %B %Y",
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    # OCR sometimes produces a date embedded in surrounding text.
    patterns = [
        r"\b\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{4}\b",
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            for fmt in formats:
                try:
                    return datetime.strptime(match.group(), fmt).date()
                except ValueError:
                    pass

    return None

def parse_validity_range(validity):
    """Return (start_date, end_date) when a validity range can be parsed."""
    if not validity:
        return None, None

    raw = normalize_field_text(validity)

    # Full date range: 01/01/2024 - 01/01/2034
    date_matches = re.findall(
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b",
        raw
    )
    if len(date_matches) >= 2:
        start = parse_date_value(date_matches[0])
        end = parse_date_value(date_matches[1])
        if start and end:
            return start, end

    # Month-name dates
    month_matches = re.findall(
        r"\b\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{4}\b",
        raw
    )
    if len(month_matches) >= 2:
        start = parse_date_value(month_matches[0])
        end = parse_date_value(month_matches[1])
        if start and end:
            return start, end

    # Year-only range: 2024-2027
    year_match = re.search(r"\b(19|20)\d{2}\s*[-/.]\s*((?:19|20)\d{2})\b", raw)
    if year_match:
        start_year = int(year_match.group(1) + raw[year_match.start()+2:year_match.start()+4]) if False else None
        # Use a second, simpler extraction because the grouped regex above
        # intentionally validates the century.
        years = re.findall(r"\b(?:19|20)\d{2}\b", raw)
        if len(years) >= 2:
            return datetime(int(years[0]), 1, 1).date(), datetime(int(years[1]), 12, 31).date()

    # Single expiry date
    single = parse_date_value(raw)
    if single:
        return None, single

    return None, None

def validate_document_number(document_type, id_number):
    """Validate the extracted identifier against document-type rules."""
    result = {
        "status": "NOT_CHECKED",
        "normalized": normalize_field_text(id_number),
        "reason": "Document number could not be extracted",
    }

    if not id_number:
        return result

    normalized = re.sub(r"[\s]", "", normalize_field_text(id_number))

    # OCR can produce O/0 or I/1 ambiguities, but we do NOT silently alter
    # the stored identifier. Validation remains conservative.
    patterns = DOCUMENT_NUMBER_PATTERNS.get(document_type, [])
    if not patterns:
        result.update({
            "status": "REVIEW",
            "normalized": normalized,
            "reason": f"No strict format rule configured for {document_type}",
        })
        return result

    if any(re.fullmatch(pattern, normalized) for pattern in patterns):
        result.update({
            "status": "VALID",
            "normalized": normalized,
            "reason": f"{document_type} number matches the expected format",
        })
    else:
        result.update({
            "status": "INVALID",
            "normalized": normalized,
            "reason": f"{document_type} number does not match the expected format",
        })

    return result

def extract_nationality(lines):
    labels = ["nationality", "citizenship", "nationality/citizenship"]

    for i, line in enumerate(lines):
        lower = line.lower()
        if any(label in lower for label in labels):
            parts = re.split(r"[:\-]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

            if i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if candidate:
                    return candidate

    # Common passport OCR abbreviation.
    for line in lines:
        match = re.search(r"\bNATIONALITY\s+([A-Za-z][A-Za-z ]{2,30})$", line, re.I)
        if match:
            return match.group(1).strip()

    return None

def validate_nationality(nationality):
    if not nationality:
        return {
            "status": "NOT_CHECKED",
            "value": None,
            "reason": "Nationality was not reliably extracted",
        }

    value = normalize_field_text(nationality)
    compact = re.sub(r"[^A-Z ]", "", value).strip()

    if compact in KNOWN_NATIONALITIES:
        return {
            "status": "VALID",
            "value": nationality,
            "reason": "Nationality value is recognized",
        }

    # Don't reject an unfamiliar but plausible nationality because OCR can
    # return a valid country adjective not included in the compact list.
    if re.fullmatch(r"[A-Z][A-Z ]{2,30}", compact):
        return {
            "status": "REVIEW",
            "value": nationality,
            "reason": "Nationality was extracted but could not be confidently matched to the built-in country list",
        }

    return {
        "status": "INVALID",
        "value": nationality,
        "reason": "Extracted nationality contains an invalid value",
    }

def validate_document(validity, document_type="Unknown Document",
                      id_number=None, nationality=None, dob=None, name=None):
    """
    Structured document validation.

    Important:
    - Missing optional OCR fields do not automatically mean a document is fake.
    - Date validation uses the actual current date, not only the current year.
    - Format checks are document-type specific.
    """
    today = datetime.now().date()
    findings = []
    checks = []

    # ---- Required identity fields ----
    if name:
        checks.append({"field": "Name", "status": "VALID", "reason": "Name extracted"})
    else:
        checks.append({"field": "Name", "status": "REVIEW", "reason": "Name could not be reliably extracted"})

    if dob:
        parsed_dob = parse_date_value(dob)
        if not parsed_dob:
            checks.append({"field": "Date of birth", "status": "REVIEW", "reason": "Date of birth format could not be parsed"})
        elif parsed_dob >= today:
            checks.append({"field": "Date of birth", "status": "INVALID", "reason": "Date of birth cannot be today or in the future"})
        else:
            checks.append({"field": "Date of birth", "status": "VALID", "reason": "Date of birth is a plausible past date"})
    else:
        checks.append({"field": "Date of birth", "status": "REVIEW", "reason": "Date of birth was not extracted"})

    # ---- Document number ----
    number_validation = validate_document_number(document_type, id_number)
    checks.append({
        "field": "Document number",
        "status": number_validation["status"],
        "reason": number_validation["reason"],
    })

    # ---- Nationality ----
    nationality_validation = validate_nationality(nationality)
    if nationality:
        checks.append({
            "field": "Nationality",
            "status": nationality_validation["status"],
            "reason": nationality_validation["reason"],
        })

    # ---- Expiry / validity ----
    if not validity:
        validity_status = "UNKNOWN"
        validity_reason = "Validity information not found"
        checks.append({
            "field": "Validity",
            "status": validity_status,
            "reason": validity_reason,
        })
    else:
        start_date, end_date = parse_validity_range(validity)

        if start_date and end_date:
            if start_date > end_date:
                validity_status = "INVALID"
                validity_reason = "Validity start date is after the expiry date"
            elif today < start_date:
                validity_status = "NOT_YET_VALID"
                validity_reason = "Document validity has not started"
            elif today > end_date:
                validity_status = "EXPIRED"
                validity_reason = "Document validity has expired"
            else:
                validity_status = "VALID"
                validity_reason = "Document is currently valid"
        elif end_date:
            if today > end_date:
                validity_status = "EXPIRED"
                validity_reason = "Document expiry date has passed"
            else:
                validity_status = "VALID"
                validity_reason = "Document expiry date has not passed"
        else:
            validity_status = "UNKNOWN"
            validity_reason = "Validity format could not be parsed"

        checks.append({
            "field": "Validity",
            "status": validity_status,
            "reason": validity_reason,
            "start_date": start_date.isoformat() if start_date else None,
            "expiry_date": end_date.isoformat() if end_date else None,
        })

    # ---- Overall status ----
    statuses = [c["status"] for c in checks]
    if "INVALID" in statuses or validity_status == "INVALID":
        overall = "INVALID"
    elif validity_status == "EXPIRED":
        overall = "EXPIRED"
    elif validity_status == "NOT_YET_VALID":
        overall = "NOT_YET_VALID"
    elif "VALID" in statuses and all(
        s not in {"INVALID", "EXPIRED"} for s in statuses
    ):
        # Unknown/review fields keep the document from being called fully valid.
        overall = "VALID" if not any(s == "REVIEW" for s in statuses) else "REVIEW"
    else:
        overall = "UNKNOWN"

    for check in checks:
        if check["status"] in {"INVALID", "EXPIRED", "NOT_YET_VALID", "REVIEW"}:
            findings.append(check["reason"])

    return {
        "status": overall,
        "reason": findings[0] if findings else "Document validation checks passed",
        "checks": checks,
        "document_type": document_type,
        "document_number": number_validation,
        "nationality": nationality_validation,
        "expiry": {
            "start_date": checks[-1].get("start_date") if checks else None,
            "expiry_date": checks[-1].get("expiry_date") if checks else None,
            "status": validity_status,
        },
        "findings": findings,
    }


# =========================================================
# OCR CONFIDENCE
# =========================================================

def analyze_ocr_confidence(image):

    try:

        data = pytesseract.image_to_data(
            image,
            lang="eng",
            config="--psm 6",
            output_type=Output.DICT
        )

        confidences = []

        for value in data["conf"]:

            try:

                confidence = float(value)

                if confidence >= 0:
                    confidences.append(confidence)

            except:
                pass

        if not confidences:

            return {
                "average_confidence": 0,
                "status": "LOW"
            }

        average = round(
            sum(confidences) / len(confidences),
            2
        )

        if average >= 85:
            status = "HIGH"

        elif average >= 65:
            status = "MEDIUM"

        else:
            status = "LOW"

        return {
            "average_confidence": average,
            "status": status
        }

    except Exception as e:

        return {
            "average_confidence": 0,
            "status": "UNKNOWN",
            "error": str(e)
        }


# =========================================================
# IMAGE QUALITY
# =========================================================

def analyze_image_quality(image):

    width, height = image.size

    score = 0
    indicators = []

    if width < 600 or height < 600:

        score += 15

        indicators.append(
            "Low image resolution"
        )

    if width >= 800 and height >= 1000:

        indicators.append(
            "Image resolution is acceptable"
        )

    gray = cv2.cvtColor(
        np.array(image),
        cv2.COLOR_RGB2GRAY
    )

    blur_value = cv2.Laplacian(
        gray,
        cv2.CV_64F
    ).var()

    if blur_value < 80:

        score += 10

        indicators.append(
            "Image may be blurry"
        )

    else:

        indicators.append(
            "Image sharpness is acceptable"
        )

    return {
        "score": min(score, 25),
        "width": width,
        "height": height,
        "blur_score": round(
            float(blur_value),
            2
        ),
        "indicators": indicators
    }


# =========================================================
# ELA
# =========================================================

def perform_ela(image):

    try:

        rgb_image = image.convert("RGB")

        temp = BytesIO()

        rgb_image.save(
            temp,
            format="JPEG",
            quality=90
        )

        temp.seek(0)

        recompressed = Image.open(
            temp
        ).convert("RGB")

        diff = ImageChops.difference(
            rgb_image,
            recompressed
        )

        diff = ImageEnhance.Brightness(
            diff
        ).enhance(10)

        diff_array = np.array(diff)

        mean_error = float(
            np.mean(diff_array)
        )

        max_error = int(
            np.max(diff_array)
        )

        if mean_error > 8:

            status = "SUSPICIOUS"
            score = 30

        elif mean_error > 4:

            status = "REVIEW"
            score = 15

        else:

            status = "NORMAL"
            score = 0

        return {
            "status": status,
            "score": score,
            "average_error": round(
                mean_error,
                2
            ),
            "max_error": max_error
        }

    except Exception as e:

        return {
            "status": "UNAVAILABLE",
            "score": 0,
            "average_error": 0,
            "max_error": 0,
            "error": str(e)
        }


# =========================================================
# METADATA
# =========================================================

def analyze_metadata(original_image):

    try:

        exif = original_image.getexif()

        if not exif:

            return {
                "status": "LIMITED",
                "score": 0,
                "indicators": [
                    "No EXIF metadata available"
                ]
            }

        metadata = {}

        for key, value in exif.items():

            tag = ExifTags.TAGS.get(
                key,
                str(key)
            )

            metadata[tag] = str(value)

        return {
            "status": "AVAILABLE",
            "score": 0,
            "fields_found": list(
                metadata.keys()
            )[:15],
            "indicators": [
                "EXIF metadata is available"
            ]
        }

    except Exception as e:

        return {
            "status": "UNKNOWN",
            "score": 0,
            "indicators": [
                "Metadata could not be read"
            ],
            "error": str(e)
        }


# =========================================================
# TEXT CONSISTENCY
# =========================================================

def analyze_text_consistency(
    ocr_confidence,
    name,
    dob,
    id_number,
    validity
):

    score = 0
    indicators = []

    confidence = ocr_confidence[
        "average_confidence"
    ]

    if confidence < 50:

        score += 20

        indicators.append(
            "Low OCR confidence"
        )

    elif confidence < 70:

        score += 10

        indicators.append(
            "Moderate OCR confidence"
        )

    else:

        indicators.append(
            "OCR confidence is acceptable"
        )

    if not name:

        score += 10

        indicators.append(
            "Name could not be reliably extracted"
        )

    if not dob:

        score += 5

        indicators.append(
            "Date of birth not detected"
        )

    if not id_number:

        score += 10

        indicators.append(
            "Document ID not detected"
        )

    if not validity:

        score += 5

        indicators.append(
            "Validity information not detected"
        )

    if score >= 25:

        status = "SUSPICIOUS"

    elif score >= 10:

        status = "REVIEW"

    else:

        status = "NORMAL"

    return {
        "status": status,
        "score": min(score, 30),
        "overall_confidence": confidence,
        "indicators": indicators
    }


# =========================================================
# ADVANCED TAMPERING / INTEGRITY ENGINE
# =========================================================


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        if np.isfinite(value):
            return value
    except Exception:
        pass
    return default


def _score_outlier(value, median, mad, direction="high"):
    """Robust outlier score using median/MAD instead of fixed global thresholds."""
    scale = max(1.4826 * abs(mad), 1.0)
    z = (value - median) / scale
    if direction == "abs":
        z = abs(z)
    elif direction == "low":
        z = -z
    return max(0.0, min(100.0, (z - 1.5) * 25.0))


def _region_metrics(gray, ela_gray, x1, y1, x2, y2):
    crop = gray[y1:y2, x1:x2]
    ela_crop = ela_gray[y1:y2, x1:x2]
    if crop.size == 0 or ela_crop.size == 0:
        return {"ela_mean": 0.0, "noise": 0.0, "edge_density": 0.0}

    edges = cv2.Canny(crop, 80, 160)
    edge_density = float(np.mean(edges > 0) * 100.0)
    noise = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    ela_mean = float(np.mean(ela_crop))

    return {
        "ela_mean": ela_mean,
        "noise": noise,
        "edge_density": edge_density,
    }


def analyze_local_regions(image):
    """Find *relative* suspicious regions rather than assigning one score to the whole image."""
    result = {
        "status": "NORMAL",
        "score": 0,
        "grid": "4x4",
        "regions_analyzed": 0,
        "suspicious_regions": [],
        "indicators": [],
    }

    try:
        rgb = image.convert("RGB")
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        # Recompress only for ELA comparison. The important signal here is
        # regional deviation from the document's own baseline, not raw ELA.
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=90)
        buffer.seek(0)
        recompressed = np.array(Image.open(buffer).convert("RGB"))
        diff = cv2.absdiff(arr, recompressed)
        ela_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY).astype(np.float32)
        ela_gray = cv2.GaussianBlur(ela_gray, (3, 3), 0)

        h, w = gray.shape[:2]
        cols, rows = 4, 4
        metrics = []

        for row in range(rows):
            for col in range(cols):
                x1 = int(col * w / cols)
                y1 = int(row * h / rows)
                x2 = int((col + 1) * w / cols)
                y2 = int((row + 1) * h / rows)
                m = _region_metrics(gray, ela_gray, x1, y1, x2, y2)
                m.update({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})
                metrics.append(m)

        result["regions_analyzed"] = len(metrics)

        ela_values = np.array([m["ela_mean"] for m in metrics], dtype=np.float32)
        noise_values = np.array([m["noise"] for m in metrics], dtype=np.float32)
        edge_values = np.array([m["edge_density"] for m in metrics], dtype=np.float32)

        ela_med, ela_mad = float(np.median(ela_values)), float(np.median(np.abs(ela_values - np.median(ela_values))))
        noise_med, noise_mad = float(np.median(noise_values)), float(np.median(np.abs(noise_values - np.median(noise_values))))
        edge_med, edge_mad = float(np.median(edge_values)), float(np.median(np.abs(edge_values - np.median(edge_values))))

        for m in metrics:
            ela_score = _score_outlier(m["ela_mean"], ela_med, ela_mad, "high")
            noise_score = _score_outlier(m["noise"], noise_med, noise_mad, "abs")
            edge_score = _score_outlier(m["edge_density"], edge_med, edge_mad, "abs")
            # ELA is strongest signal; noise/edge are supporting evidence.
            m["anomaly_score"] = round(0.60 * ela_score + 0.25 * noise_score + 0.15 * edge_score, 2)

        ranked = sorted(metrics, key=lambda item: item["anomaly_score"], reverse=True)
        suspicious = []
        for m in ranked[:6]:
            if m["anomaly_score"] >= 55:
                suspicious.append({
                    "x": m["x"], "y": m["y"], "width": m["w"], "height": m["h"],
                    "score": m["anomaly_score"],
                    "signals": {
                        "ela": round(m["ela_mean"], 2),
                        "noise": round(m["noise"], 2),
                        "edge_density": round(m["edge_density"], 2),
                    },
                    "reason": "Region differs from the document's local compression/texture baseline",
                })

        result["suspicious_regions"] = suspicious
        result["score"] = min(35, int(round(sum(r["score"] for r in suspicious) / max(len(suspicious), 1) * 0.35))) if suspicious else 0

        if len(suspicious) >= 3:
            result["status"] = "SUSPICIOUS"
            result["indicators"].append(f"{len(suspicious)} local regions show abnormal compression/texture patterns")
        elif suspicious:
            result["status"] = "REVIEW"
            result["indicators"].append("A local region shows an abnormal compression/texture pattern")
        else:
            result["indicators"].append("No strong local-region outlier detected")

        return result

    except Exception as e:
        result["status"] = "UNAVAILABLE"
        result["indicators"] = ["Local region analysis could not be completed"]
        result["error"] = str(e)
        return result


def analyze_text_regions(image):
    """Check OCR text boxes for region-level outliers; missing OCR fields are NOT treated as tampering."""
    result = {
        "status": "NOT_AVAILABLE",
        "score": 0,
        "text_regions_analyzed": 0,
        "suspicious_regions": [],
        "indicators": [],
    }

    try:
        rgb = image.convert("RGB")
        data = pytesseract.image_to_data(rgb, lang="eng", config="--psm 6", output_type=Output.DICT)
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        # Build an ELA map once.
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=90)
        buffer.seek(0)
        recompressed = np.array(Image.open(buffer).convert("RGB"))
        diff = cv2.absdiff(arr, recompressed)
        ela = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY).astype(np.float32)
        ela = cv2.GaussianBlur(ela, (3, 3), 0)

        regions = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            try:
                conf = float(data["conf"][i])
                x, y = int(data["left"][i]), int(data["top"][i])
                w, h = int(data["width"][i]), int(data["height"][i])
            except Exception:
                continue
            if not text or conf < 45 or w < 8 or h < 5:
                continue
            pad = max(3, int(min(w, h) * 0.35))
            x1, y1 = max(0, x - pad), max(0, y - pad)
            x2, y2 = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
            crop = ela[y1:y2, x1:x2]
            if crop.size:
                regions.append({
                    "x": x1, "y": y1, "width": x2-x1, "height": y2-y1,
                    "text": text[:40], "ocr_confidence": round(conf, 1),
                    "ela": float(np.mean(crop)),
                })

        result["text_regions_analyzed"] = len(regions)
        if len(regions) < 3:
            result["indicators"] = ["Not enough reliable OCR text regions for relative comparison"]
            return result

        values = np.array([r["ela"] for r in regions], dtype=np.float32)
        med = float(np.median(values))
        mad = float(np.median(np.abs(values - med)))

        suspicious = []
        for r in regions:
            s = _score_outlier(r["ela"], med, mad, "high")
            if s >= 60:
                suspicious.append({
                    "x": r["x"], "y": r["y"], "width": r["width"], "height": r["height"],
                    "score": round(s, 2),
                    "ocr_confidence": r["ocr_confidence"],
                    "reason": "Text region has an unusually high compression residual compared with other text regions",
                })

        result["suspicious_regions"] = suspicious[:5]
        result["score"] = min(20, len(suspicious) * 7)

        if len(suspicious) >= 2:
            result["status"] = "SUSPICIOUS"
            result["indicators"].append(f"{len(suspicious)} text regions differ from the document's text-region baseline")
        elif suspicious:
            result["status"] = "REVIEW"
            result["indicators"].append("One text region differs from the document's text-region baseline")
        else:
            result["status"] = "NORMAL"
            result["indicators"].append("Text-region compression patterns are consistent")

        return result

    except Exception as e:
        result["status"] = "UNAVAILABLE"
        result["indicators"] = ["Text-region analysis could not be completed"]
        result["error"] = str(e)
        return result


def analyze_photo_region(image):
    """Conservative photo-region check. It reports inconsistency, not a definitive photo swap."""
    result = {
        "status": "NOT_AVAILABLE",
        "score": 0,
        "face_detected": False,
        "face_box": None,
        "indicators": [],
    }

    try:
        faces = _detect_yunet_faces(image) if YUNET_DETECTOR is not None else []
        if not faces:
            result["indicators"] = ["No document face detected for photo-region analysis"]
            return result

        face = faces[0]
        result["face_detected"] = True
        x, y, w, h = [int(face[k]) for k in ("x", "y", "width", "height")]
        result["face_box"] = {"x": x, "y": y, "width": w, "height": h}

        rgb = image.convert("RGB")
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=90)
        buffer.seek(0)
        recompressed = np.array(Image.open(buffer).convert("RGB"))
        ela = cv2.cvtColor(cv2.absdiff(arr, recompressed), cv2.COLOR_RGB2GRAY).astype(np.float32)

        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(gray.shape[1], x+w), min(gray.shape[0], y+h)
        face_crop = ela[y1:y2, x1:x2]
        if face_crop.size == 0:
            return result

        # Compare face with a ring immediately outside it. A genuine printed
        # portrait can differ naturally, so the threshold is deliberately conservative.
        pad = max(8, int(min(w, h) * 0.35))
        ox1, oy1 = max(0, x-pad), max(0, y-pad)
        ox2, oy2 = min(gray.shape[1], x+w+pad), min(gray.shape[0], y+h+pad)
        outer = ela[oy1:oy2, ox1:ox2]
        outer_mean = float(np.mean(outer)) if outer.size else 0.0
        face_mean = float(np.mean(face_crop))
        ratio = face_mean / max(outer_mean, 0.5)

        if ratio >= 2.4:
            result["status"] = "REVIEW"
            result["score"] = 12
            result["indicators"].append("Document photo region has a strong compression residual difference from its surrounding region")
        else:
            result["status"] = "NORMAL"
            result["indicators"].append("Document photo region is not a strong compression outlier")

        result["face_ela"] = round(face_mean, 2)
        result["surrounding_ela"] = round(outer_mean, 2)
        result["ela_ratio"] = round(ratio, 2)
        return result

    except Exception as e:
        result["status"] = "UNAVAILABLE"
        result["indicators"] = ["Photo-region analysis could not be completed"]
        result["error"] = str(e)
        return result


def analyze_metadata(original_image):
    """Metadata is supporting evidence only; absence of EXIF is NOT a tampering penalty."""
    try:
        exif = original_image.getexif()
        if not exif:
            return {
                "status": "LIMITED",
                "score": 0,
                "indicators": ["No EXIF metadata available; metadata evidence is limited"],
            }

        metadata = {}
        for key, value in exif.items():
            tag = ExifTags.TAGS.get(key, str(key))
            metadata[tag] = str(value)

        suspicious_software = metadata.get("Software", "")
        score = 0
        indicators = ["EXIF metadata is available"]
        if suspicious_software:
            software_lower = suspicious_software.lower()
            editing_terms = ["photoshop", "gimp", "paint.net", "lightroom", "canva", "affinity"]
            if any(term in software_lower for term in editing_terms):
                score = 10
                indicators.append(f"Image metadata reports editing software: {suspicious_software}")

        return {
            "status": "REVIEW" if score else "AVAILABLE",
            "score": score,
            "fields_found": list(metadata.keys())[:15],
            "indicators": indicators,
        }
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "score": 0,
            "indicators": ["Metadata could not be read"],
            "error": str(e),
        }


def analyze_text_consistency(
    ocr_confidence,
    name,
    dob,
    id_number,
    validity
):
    """Field extraction quality is kept separate from tampering evidence."""
    confidence = _safe_float(ocr_confidence.get("average_confidence", 0))
    missing = []
    if not name: missing.append("name")
    if not dob: missing.append("date of birth")
    if not id_number: missing.append("document ID")
    if not validity: missing.append("validity")

    if confidence >= 85 and not missing:
        status = "NORMAL"
    elif confidence >= 65:
        status = "REVIEW"
    else:
        status = "LIMITED"

    indicators = ["OCR field extraction quality is acceptable" if status == "NORMAL" else "OCR field extraction quality needs review"]
    if missing:
        indicators.append("Fields not reliably extracted: " + ", ".join(missing))

    return {
        "status": status,
        "score": 0,
        "overall_confidence": confidence,
        "missing_fields": missing,
        "indicators": indicators,
    }


def run_tampering_analysis(
    image,
    original_image,
    ocr_confidence,
    name,
    dob,
    id_number,
    validity
):
    """Multi-signal integrity engine with independent regional evidence.

    Important: this score is NOT the overall screening risk score. It is only
    the document-integrity/tampering evidence score. OCR/reference/face risk
    is calculated separately by the main risk engine.
    """
    local_regions = analyze_local_regions(image)
    text_regions = analyze_text_regions(image)
    photo_region = analyze_photo_region(image)
    metadata = analyze_metadata(original_image)
    text_consistency = analyze_text_consistency(
        ocr_confidence, name, dob, id_number, validity
    )

    # Global ELA is deliberately capped and used only as supporting evidence.
    # This prevents one whole-image compression number from dominating the result.
    try:
        rgb = image.convert("RGB")
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        recompressed = Image.open(buf).convert("RGB")
        diff = ImageChops.difference(rgb, recompressed)
        stat = ImageStat.Stat(diff)
        mean_error = float(sum(stat.mean) / len(stat.mean))
        global_ela_score = min(15, int(round(max(0, mean_error - 3.0) * 1.5)))
        global_ela_status = "REVIEW" if global_ela_score >= 8 else "NORMAL"
        ela = {
            "status": global_ela_status,
            "score": global_ela_score,
            "average_error": round(mean_error, 2),
            "reason": "Global compression residual used as supporting evidence only",
        }
    except Exception as e:
        ela = {"status": "UNAVAILABLE", "score": 0, "average_error": 0, "error": str(e)}

    components = {
        "global_ela": ela,
        "ela": ela,  # backward-compatible UI key
        "local_regions": local_regions,
        "text_regions": text_regions,
        "photo_region": photo_region,
        "text_consistency": text_consistency,
        "metadata": metadata,
    }

    component_scores = {
        "global_ela": ela.get("score", 0),
        "local_regions": local_regions.get("score", 0),
        "text_regions": text_regions.get("score", 0),
        "photo_region": photo_region.get("score", 0),
        "metadata": metadata.get("score", 0),
    }

    total_score = min(100, sum(component_scores.values()))

    evidence_count = sum([
        local_regions.get("status") in {"REVIEW", "SUSPICIOUS"},
        text_regions.get("status") in {"REVIEW", "SUSPICIOUS"},
        photo_region.get("status") == "REVIEW",
        metadata.get("status") == "REVIEW",
    ])

    # Classification is based on evidence strength; confidence describes how
    # much of the analysis pipeline actually ran, NOT how suspicious the file is.
    # A clean document can therefore be NORMAL with HIGH analysis confidence.
    coverage = 0
    if local_regions.get("regions_analyzed", 0) >= 12:
        coverage += 1
    if text_regions.get("text_regions_analyzed", 0) >= 3:
        coverage += 1
    if photo_region.get("face_detected"):
        coverage += 1
    if metadata.get("status") in {"AVAILABLE", "LIMITED", "REVIEW"}:
        coverage += 1

    analysis_confidence = "HIGH" if coverage >= 3 else ("MEDIUM" if coverage >= 2 else "LOW")

    # Conservative classification: one weak signal should not become HIGH_RISK.
    if total_score >= 60 and evidence_count >= 2:
        status = "HIGH_RISK"
    elif total_score >= 30 and evidence_count >= 1:
        status = "REVIEW"
    elif total_score >= 15:
        status = "LOW_RISK"
    else:
        status = "NORMAL"

    confidence = analysis_confidence

    indicators = []
    for group in (local_regions, text_regions, photo_region, metadata):
        indicators.extend(group.get("indicators", []))

    return {
        "status": status,
        "score": int(total_score),
        "confidence": confidence,
        "indicators": indicators,
        "component_scores": component_scores,
        "evidence_count": evidence_count,
        "components": components,
    }


# =========================================================
# MONGODB HELPERS
# =========================================================

def normalize_text(value):

    if value is None:
        return ""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value).upper()
    )


# =========================================================
# COMPARE WITH REFERENCE PASSPORT
# =========================================================

def compare_reference_document(
    reference,
    extracted_name,
    extracted_dob,
    extracted_id,
    extracted_validity
):

    matches = []
    mismatches = []

    # -----------------------------------------------------
    # PASSPORT NUMBER
    # -----------------------------------------------------

    reference_passport = normalize_text(
        reference.get(
            "passport_number"
        )
    )

    uploaded_passport = normalize_text(
        extracted_id
    )

    if (
        uploaded_passport
        and reference_passport
    ):

        if (
            uploaded_passport
            == reference_passport
        ):

            matches.append(
                "Passport number"
            )

        else:

            mismatches.append({
                "field": "passport_number",
                "uploaded": extracted_id,
                "reference": reference.get(
                    "passport_number"
                )
            })

    # -----------------------------------------------------
    # NAME
    # -----------------------------------------------------

    reference_name = normalize_text(
        f"{reference.get('given_name', '')} "
        f"{reference.get('surname', '')}"
    )

    uploaded_name = normalize_text(
        extracted_name
    )

    if (
        uploaded_name
        and reference_name
    ):

        if (
            uploaded_name in reference_name
            or reference_name in uploaded_name
        ):

            matches.append(
                "Name"
            )

        else:

            mismatches.append({
                "field": "name",
                "uploaded": extracted_name,
                "reference": (
                    f"{reference.get('given_name', '')} "
                    f"{reference.get('surname', '')}"
                )
            })

    # -----------------------------------------------------
    # DATE OF BIRTH
    # -----------------------------------------------------

    if extracted_dob:

        reference_dob = normalize_text(
            reference.get(
                "date_of_birth"
            )
        )

        uploaded_dob = normalize_text(
            extracted_dob
        )

        if (
            uploaded_dob
            and reference_dob
            and uploaded_dob == reference_dob
        ):

            matches.append(
                "Date of birth"
            )

        elif reference_dob:

            mismatches.append({
                "field": "date_of_birth",
                "uploaded": extracted_dob,
                "reference": reference.get(
                    "date_of_birth"
                )
            })

    # -----------------------------------------------------
    # EXPIRY DATE
    # -----------------------------------------------------

    reference_expiry = normalize_text(
        reference.get(
            "date_of_expiry"
        )
    )

    uploaded_validity = normalize_text(
        extracted_validity
    )

    if (
        reference_expiry
        and uploaded_validity
    ):

        if reference_expiry in uploaded_validity:

            matches.append(
                "Expiry date"
            )

        # Don't automatically mark mismatch
        # because validity can be displayed
        # in different formats.

    # -----------------------------------------------------
    # MATCH PERCENTAGE
    # -----------------------------------------------------

    total_checked = (
        len(matches)
        + len(mismatches)
    )

    if total_checked == 0:

        match_percentage = 0

    else:

        match_percentage = round(
            (
                len(matches)
                / total_checked
            ) * 100
        )

    # -----------------------------------------------------
    # FINAL VERIFICATION STATUS
    # -----------------------------------------------------

    if (
        len(mismatches) == 0
        and len(matches) >= 2
    ):

        verification_status = "MATCH"

    elif len(matches) >= 1:

        verification_status = "PARTIAL_MATCH"

    else:

        verification_status = "MISMATCH"

    return {
        "status": verification_status,
        "match_percentage": match_percentage,
        "matched_fields": matches,
        "mismatched_fields": mismatches
    }


# =========================================================
# REFERENCE DATABASE SEARCH
# =========================================================

def verify_against_reference(
    name,
    dob,
    id_number,
    validity
):

    # -----------------------------------------------------
    # ID NOT FOUND
    # -----------------------------------------------------

    if not id_number:

        return {
            "status": "NOT_CHECKED",
            "reason": (
                "Passport/document number "
                "could not be extracted"
            ),
            "reference_found": False
        }

    clean_id = normalize_text(
        id_number
    )

    # -----------------------------------------------------
    # EXACT SEARCH
    # -----------------------------------------------------

    reference = reference_passports.find_one(
        {
            "passport_number": clean_id
        }
    )

    # -----------------------------------------------------
    # CASE-INSENSITIVE SEARCH
    # -----------------------------------------------------

    if not reference:

        reference = reference_passports.find_one(
            {
                "passport_number": {
                    "$regex": (
                        f"^{re.escape(clean_id)}$"
                    ),
                    "$options": "i"
                }
            }
        )

    # -----------------------------------------------------
    # NOT FOUND
    # -----------------------------------------------------

    if not reference:

        return {
            "status": "NO_MATCH",
            "reason": (
                "No reference passport "
                "found in database"
            ),
            "reference_found": False,
            "searched_passport_number": id_number
        }

    # -----------------------------------------------------
    # COMPARE
    # -----------------------------------------------------

    comparison = compare_reference_document(
        reference=reference,
        extracted_name=name,
        extracted_dob=dob,
        extracted_id=id_number,
        extracted_validity=validity
    )

    # Remove MongoDB internal _id
    reference_data = {
        key: value
        for key, value in reference.items()
        if key != "_id"
    }

    return {
        "status": comparison["status"],
        "reason": "Reference passport found",
        "reference_found": True,
        "searched_passport_number": id_number,
        "reference_document": reference_data,
        "match_percentage": comparison[
            "match_percentage"
        ],
        "matched_fields": comparison[
            "matched_fields"
        ],
        "mismatched_fields": comparison[
            "mismatched_fields"
        ]
    }


# =========================================================
# RISK ENGINE
# =========================================================

def calculate_risk(
    validation,
    tampering,
    reference_verification=None,
    face_verification=None,
    ocr_confidence=None,
    image_quality=None,
    document_type=None,
    person_photo_supplied=False,
    extracted_text=""
):
    """
    Structured explainable screening-risk engine.

    Risk policy:
    - A clean, successfully verified document starts at 15/100.
    - Positive verification signals do NOT add risk.
    - Suspicious/failed signals add risk according to severity.
    - Face mismatch is a strong risk signal because the person photo is
      compared directly with the photo printed on the uploaded document.
    - Reference database risk is used only when reference verification is
      actually applicable.
    """
    reference_verification = reference_verification or {}
    face_verification = face_verification or {}
    ocr_confidence = ocr_confidence or {}
    image_quality = image_quality or {}
    contributors = []

    # Clean baseline for a successfully screened case.
    BASELINE_RISK = 15

    def add(source, points, reason, severity="INFO"):
        points = int(max(0, points))
        if points:
            contributors.append({
                "source": source,
                "points": points,
                "reason": reason,
                "severity": severity
            })

    # ---------------------------------------------------------
    # 1. TAMPERING / DOCUMENT INTEGRITY
    # ---------------------------------------------------------
    tampering_score = int(tampering.get("score", 0) or 0)
    tampering_status = str(tampering.get("status", "NORMAL")).upper()

    # Do not blindly add the complete tampering score to overall risk.
    # Tampering is converted into controlled risk bands so one noisy ELA
    # measurement cannot dominate the final screening decision.
    tampering_points_map = {
        "NORMAL": 0,
        "LOW_RISK": 5,
        "REVIEW": 15,
        "SUSPICIOUS": 25,
        "HIGH_RISK": 35,
        "UNAVAILABLE": 0,
        "NOT_AVAILABLE": 0,
    }
    tampering_points = tampering_points_map.get(tampering_status, 0)

    # If a numeric score is available but the status is missing, use a
    # conservative band rather than treating the raw score as final risk.
    if tampering_status not in tampering_points_map:
        if tampering_score >= 60:
            tampering_points = 35
        elif tampering_score >= 30:
            tampering_points = 15
        elif tampering_score >= 15:
            tampering_points = 5
        else:
            tampering_points = 0

    if tampering_points:
        evidence_count = int(tampering.get("evidence_count", 0) or 0)
        add(
            "Tampering analysis",
            tampering_points,
            f"{tampering_status} integrity evidence detected"
            + (f" across {evidence_count} independent source(s)" if evidence_count else ""),
            "HIGH" if tampering_points >= 25 else "MEDIUM"
        )

    # ---------------------------------------------------------
    # 2. DOCUMENT VALIDATION
    # ---------------------------------------------------------
    validation_status = str(validation.get("status", "UNKNOWN")).upper()

    validation_points_map = {
        "EXPIRED": 25,
        "NOT_YET_VALID": 20,
        "INVALID": 35,
        "UNKNOWN": 8,
        "REVIEW": 5,
    }
    validation_points = validation_points_map.get(validation_status, 0)

    if validation_points:
        add(
            "Document validation",
            validation_points,
            validation.get(
                "reason",
                "Document validation requires review"
            ),
            "HIGH" if validation_status in {"EXPIRED", "INVALID"} else "MEDIUM"
        )

    # ---------------------------------------------------------
    # 3. REFERENCE DATABASE
    # ---------------------------------------------------------
    reference_status = str(
        reference_verification.get("status", "NOT_CHECKED")
    ).upper()

    # NOT_APPLICABLE is intentionally zero-risk. For example, Student ID
    # screening should not be penalized merely because no passport reference
    # record exists.
    reference_points_map = {
        "MISMATCH": 30,
        "NO_MATCH": 20,
        "PARTIAL_MATCH": 10,
    }
    reference_points = reference_points_map.get(reference_status, 0)

    if reference_points:
        reasons = {
            "MISMATCH":
                "Reference record found but extracted identity fields do not match",
            "NO_MATCH":
                "No matching reference document was found in the database",
            "PARTIAL_MATCH":
                "Reference record found with only partial field agreement",
        }
        add(
            "Reference database",
            reference_points,
            reasons[reference_status],
            "HIGH" if reference_status == "MISMATCH" else "MEDIUM"
        )

    # ---------------------------------------------------------
    # 4. FACE VERIFICATION
    # ---------------------------------------------------------
    face_status = str(
        face_verification.get("status", "NOT_CHECKED")
    ).upper()

    face_points_map = {
        # Strong negative signal.
        "MISMATCH": 40,

        # Borderline similarity requires human review.
        "PARTIAL_MATCH": 20,
        "PARTIAL": 20,

        # Verification failures.
        "NO_DOCUMENT_FACE": 25,
        "NO_REFERENCE_FACE": 25,
        "NO_PERSON_FACE": 25,
        "MULTIPLE_PERSON_FACES": 25,
        "FACE_MODEL_UNAVAILABLE": 10,
        "FACE_VERIFICATION_ERROR": 10,
    }
    face_points = face_points_map.get(face_status, 0)

    if face_points:
        reasons = {
            "MISMATCH":
                "Person photo does not sufficiently match the photo printed on the document",
            "PARTIAL_MATCH":
                "Person-to-document face similarity is borderline and requires manual review",
            "PARTIAL":
                "Person-to-document face similarity is borderline and requires manual review",
            "NO_DOCUMENT_FACE":
                "No usable face was detected on the document",
            "NO_REFERENCE_FACE":
                "No usable document face was available for comparison",
            "NO_PERSON_FACE":
                "No usable face was detected in the person photo",
            "MULTIPLE_PERSON_FACES":
                "Multiple person faces were detected; identity verification is uncertain",
            "FACE_MODEL_UNAVAILABLE":
                "Face recognition models are unavailable",
            "FACE_VERIFICATION_ERROR":
                "Face verification encountered a processing error",
        }
        add(
            "Face verification",
            face_points,
            reasons.get(
                face_status,
                "Face verification requires review"
            ),
            "HIGH" if face_status == "MISMATCH" else "MEDIUM"
        )

    # ---------------------------------------------------------
    # 5. DOCUMENT-SPECIFIC RISK POLICY
    # ---------------------------------------------------------
    # Explicit SIH demo/business policy:
    # A Driving Licence whose holder face successfully matches the printed
    # document portrait is treated as an elevated-risk screening case.
    #
    # IMPORTANT:
    # This does NOT change the actual face-recognition result. MATCH remains
    # MATCH. It only changes the OVERALL SCREENING RISK according to the
    # configured policy requested for this workflow.
    #
    # Clean DL + MATCH:
    #   baseline 15 + policy 45 = 60 -> HIGH_RISK
    #
    # The alias handling below prevents "Driving License" vs "Driving Licence"
    # wording from accidentally bypassing the policy.
    # Prefer the explicitly detected document_type from the screening route.
    # Fall back to validation.document_type for backward compatibility.
    raw_document_type = str(
        document_type or validation.get("document_type", "")
    ).strip().lower()
    normalized_document_type = re.sub(r"[^a-z]+", " ", raw_document_type).strip()

    is_driving_licence = normalized_document_type in {
        "driving licence",
        "driving license",
        "dl",
        "indian driving licence",
        "indian driving license",
    }

    # OCR fallback: a photographed DL can occasionally be returned as a
    # generic "Document" when the heading is blurry/cropped. In that case,
    # use strong DL-specific OCR clues instead of silently bypassing policy.
    ocr_lower = str(extracted_text or "").lower()
    dl_ocr_clues = (
        "driving licence",
        "driving license",
        "indian union driving",
        "validity (nt)",
        "validity(nt)",
        "issued by uttar pradesh",
        "date of first issue",
        "holder's signature",
        "son/daughter/wife of",
    )
    dl_ocr_detected = any(clue in ocr_lower for clue in dl_ocr_clues)

    dl_screening_detected = is_driving_licence or dl_ocr_detected

    # Requested screening policy: when a DL is screened together with a
    # supplied person verification photo, the overall case must be elevated.
    # This is an overall-risk policy; it does NOT alter the face MATCH result.
    dl_person_policy_triggered = (
        dl_screening_detected and bool(person_photo_supplied)
    )

    if dl_person_policy_triggered:
        # HARD POLICY: a Driving Licence with a successful person-to-document
        # face MATCH must never remain LOW/MEDIUM. The minimum overall risk is
        # 60/100 (HIGH_RISK). Existing suspicious signals are preserved and
        # can raise the score further.
        current_before_policy = BASELINE_RISK + sum(
            item["points"] for item in contributors
        )
        policy_points = max(0, 60 - current_before_policy)

        # For a clean DL + MATCH this is exactly +45:
        # 15 baseline + 45 policy = 60.
        if policy_points:
            add(
                "Driving Licence + person-photo policy",
                policy_points,
                "Driving Licence with a supplied person verification photo triggers the configured HIGH_RISK policy",
                "HIGH"
            )

    # ---------------------------------------------------------
    # 6. OCR RELIABILITY
    # ---------------------------------------------------------
    ocr_score = float(
        ocr_confidence.get("average_confidence", 0) or 0
    )

    if 0 < ocr_score < 45:
        add(
            "OCR reliability",
            8,
            f"OCR confidence is low ({ocr_score:.1f}%)",
            "LOW"
        )
    elif 45 <= ocr_score < 65:
        add(
            "OCR reliability",
            4,
            f"OCR confidence is moderate ({ocr_score:.1f}%)",
            "LOW"
        )

    # ---------------------------------------------------------
    # 6. IMAGE QUALITY
    # ---------------------------------------------------------
    quality_score = int(
        image_quality.get("score", 0) or 0
    )

    if quality_score >= 15:
        add(
            "Image quality",
            5,
            "Low image quality may reduce screening reliability",
            "LOW"
        )
    elif quality_score >= 8:
        add(
            "Image quality",
            2,
            "Image quality is slightly below the preferred screening quality",
            "LOW"
        )

    # ---------------------------------------------------------
    # FINAL SCORE
    # ---------------------------------------------------------
    additional_risk = sum(
        item["points"] for item in contributors
    )

    raw_score = BASELINE_RISK + additional_risk
    score = min(100, raw_score)

    # Final hard floor. This is deliberately AFTER all normal contributors so
    # no later calculation can accidentally reduce a DL + face MATCH below 60.
    if dl_person_policy_triggered:
        score = max(score, 60)

    # Keep the policy visible in the returned risk object so the frontend,
    # history and reports can explain why the overall risk is elevated.
    policy_triggered = dl_person_policy_triggered
    policy_name = (
        "DRIVING_LICENCE_PERSON_PHOTO_HIGH_RISK"
        if policy_triggered
        else None
    )

    # Risk levels and decisions.
    if score >= 80:
        level = "CRITICAL_RISK"
        decision = "REJECT_ESCALATE"
        recommendation = "REJECT / ESCALATE"
    elif score >= 60:
        level = "HIGH_RISK"
        decision = "MANUAL_REVIEW"
        recommendation = "MANUAL REVIEW"
    elif score >= 35:
        level = "MEDIUM_RISK"
        decision = "MANUAL_REVIEW"
        recommendation = "MANUAL REVIEW"
    elif score >= 20:
        level = "LOW_RISK_REVIEW"
        decision = "SECONDARY_CHECK"
        recommendation = "MANUAL REVIEW"
    else:
        level = "LOW_RISK"
        decision = "PASS"
        recommendation = "CLEAR"

    contributors.sort(
        key=lambda x: x["points"],
        reverse=True
    )

    explanation = [
        f"{item['source']}: +{item['points']} — {item['reason']}"
        for item in contributors
    ]

    # Explicitly describe the clean baseline.
    if not contributors:
        explanation.insert(
            0,
            "Base screening risk: +15 — clean baseline for a successfully processed case"
        )

    # ---------------------------------------------------------
    # RISK CONFIDENCE
    # ---------------------------------------------------------
    confidence_signals = sum([
        ocr_score >= 65,
        validation_status not in {"UNKNOWN", "REVIEW"},
        tampering.get("confidence") == "HIGH",
        face_status not in {
            "NOT_CHECKED",
            "NO_DOCUMENT_FACE",
            "NO_PERSON_FACE",
            "FACE_MODEL_UNAVAILABLE",
            "FACE_VERIFICATION_ERROR",
        },
        reference_status not in {"NOT_CHECKED", "NOT_APPLICABLE"},
    ])

    confidence = (
        "HIGH"
        if confidence_signals >= 4
        else ("MEDIUM" if confidence_signals >= 2 else "LOW")
    )

    # ---------------------------------------------------------
    # EXPLAINABLE DECISION
    # ---------------------------------------------------------
    if score < 20:
        decision_reason = (
            "No significant risk indicators detected; document passed "
            "the available screening checks."
        )
    elif score < 35:
        decision_reason = (
            "Minor screening concerns are present; routine secondary "
            "verification is recommended."
        )
    elif score < 60:
        decision_reason = (
            "One or more meaningful risk indicators were detected; "
            "manual review is recommended."
        )
    elif score < 80:
        if policy_triggered:
            decision_reason = (
                "Driving Licence face-match policy elevated this case to "
                "HIGH RISK; manual review is required before clearance."
            )
        else:
            decision_reason = (
                "Strong risk indicators were detected; the case requires "
                "manual review before clearance."
            )
    else:
        decision_reason = (
            "Multiple or severe risk indicators were detected; "
            "reject/escalate the case."
        )

    return {
        "score": score,
        "level": level,
        "decision": decision,
        "recommendation": recommendation,
        "decision_reason": decision_reason,
        "contributors": contributors,
        "explanation": explanation,
        "confidence": confidence,
        "raw_score": raw_score,
        "additional_risk": additional_risk,
        "baseline_risk": BASELINE_RISK,
        "score_capped": raw_score > 100,
        "policy_triggered": policy_triggered,
        "policy_name": policy_name,
        "risk_model": "structured_multi_signal_v5_dl_person_photo_policy"
    }


# =========================================================
# AUDIT TRAIL
# =========================================================

def create_audit_log(
    event,
    officer=None,
    case_id=None,
    details=None
):
    """
    Save a security/audit event in MongoDB.
    Audit failures must never stop the screening workflow.
    """
    try:
        log = {
            "event": event,
            "timestamp": datetime.now(timezone.utc),
            "case_id": case_id,
            "details": details or {}
        }

        if officer:
            log["officer"] = {
                "officer_id": officer.get("officer_id"),
                "username": officer.get("username"),
                "name": officer.get("name"),
                "designation": officer.get("designation")
            }

        audit_logs.insert_one(log)

    except Exception as e:
        print("Audit log error:", e)


# =========================================================
# AUTHENTICATION
# =========================================================

SESSION_HOURS = 8
PBKDF2_ITERATIONS = 310_000


class LoginRequest(BaseModel):
    username: str
    password: str


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()


def _verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    calculated = _hash_password(password, salt_hex)
    return hmac.compare_digest(calculated, stored_hash)


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_officer(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    session = auth_sessions.find_one({
        "token_hash": _hash_session_token(token),
        "active": True,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })

    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    officer = officers.find_one(
        {"username": session["username"], "active": True},
        {"_id": 0, "password_hash": 0, "password_salt": 0},
    )

    if not officer:
        raise HTTPException(status_code=401, detail="Officer account is inactive")

    return officer


@app.post("/auth/login")
def auth_login(payload: LoginRequest):
    username = payload.username.strip()

    officer = officers.find_one({"username": username})

    if not officer or not officer.get("active", False):
        create_audit_log(
            event="LOGIN_FAILED",
            details={
                "username": username,
                "reason": "INVALID_OFFICER_CREDENTIALS"
            }
        )
        raise HTTPException(status_code=401, detail="Invalid officer credentials")

    if not _verify_password(
        payload.password,
        officer.get("password_hash", ""),
        officer.get("password_salt", ""),
    ):
        create_audit_log(
            event="LOGIN_FAILED",
            officer={
                "officer_id": officer.get("officer_id"),
                "username": officer.get("username"),
                "name": officer.get("name"),
                "designation": officer.get("designation")
            },
            details={
                "username": username,
                "reason": "INVALID_PASSWORD"
            }
        )
        raise HTTPException(status_code=401, detail="Invalid officer credentials")

    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=SESSION_HOURS)

    auth_sessions.insert_one({
        "token_hash": _hash_session_token(token),
        "username": username,
        "officer_id": officer.get("officer_id"),
        "created_at": now,
        "expires_at": expires_at,
        "active": True,
    })

    officers.update_one(
        {"_id": officer["_id"]},
        {"$set": {"last_login": now}},
    )

    create_audit_log(
        event="LOGIN_SUCCESS",
        officer={
            "officer_id": officer.get("officer_id"),
            "username": officer.get("username"),
            "name": officer.get("name"),
            "designation": officer.get("designation")
        },
        details={
            "session_expires_at": expires_at
        }
    )

    return {
        "success": True,
        "message": "Login successful",
        "token": token,
        "expires_at": expires_at.isoformat(),
        "officer": {
            "officer_id": officer.get("officer_id"),
            "username": officer.get("username"),
            "name": officer.get("name"),
            "designation": officer.get("designation"),
        },
    }


@app.get("/auth/me")
def auth_me(officer=Depends(require_officer)):
    return {
        "success": True,
        "officer": officer,
    }


@app.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            token_hash = _hash_session_token(token)
            session = auth_sessions.find_one({"token_hash": token_hash})

            if session:
                officer = officers.find_one(
                    {"username": session.get("username")},
                    {"_id": 0, "password_hash": 0, "password_salt": 0},
                )

                auth_sessions.update_one(
                    {"token_hash": token_hash},
                    {"$set": {"active": False, "logged_out_at": datetime.now(timezone.utc)}},
                )

                create_audit_log(
                    event="LOGOUT",
                    officer=officer,
                    details={"session_terminated": True}
                )

    return {"success": True, "message": "Logged out successfully"}


# =========================================================
# AUDIT LOGS
# =========================================================

@app.get("/audit-logs")
def get_audit_logs(limit: int = 100, officer=Depends(require_officer)):
    """Return recent security and screening audit events."""

    try:
        limit = max(1, min(limit, 500))

        logs = list(
            audit_logs
            .find({}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )

        return {
            "success": True,
            "count": len(logs),
            "logs": logs
        }

    except Exception as e:
        print("Audit log retrieval error:", e)
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve audit logs"
        )


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {
        "message": (
            "AI Document Screening API is running"
        ),
        "version": "3.0.0"
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    try:

        reference_passports.database.client.admin.command(
            "ping"
        )

        mongo_status = "connected"

    except Exception:

        mongo_status = "disconnected"

    return {
        "status": "healthy",
        "mongodb": mongo_status,
        "screening_cases": screening_cases.count_documents({})
    }


# =========================================================
# SCREENING HISTORY
# =========================================================

@app.get("/history")
def get_history(limit: int = 100, officer=Depends(require_officer)):
    """
    Return screening cases saved in MongoDB.

    The frontend uses this endpoint for:
    - Screening History
    - Dashboard recent activity
    - Risk Analytics
    - Reports
    """

    try:
        # Keep the limit safe so an accidental large request
        # does not load an excessive number of records.
        limit = max(1, min(limit, 500))

        cases = list(
            screening_cases
            .find({}, {"_id": 0})
            .sort("screened_at", -1)
            .limit(limit)
        )

        return {
            "success": True,
            "count": len(cases),
            "history": cases
        }

    except Exception as e:
        print("Screening history error:", e)

        raise HTTPException(
            status_code=500,
            detail=f"Failed to load screening history: {str(e)}"
        )


# =========================================================
# REPORTS
# =========================================================

@app.get("/reports")
def get_reports(
    status: str = "ALL",
    document_type: str = "ALL",
    limit: int = 500,
    officer=Depends(require_officer)
):
    """Return MongoDB screening records formatted for reporting/export."""
    try:
        limit = max(1, min(limit, 1000))
        query = {}

        if status and status.upper() != "ALL":
            query["screening_status"] = status.upper()

        if document_type and document_type.upper() != "ALL":
            query["document_type"] = document_type

        cases = list(
            screening_cases
            .find(query, {"_id": 0})
            .sort("screened_at", -1)
            .limit(limit)
        )

        def risk_score(case):
            return (case.get("risk_assessment") or {}).get("score", 0) or 0

        def ref_status(case):
            return (case.get("reference_verification") or {}).get("status", "NOT_CHECKED")

        summary = {
            "total": len(cases),
            "verified": sum(1 for c in cases if c.get("screening_status") == "VERIFIED"),
            "review": sum(1 for c in cases if c.get("screening_status") == "REVIEW"),
            "high_risk": sum(1 for c in cases if c.get("screening_status") == "HIGH RISK"),
            "average_risk_score": round(sum(float(risk_score(c)) for c in cases) / len(cases), 1) if cases else 0,
            "reference_match": sum(1 for c in cases if ref_status(c) == "MATCH"),
            "reference_partial": sum(1 for c in cases if ref_status(c) == "PARTIAL_MATCH"),
            "reference_mismatch": sum(1 for c in cases if ref_status(c) == "MISMATCH"),
            "reference_no_match": sum(1 for c in cases if ref_status(c) == "NO_MATCH"),
        }

        return {
            "success": True,
            "count": len(cases),
            "summary": summary,
            "reports": cases,
        }
    except Exception as e:
        print("Reports error:", e)
        raise HTTPException(status_code=500, detail=f"Failed to load reports: {str(e)}")


# =========================================================
# RISK ANALYTICS
# =========================================================

@app.get("/analytics")
def get_analytics(officer=Depends(require_officer)):
    """
    Calculate live screening analytics directly from MongoDB.
    """

    try:
        total_cases = screening_cases.count_documents({})

        verified_count = screening_cases.count_documents({
            "screening_status": "VERIFIED"
        })

        review_count = screening_cases.count_documents({
            "screening_status": "REVIEW"
        })

        high_risk_count = screening_cases.count_documents({
            "screening_status": "HIGH RISK"
        })

        # Average risk score
        average_result = list(
            screening_cases.aggregate([
                {
                    "$group": {
                        "_id": None,
                        "average": {
                            "$avg": "$risk_assessment.score"
                        }
                    }
                }
            ])
        )

        average_risk_score = 0

        if average_result:
            average_risk_score = round(
                float(average_result[0].get("average") or 0),
                1
            )

        # Reference verification counts
        reference_match_count = screening_cases.count_documents({
            "reference_verification.status": "MATCH"
        })

        reference_partial_match_count = screening_cases.count_documents({
            "reference_verification.status": "PARTIAL_MATCH"
        })

        reference_mismatch_count = screening_cases.count_documents({
            "reference_verification.status": "MISMATCH"
        })

        reference_no_match_count = screening_cases.count_documents({
            "reference_verification.status": "NO_MATCH"
        })

        # Document type distribution
        document_type_pipeline = [
            {
                "$group": {
                    "_id": "$document_type",
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {
                    "count": -1
                }
            }
        ]

        document_type_results = list(
            screening_cases.aggregate(
                document_type_pipeline
            )
        )

        document_types = {}

        for item in document_type_results:
            document_type = item.get("_id") or "Unknown"
            document_types[document_type] = item.get(
                "count",
                0
            )

        def percentage(count):
            if total_cases == 0:
                return 0

            return round(
                (count / total_cases) * 100,
                1
            )

        return {
            "success": True,

            "total_cases": total_cases,

            "verified_count": verified_count,
            "review_count": review_count,
            "high_risk_count": high_risk_count,

            "verified_rate": percentage(
                verified_count
            ),

            "review_rate": percentage(
                review_count
            ),

            "high_risk_rate": percentage(
                high_risk_count
            ),

            "average_risk_score": average_risk_score,

            "reference_match_count":
                reference_match_count,

            "reference_partial_match_count":
                reference_partial_match_count,

            "reference_mismatch_count":
                reference_mismatch_count,

            "reference_no_match_count":
                reference_no_match_count,

            "document_types": document_types
        }

    except Exception as e:
        print("Risk analytics error:", e)

        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate analytics: {str(e)}"
        )


# =========================================================
# FACE VERIFICATION — YuNet + SFace
# =========================================================
# Production/demo face pipeline:
#   YuNet  -> detects faces + 5 landmarks
#   SFace  -> aligns face + extracts identity features + cosine match
# The comparison target is ONLY the face printed on the uploaded document
# versus the uploaded/captured person photo.

from pathlib import Path
from urllib.request import urlopen, Request

FACE_MODEL_DIR = Path(__file__).resolve().parent / "models" / "face"
FACE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
YUNET_MODEL_PATH = FACE_MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL_PATH = FACE_MODEL_DIR / "face_recognition_sface_2021dec.onnx"

YUNET_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

YUNET_DETECTOR = None
SFACE_RECOGNIZER = None
FACE_MODEL_ERROR = None


def _download_face_model(path: Path, url: str):
    """Download an OpenCV Zoo model once; later starts use the local file."""
    if path.exists() and path.stat().st_size > 1024:
        return
    print(f"Downloading face model: {path.name} ...")
    req = Request(url, headers={"User-Agent": "VERIGUARD/1.0"})
    with urlopen(req, timeout=120) as response, open(path, "wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    if path.stat().st_size <= 1024:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded model is invalid: {path.name}")


def _load_yunet_sface():
    global YUNET_DETECTOR, SFACE_RECOGNIZER, FACE_MODEL_ERROR
    try:
        _download_face_model(YUNET_MODEL_PATH, YUNET_MODEL_URL)
        _download_face_model(SFACE_MODEL_PATH, SFACE_MODEL_URL)

        YUNET_DETECTOR = cv2.FaceDetectorYN.create(
            str(YUNET_MODEL_PATH),
            "",
            (320, 320),
            0.70,
            0.30,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        SFACE_RECOGNIZER = cv2.FaceRecognizerSF.create(
            str(SFACE_MODEL_PATH),
            "",
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        print("YuNet + SFace face models loaded successfully.")
    except Exception as exc:
        FACE_MODEL_ERROR = str(exc)
        YUNET_DETECTOR = None
        SFACE_RECOGNIZER = None
        print("YuNet/SFace unavailable:", exc)


_load_yunet_sface()


def _detect_yunet_faces(image):
    """Return YuNet detections sorted largest-first."""
    if YUNET_DETECTOR is None:
        return []
    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = frame.shape[:2]
    YUNET_DETECTOR.setInputSize((w, h))
    _, faces = YUNET_DETECTOR.detect(frame)
    if faces is None:
        return []
    rows = []
    for row in faces:
        x, y, fw, fh = [float(v) for v in row[:4]]
        score = float(row[14]) if len(row) > 14 else 0.0
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        fw = max(1, min(w - x, fw))
        fh = max(1, min(h - y, fh))
        rows.append({
            "row": row,
            "x": int(x), "y": int(y),
            "width": int(fw), "height": int(fh),
            "score": score,
            "area": int(fw * fh),
        })
    return sorted(rows, key=lambda item: item["area"], reverse=True)


def compare_face_images(document_image, person_image):
    """
    Compare ONLY the largest face printed on the document with the person's
    captured/uploaded face using YuNet detection + SFace recognition.
    """
    base = {
        "status": "NOT_CHECKED",
        "score": 0,
        "similarity": 0,
        "document_face_detected": False,
        "person_face_detected": False,
        "reference_face_detected": False,
        "method": "YuNet + SFace",
        "model": "YuNet face_detection_yunet_2023mar + SFace face_recognition_sface_2021dec",
        "verification_target": "person_photo_vs_document_printed_face",
        "document_face_count": 0,
        "person_face_count": 0,
    }

    if YUNET_DETECTOR is None or SFACE_RECOGNIZER is None:
        base["status"] = "FACE_MODEL_UNAVAILABLE"
        base["reason"] = "YuNet/SFace models are unavailable. Check the backend model download/network once."
        base["model_error"] = FACE_MODEL_ERROR or "unknown model error"
        return base

    try:
        doc_frame = cv2.cvtColor(np.array(document_image.convert("RGB")), cv2.COLOR_RGB2BGR)
        person_frame = cv2.cvtColor(np.array(person_image.convert("RGB")), cv2.COLOR_RGB2BGR)

        doc_faces = _detect_yunet_faces(document_image)
        person_faces = _detect_yunet_faces(person_image)
        base["document_face_count"] = len(doc_faces)
        base["person_face_count"] = 0
        base["person_faces_detected_total"] = len(person_faces)
        base["document_face_detected"] = bool(doc_faces)
        base["person_face_detected"] = bool(person_faces)
        base["reference_face_detected"] = bool(person_faces)
        base["person_face_selection"] = "center_priority"

        if not doc_faces:
            base.update({
                "status": "NO_DOCUMENT_FACE",
                "reason": "YuNet could not detect the face printed on the uploaded document."
            })
            return base
        if not person_faces:
            base.update({
                "status": "NO_PERSON_FACE",
                "reason": "YuNet could not detect a face in the person's photo/camera capture."
            })
            return base

        doc_face = doc_faces[0]

        # Camera frames can contain background people. Pick the face closest
        # to the frame center, with area as a tie-breaker, instead of failing
        # the whole verification because a background face was detected.
        h, w = person_frame.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        def subject_key(item):
            fx = item["x"] + item["width"] / 2.0
            fy = item["y"] + item["height"] / 2.0
            dist = ((fx - cx) / max(w, 1)) ** 2 + ((fy - cy) / max(h, 1)) ** 2
            area_norm = (item["area"] / max(w * h, 1))
            return (dist, -area_norm)
        person_face = sorted(person_faces, key=subject_key)[0]
        base["person_face_count"] = 1
        base["selected_subject_face"] = {"x": person_face["x"], "y": person_face["y"], "width": person_face["width"], "height": person_face["height"]}

        doc_row = doc_face["row"].reshape(1, -1)
        person_row = person_face["row"].reshape(1, -1)

        doc_aligned = SFACE_RECOGNIZER.alignCrop(doc_frame, doc_row)
        person_aligned = SFACE_RECOGNIZER.alignCrop(person_frame, person_row)
        doc_feature = SFACE_RECOGNIZER.feature(doc_aligned)
        person_feature = SFACE_RECOGNIZER.feature(person_aligned)

        cosine = float(SFACE_RECOGNIZER.match(
            doc_feature,
            person_feature,
            cv2.FaceRecognizerSF_FR_COSINE,
        ))
        cosine = max(-1.0, min(1.0, cosine))

        # SFace/OpenCV cosine similarity is a similarity metric, not probability.
        similarity = max(0.0, min(100.0, cosine * 100.0))

        # Conservative screening thresholds; tune with project test set later.
        if cosine >= 0.363:
            status = "MATCH"
        elif cosine >= 0.30:
            status = "PARTIAL_MATCH"
        else:
            status = "MISMATCH"

        base.update({
            "status": status,
            "score": round(similarity, 1),
            "similarity": round(similarity, 1),
            "cosine_similarity": round(cosine, 4),
            "document_detection_score": round(doc_face["score"], 3),
            "person_detection_score": round(person_face["score"], 3),
            "document_face_box": {k: doc_face[k] for k in ("x", "y", "width", "height")},
            "person_face_box": {k: person_face[k] for k in ("x", "y", "width", "height")},
            "reference_face_box": {k: person_face[k] for k in ("x", "y", "width", "height")},
            "reason": (
                "YuNet selected the centered subject face for verification; "
                "SFace compared that subject only with the face printed on the document."
            ),
            "background_faces_ignored": max(0, base.get("person_faces_detected_total", 1) - 1),
        })
        return base
    except Exception as exc:
        base["status"] = "FACE_VERIFICATION_ERROR"
        base["reason"] = f"YuNet/SFace face verification failed: {exc}"
        return base


# =========================================================
# UPLOAD SECURITY
# =========================================================

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
MAX_PERSON_PHOTO_SIZE = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def sanitize_filename(filename):
    """Return a safe display/storage filename without path traversal characters."""
    raw = str(filename or "document")
    raw = raw.replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    return safe[:180] or "document"


def validate_uploaded_image(contents, upload, max_size, label):
    """Validate declared type, actual image format, size and dimensions."""
    if not contents:
        raise HTTPException(status_code=400, detail=f"{label} is empty.")

    if len(contents) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"{label} is too large. Maximum allowed size is {limit_mb} MB."
        )

    declared_type = (upload.content_type or "").lower().strip()
    if declared_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {label.lower()} type. Use JPG, PNG or WEBP."
        )

    try:
        with Image.open(BytesIO(contents)) as checked_image:
            checked_image.verify()

        with Image.open(BytesIO(contents)) as checked_image:
            actual_format = (checked_image.format or "").upper()
            width, height = checked_image.size

        if actual_format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported {label.lower()} format. Use JPG, PNG or WEBP."
            )

        if width < 120 or height < 120:
            raise HTTPException(
                status_code=400,
                detail=f"{label} resolution is too small for reliable screening."
            )

        if width * height > MAX_IMAGE_PIXELS:
            raise HTTPException(
                status_code=400,
                detail=f"{label} dimensions are too large for safe processing."
            )

        return {
            "safe_filename": sanitize_filename(upload.filename),
            "format": actual_format,
            "width": width,
            "height": height,
            "size_bytes": len(contents),
        }

    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{label} is not a valid readable image."
        ) from exc
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{label} exceeds the safe image processing limit."
        ) from exc


# =========================================================
# UPLOAD + COMPLETE SCREENING
# =========================================================

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    person_photo: UploadFile | None = File(None),
    reference_photo: UploadFile | None = File(None),
    officer=Depends(require_officer)
):

    contents = await file.read()

    try:

        # -------------------------------------------------
        # SECURE DOCUMENT UPLOAD VALIDATION
        # -------------------------------------------------

        document_info = validate_uploaded_image(
            contents,
            file,
            MAX_DOCUMENT_SIZE,
            "Document image"
        )

        # -------------------------------------------------
        # OPEN ORIGINAL IMAGE
        # -------------------------------------------------

        original_image = Image.open(BytesIO(contents))

        original_format = (
            document_info["format"]
            or "UNKNOWN"
        )

        image = original_image.convert("RGB")

        # -------------------------------------------------
        # FACE VERIFICATION
        # -------------------------------------------------
        document_faces = _detect_yunet_faces(image) if YUNET_DETECTOR is not None else []
        face_verification = {
            "status": "NOT_CHECKED",
            "score": 0,
            "similarity": 0,
            "document_face_detected": bool(document_faces),
            "document_face_count": len(document_faces),
            "person_face_detected": False,
            "reference_face_detected": False,
            "person_face_count": 0,
            "reason": "Person photo not supplied.",
            "method": "YuNet + SFace",
            "verification_target": "person_photo_vs_document_printed_face",
        }

        # Person photo is the live/uploaded face that must match the
        # face found inside the document. Keep reference_photo as a
        # backwards-compatible alias for older frontend builds.
        person_upload = person_photo if person_photo is not None else reference_photo
        if person_upload is not None:
            person_contents = await person_upload.read()
            validate_uploaded_image(
                person_contents,
                person_upload,
                MAX_PERSON_PHOTO_SIZE,
                "Person photo"
            )
            person_image = Image.open(BytesIO(person_contents)).convert("RGB")
            face_verification = compare_face_images(image, person_image)

        # -------------------------------------------------
        # OCR
        # -------------------------------------------------

        extracted_text = pytesseract.image_to_string(
            image,
            lang="eng",
            config="--psm 6"
        )

        lines = [
            line.strip()
            for line in extracted_text.splitlines()
            if line.strip()
        ]

        # -------------------------------------------------
        # FIELD EXTRACTION
        # -------------------------------------------------

        document_type = detect_document_type(
            extracted_text
        )

        name = extract_name(
            lines
        )

        # Second-pass OCR with a sparse page mode is useful on ID cards where
        # the holder name is separated from the main text block. It only fills
        # a missing name and does not alter other screening modules.
        if not name and document_type == "Driving Licence":
            try:
                sparse_text = pytesseract.image_to_string(
                    image,
                    lang="eng",
                    config="--psm 11"
                )
                sparse_lines = [
                    line.strip()
                    for line in sparse_text.splitlines()
                    if line.strip()
                ]
                name = extract_name(sparse_lines)
                if name:
                    lines = lines + [x for x in sparse_lines if x not in lines]
            except Exception as e:
                print("Secondary name OCR warning:", e)

        dob = extract_dob(
            lines
        )

        id_number = extract_id_number(
            lines,
            document_type=document_type
        )

        validity = extract_validity(
            lines
        )

        nationality = extract_nationality_enhanced(lines, document_type)
        gender = extract_gender(lines, document_type)
        passport_fields = extract_passport_fields(lines) if document_type == "Passport" else {}
        visa_fields = extract_visa_fields(lines) if "Visa" in document_type else {}
        if document_type == "Passport":
            if not id_number and passport_fields.get("passport_number"):
                id_number = passport_fields["passport_number"]
            if not nationality and passport_fields.get("nationality"):
                nationality = passport_fields["nationality"]
            if not gender and passport_fields.get("gender"):
                gender = passport_fields["gender"]
        visa_validation = validate_visa_fields(visa_fields) if visa_fields else None

        # -------------------------------------------------
        # OCR CONFIDENCE
        # -------------------------------------------------

        ocr_confidence = analyze_ocr_confidence(
            image
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        validation = validate_document(
            validity=validity,
            document_type=document_type,
            id_number=id_number,
            nationality=nationality,
            dob=dob,
            name=name
        )

        # -------------------------------------------------
        # TAMPERING
        # -------------------------------------------------

        tampering = run_tampering_analysis(
            image=image,
            original_image=original_image,
            ocr_confidence=ocr_confidence,
            name=name,
            dob=dob,
            id_number=id_number,
            validity=validity
        )

        # -------------------------------------------------
        # MONGODB REFERENCE VERIFICATION
        # -------------------------------------------------

        if document_type == "Passport":
            reference_verification = verify_against_reference(
                name=name,
                dob=dob,
                id_number=id_number,
                validity=validity
            )
        else:
            reference_verification = {
                "status": "NOT_APPLICABLE",
                "reason": "Reference passport verification is only applicable to Passport documents.",
                "reference_found": False,
                "not_applicable": True,
            }

        # -------------------------------------------------
        # RISK
        # -------------------------------------------------

        image_quality = analyze_image_quality(image)
        risk = calculate_risk(
            validation=validation,
            tampering=tampering,
            reference_verification=reference_verification,
            face_verification=face_verification,
            ocr_confidence=ocr_confidence,
            image_quality=image_quality,
            document_type=document_type,
            person_photo_supplied=(person_upload is not None),
            extracted_text=extracted_text,
        )

        # -------------------------------------------------
        # FINAL SCREENING STATUS
        # -------------------------------------------------

        if risk["level"] == "CRITICAL_RISK":
            screening_status = "CRITICAL RISK"

        elif risk["level"] == "HIGH_RISK":
            screening_status = "HIGH RISK"

        elif risk["level"] in [
            "MEDIUM_RISK",
            "LOW_RISK_REVIEW",
            "REVIEW_REQUIRED"
        ]:
            screening_status = "REVIEW"

        else:
            screening_status = "VERIFIED"

        # -------------------------------------------------
        # SAVE SCREENING CASE
        # -------------------------------------------------

        case_id = generate_case_id()

        screening_case = {
            "case_id": case_id,
            "filename": document_info["safe_filename"],
            "content_type": file.content_type,
            "document_type": document_type,
            "name": name,
            "date_of_birth": dob,
            "id_number": id_number,
            "validity": validity,
            "nationality": nationality,
            "gender": gender,
            "passport_fields": passport_fields,
            "visa_fields": visa_fields,
            "visa_validation": visa_validation,
            "validation": validation,
            "reference_verification": (
                reference_verification
            ),
            "face_verification": face_verification,
            "tampering_analysis": tampering,
            "risk_assessment": risk,
            "risk_score": risk.get("score", 0),
            "risk_level": risk.get("level", "LOW_RISK"),
            "risk_decision": risk.get("decision", "PASS"),
            "screening_status": screening_status,
            "screened_at": datetime.utcnow(),

            # Authenticated officer who performed this screening.
            "screened_by": {
                "officer_id": officer.get("officer_id"),
                "username": officer.get("username"),
                "name": officer.get("name"),
                "designation": officer.get("designation")
            }
        }

        try:

            screening_case = sanitize_screening_case(screening_case)
            screening_cases.insert_one(screening_case)

        except Exception as db_error:

            print(
                "Screening history save error:",
                db_error
            )

        # -------------------------------------------------
        # AUDIT TRAIL
        # -------------------------------------------------

        create_audit_log(
            event="SCREENING_COMPLETED",
            officer=officer,
            case_id=case_id,
            details={
                "document_type": document_type,
                "screening_status": screening_status,
                "risk_score": risk.get("score", 0),
                "validation_status": validation.get("status"),
                "face_status": face_verification.get("status"),
                "reference_status": reference_verification.get("status"),
                "tampering_status": tampering.get("status")
            }
        )

        # -------------------------------------------------
        # FINAL RESPONSE
        # -------------------------------------------------

        return {

            "message": (
                "Document screening completed"
            ),

            "case_id": case_id,

            "filename": file.filename,

            "content_type": file.content_type,

            "document_type": document_type,

            "screening_status": screening_status,

            "name": name,

            "date_of_birth": dob,

            "id_number": id_number,

            "validity": validity,
            "nationality": nationality,
            "gender": gender,
            "passport_fields": passport_fields,
            "visa_fields": visa_fields,
            "visa_validation": visa_validation,

            # OCR
            "ocr": {
                "average_confidence": (
                    ocr_confidence[
                        "average_confidence"
                    ]
                ),
                "status": (
                    ocr_confidence["status"]
                )
            },

            # Validation
            "validation": validation,

            # MongoDB
            "reference_verification": (
                reference_verification
            ),

            # Face verification
            "face_verification": face_verification,

            # Tampering
            "tampering_analysis": tampering,

            # Risk
            "risk_assessment": risk,
            # Frontend compatibility aliases for older UI builds.
            "risk_score": risk.get("score", 0),
            "risk_level": risk.get("level", "LOW_RISK"),
            "risk_decision": risk.get("decision", "PASS"),

            # Image
            "image": {
                "format": original_format,
                "width": image.width,
                "height": image.height
            },

            # OCR raw text
            "extracted_text": extracted_text,

            "lines": lines,

            "screened_at": (
                datetime.now().isoformat()
            )
        }

    except Exception as e:

        print(
            "Document screening error:",
            e
        )

        return {

            "message": (
                "Document screening failed"
            ),

            "error": str(e)
        }