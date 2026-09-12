from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from PIL import Image, ImageChops, ImageEnhance, ExifTags
import pytesseract
from pytesseract import Output

import cv2
import numpy as np

# Optional AI face-recognition model (ArcFace via InsightFace).
# The rest of document screening works even if this package/model is unavailable.
try:
    from insightface.app import FaceAnalysis
except Exception:
    FaceAnalysis = None

import re
from io import BytesIO
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

# MongoDB
from db import reference_passports, screening_cases, db

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
# MONGODB INDEXES
# =========================================================

try:
    reference_passports.create_index(
        "passport_number"
    )

    screening_cases.create_index(
        "screened_at"
    )

    officers.create_index("username", unique=True)
    auth_sessions.create_index("expires_at", expireAfterSeconds=0)
except Exception as e:
    print("MongoDB index warning:", e)


# =========================================================
# DOCUMENT TYPE
# =========================================================

def detect_document_type(text):

    text_lower = text.lower()

    if "passport" in text_lower:
        return "Passport"

    if (
        "driving licence" in text_lower
        or "driving license" in text_lower
    ):
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


# =========================================================
# NAME EXTRACTION
# =========================================================

def extract_name(lines):

    labels = [
        "name",
        "full name",
        "surname",
        "given name"
    ]

    for i, line in enumerate(lines):

        clean = line.strip()
        lower = clean.lower()

        for label in labels:

            if lower.startswith(label):

                parts = clean.split(":", 1)

                if len(parts) == 2 and parts[1].strip():
                    return parts[1].strip()

                if i + 1 < len(lines):
                    return lines[i + 1].strip()

    # fallback
    ignored = {
        "university",
        "student id card",
        "passport",
        "visa",
        "date of birth",
        "driving licence",
        "driving license",
        "course / branch"
    }

    for line in lines:

        clean = line.strip()

        if re.fullmatch(
            r"[A-Za-z]+(?:\s+[A-Za-z]+){1,3}",
            clean
        ):

            if clean.lower() not in ignored:
                return clean

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

def extract_id_number(lines):

    # -----------------------------------------------------
    # PASSPORT-SPECIFIC EXTRACTION
    # Indian synthetic passport numbers:
    # Example: K2294558
    # -----------------------------------------------------

    passport_patterns = [
        r"\b[A-Z]\d{7}\b",
        r"\b[A-Z]\d{6,8}\b"
    ]

    for line in lines:

        upper = line.upper().strip()

        # MRZ normally starts with passport number
        # on second MRZ line.
        for pattern in passport_patterns:

            match = re.search(
                pattern,
                upper
            )

            if match:
                return match.group()

    # -----------------------------------------------------
    # ID-related lines
    # -----------------------------------------------------

    for line in lines:

        upper = line.upper()

        if any(
            x in upper
            for x in [
                "ID",
                "IDENTITY",
                "PASSPORT",
                "DOCUMENT",
                "NUMBER",
                "NO."
            ]
        ):

            candidates = re.findall(
                r"\b[A-Z0-9]{6,15}\b",
                upper
            )

            for candidate in candidates:

                if (
                    re.search(r"[A-Z]", candidate)
                    and re.search(r"\d", candidate)
                    and not candidate.startswith("WWW")
                ):

                    return candidate

    # -----------------------------------------------------
    # General fallback
    # -----------------------------------------------------

    for line in lines:

        candidates = re.findall(
            r"\b[A-Z0-9]{6,15}\b",
            line.upper()
        )

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
# VALIDATION
# =========================================================

def validate_document(validity):

    if not validity:

        return {
            "status": "UNKNOWN",
            "reason": "Validity information not found"
        }

    current_year = datetime.now().year

    # -----------------------------------------------------
    # Year range
    # -----------------------------------------------------

    match = re.search(
        r"(\d{4})\s*[-/.]\s*(\d{4})",
        validity
    )

    if match:

        start_year = int(match.group(1))
        end_year = int(match.group(2))

        if start_year <= current_year <= end_year:

            return {
                "status": "VALID",
                "reason": "Document is currently valid"
            }

        if current_year > end_year:

            return {
                "status": "EXPIRED",
                "reason": "Document validity has expired"
            }

        return {
            "status": "NOT_YET_VALID",
            "reason": "Document validity has not started"
        }

    # -----------------------------------------------------
    # Single expiry date
    # -----------------------------------------------------

    match = re.search(
        r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})",
        validity
    )

    if match:

        expiry_year = int(match.group(3))

        if current_year <= expiry_year:

            return {
                "status": "VALID",
                "reason": "Document appears currently valid"
            }

        return {
            "status": "EXPIRED",
            "reason": "Document expiry year has passed"
        }

    # -----------------------------------------------------
    # Month-name date
    # -----------------------------------------------------

    match = re.search(
        r"\b\d{1,2}[\s/-]+"
        r"(?:[A-Za-z]{3,9}|\d{1,2})"
        r"[\s,-]+(\d{4})\b",
        validity,
        re.IGNORECASE
    )

    if match:

        expiry_year = int(match.group(1))

        if current_year <= expiry_year:

            return {
                "status": "VALID",
                "reason": "Document appears currently valid"
            }

        return {
            "status": "EXPIRED",
            "reason": "Document expiry year has passed"
        }

    return {
        "status": "UNKNOWN",
        "reason": "Validity format not recognized"
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
# TAMPERING ENGINE
# =========================================================

def run_tampering_analysis(
    image,
    original_image,
    ocr_confidence,
    name,
    dob,
    id_number,
    validity
):

    image_quality = analyze_image_quality(
        image
    )

    ela = perform_ela(
        image
    )

    metadata = analyze_metadata(
        original_image
    )

    text_consistency = analyze_text_consistency(
        ocr_confidence,
        name,
        dob,
        id_number,
        validity
    )

    total_score = (
        image_quality["score"]
        + ela["score"]
        + text_consistency["score"]
        + metadata["score"]
    )

    total_score = min(
        total_score,
        100
    )

    if total_score >= 60:

        status = "HIGH_RISK"
        confidence = "HIGH"

    elif total_score >= 35:

        status = "REVIEW"
        confidence = "MEDIUM"

    elif total_score >= 15:

        status = "LOW_RISK"
        confidence = "LOW"

    else:

        status = "NORMAL"
        confidence = "LOW"

    indicators = []

    indicators.extend(
        image_quality["indicators"]
    )

    indicators.extend(
        text_consistency["indicators"]
    )

    if ela["status"] != "NORMAL":

        indicators.append(
            "ELA analysis detected image-level anomaly"
        )

    return {
        "status": status,
        "score": total_score,
        "confidence": confidence,
        "indicators": indicators,
        "components": {
            "image_quality": image_quality,
            "ela": ela,
            "text_consistency": text_consistency,
            "metadata": metadata
        }
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
    tampering
):

    score = tampering["score"]

    if validation["status"] == "EXPIRED":

        score += 25

    elif validation["status"] == "UNKNOWN":

        score += 5

    score = min(
        score,
        100
    )

    if score >= 60:

        level = "HIGH_RISK"
        decision = "MANUAL_REVIEW"

    elif score >= 35:

        level = "MEDIUM_RISK"
        decision = "MANUAL_REVIEW"

    elif score >= 20:

        level = "REVIEW_REQUIRED"
        decision = "SECONDARY_CHECK"

    else:

        level = "LOW_RISK"
        decision = "PASS"

    return {
        "score": score,
        "level": level,
        "decision": decision
    }


# =========================================================
# AUTHENTICATION
# =========================================================

SESSION_HOURS = 8
PBKDF2_ITERATIONS = 210_000


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
        raise HTTPException(status_code=401, detail="Invalid officer credentials")

    if not _verify_password(
        payload.password,
        officer.get("password_hash", ""),
        officer.get("password_salt", ""),
    ):
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
            auth_sessions.update_one(
                {"token_hash": _hash_session_token(token)},
                {"$set": {"active": False}},
            )

    return {"success": True, "message": "Logged out successfully"}


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
# FACE VERIFICATION
# =========================================================

# Haar cascade is retained only as a fallback detector. The preferred
# verification path uses an ArcFace embedding model through InsightFace.
FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

ARC_FACE_APP = None
ARC_FACE_ERROR = None

if FaceAnalysis is not None:
    try:
        # CPU keeps this Windows setup simple. The model is loaded lazily on startup.
        ARC_FACE_APP = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"]
        )
        ARC_FACE_APP.prepare(ctx_id=0, det_size=(640, 640))
        print("ArcFace/InsightFace model loaded successfully.")
    except Exception as e:
        ARC_FACE_ERROR = str(e)
        ARC_FACE_APP = None
        print("ArcFace model unavailable; OpenCV fallback will be used:", e)


def detect_largest_face(image):
    """Fallback OpenCV detector: return largest frontal face crop + bbox."""
    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    faces = FACE_CASCADE.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    if len(faces) == 0:
        return None, None
    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    pad_x, pad_y = int(w * 0.18), int(h * 0.22)
    x1, y1 = max(0, x-pad_x), max(0, y-pad_y)
    x2, y2 = min(frame.shape[1], x+w+pad_x), min(frame.shape[0], y+h+pad_y)
    crop = frame[y1:y2, x1:x2]
    return crop, {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}


def _arcface_faces(image):
    """Return detected InsightFace faces for one PIL image, largest first."""
    if ARC_FACE_APP is None:
        return []
    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    faces = ARC_FACE_APP.get(frame)
    return sorted(
        faces,
        key=lambda f: float((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])),
        reverse=True,
    )


def compare_face_images(document_image, person_image):
    """
    Compare ONLY the face printed on the document with the person's face photo.

    Preferred path: InsightFace/ArcFace deep face embeddings + cosine similarity.
    Fallback path: OpenCV face detection + ORB visual similarity when the AI
    model is not installed/available.
    """
    # -----------------------------------------------------
    # 1) AI/ML PATH — ArcFace embeddings
    # -----------------------------------------------------
    if ARC_FACE_APP is not None:
        try:
            doc_faces = _arcface_faces(document_image)
            person_faces = _arcface_faces(person_image)

            base = {
                "status": "NOT_CHECKED",
                "score": 0,
                "similarity": 0,
                "document_face_detected": bool(doc_faces),
                "person_face_detected": bool(person_faces),
                "reference_face_detected": bool(person_faces),
                "method": "InsightFace ArcFace face embeddings",
                "model": "buffalo_l",
                "verification_target": "person_photo_vs_document_printed_face",
            }

            if not doc_faces:
                base["status"] = "NO_DOCUMENT_FACE"
                base["reason"] = "No clear face detected in the uploaded document photo area."
                return base

            if not person_faces:
                base["status"] = "NO_PERSON_FACE"
                base["reason"] = "No clear face detected in the person's photo."
                return base

            doc_face = doc_faces[0]
            person_face = person_faces[0]
            doc_embedding = np.asarray(doc_face.embedding, dtype=np.float32)
            person_embedding = np.asarray(person_face.embedding, dtype=np.float32)

            doc_embedding /= max(np.linalg.norm(doc_embedding), 1e-8)
            person_embedding /= max(np.linalg.norm(person_embedding), 1e-8)
            cosine = float(np.dot(doc_embedding, person_embedding))
            cosine = max(-1.0, min(1.0, cosine))

            # Display score is a normalized similarity indicator, not a probability.
            similarity = round(((cosine + 1.0) / 2.0) * 100.0, 1)

            # Conservative demo thresholds for 1:1 verification.
            if cosine >= 0.50:
                status = "MATCH"
            elif cosine >= 0.35:
                status = "PARTIAL_MATCH"
            else:
                status = "MISMATCH"

            base.update({
                "status": status,
                "score": similarity,
                "similarity": similarity,
                "cosine_similarity": round(cosine, 4),
                "document_detection_score": round(float(doc_face.det_score), 3),
                "person_detection_score": round(float(person_face.det_score), 3),
                "reason": "ArcFace embedding comparison completed between the person's face and the face printed on the document.",
            })
            return base
        except Exception as e:
            print("ArcFace comparison failed; using OpenCV fallback:", e)

    # -----------------------------------------------------
    # FALLBACK PATH — keeps existing screening functional
    # -----------------------------------------------------
    doc_face, doc_box = detect_largest_face(document_image)
    person_face, person_box = detect_largest_face(person_image)

    base = {
        "status": "NOT_CHECKED",
        "score": 0,
        "similarity": 0,
        "document_face_detected": bool(doc_face is not None),
        "person_face_detected": bool(person_face is not None),
        "reference_face_detected": bool(person_face is not None),
        "document_face_box": doc_box,
        "person_face_box": person_box,
        "reference_face_box": person_box,
        "method": "OpenCV fallback visual similarity",
        "verification_target": "person_photo_vs_document_printed_face",
    }

    if doc_face is None:
        base["status"] = "NO_DOCUMENT_FACE"
        base["reason"] = "No clear face detected in the uploaded document."
        return base

    if person_face is None:
        base["status"] = "NO_PERSON_FACE"
        base["reason"] = "No clear face detected in the person's photo."
        return base

    def prepare(face):
        gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (320, 320))
        gray = cv2.equalizeHist(gray)
        return gray

    a, b = prepare(doc_face), prepare(person_face)
    orb = cv2.ORB_create(nfeatures=600)
    kp1, des1 = orb.detectAndCompute(a, None)
    kp2, des2 = orb.detectAndCompute(b, None)

    good_matches = 0
    total_matches = 0
    if des1 is not None and des2 is not None and len(des1) >= 2 and len(des2) >= 2:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        pairs = matcher.knnMatch(des1, des2, k=2)
        total_matches = len(pairs)
        for pair in pairs:
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                good_matches += 1

    match_ratio = (good_matches / total_matches) if total_matches else 0
    correlation = float(cv2.compareHist(
        cv2.calcHist([a], [0], None, [64], [0, 256]),
        cv2.calcHist([b], [0], None, [64], [0, 256]),
        cv2.HISTCMP_CORREL
    ))
    correlation = max(0.0, min(1.0, correlation))
    similarity = round(min(100.0, (match_ratio * 70.0) + (correlation * 30.0)), 1)

    if similarity >= 70:
        status = "MATCH"
    elif similarity >= 45:
        status = "PARTIAL_MATCH"
    else:
        status = "MISMATCH"

    base.update({
        "status": status,
        "score": similarity,
        "similarity": similarity,
        "reason": "AI model unavailable; OpenCV fallback comparison completed.",
    })
    return base

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
        # OPEN ORIGINAL IMAGE
        # -------------------------------------------------

        original_image = Image.open(
            BytesIO(contents)
        )

        original_format = (
            original_image.format
            or "UNKNOWN"
        )

        image = original_image.convert(
            "RGB"
        )

        # -------------------------------------------------
        # FACE VERIFICATION
        # -------------------------------------------------
        face_verification = {
            "status": "NOT_CHECKED",
            "score": 0,
            "similarity": 0,
            "document_face_detected": bool(detect_largest_face(image)[0] is not None),
            "person_face_detected": False,
            "reference_face_detected": False,
            "reason": "Person photo not supplied.",
        }

        # Person photo is the live/uploaded face that must match the
        # face found inside the document. Keep reference_photo as a
        # backwards-compatible alias for older frontend builds.
        person_upload = person_photo if person_photo is not None else reference_photo
        if person_upload is not None:
            person_contents = await person_upload.read()
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

        dob = extract_dob(
            lines
        )

        id_number = extract_id_number(
            lines
        )

        validity = extract_validity(
            lines
        )

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
            validity
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

        reference_verification = (
            verify_against_reference(
                name=name,
                dob=dob,
                id_number=id_number,
                validity=validity
            )
        )

        # -------------------------------------------------
        # RISK
        # -------------------------------------------------

        risk = calculate_risk(
            validation,
            tampering
        )

        # -------------------------------------------------
        # DATABASE MATCH RISK
        # -------------------------------------------------

        if (
            reference_verification["status"]
            == "NO_MATCH"
        ):

            risk["score"] = min(
                risk["score"] + 20,
                100
            )

        elif (
            reference_verification["status"]
            == "MISMATCH"
        ):

            risk["score"] = min(
                risk["score"] + 30,
                100
            )

        elif (
            reference_verification["status"]
            == "PARTIAL_MATCH"
        ):

            risk["score"] = min(
                risk["score"] + 10,
                100
            )

        # -------------------------------------------------
        # FACE VERIFICATION RISK
        # -------------------------------------------------
        if face_verification["status"] == "MISMATCH":
            risk["score"] = min(risk["score"] + 30, 100)
        elif face_verification["status"] == "PARTIAL_MATCH":
            risk["score"] = min(risk["score"] + 10, 100)
        elif face_verification["status"] in ["NO_DOCUMENT_FACE", "NO_REFERENCE_FACE", "NO_PERSON_FACE"]:
            risk["score"] = min(risk["score"] + 5, 100)

        # -------------------------------------------------
        # RECALCULATE RISK LEVEL
        # -------------------------------------------------

        if risk["score"] >= 60:

            risk["level"] = "HIGH_RISK"
            risk["decision"] = "MANUAL_REVIEW"

        elif risk["score"] >= 35:

            risk["level"] = "MEDIUM_RISK"
            risk["decision"] = "MANUAL_REVIEW"

        elif risk["score"] >= 20:

            risk["level"] = "REVIEW_REQUIRED"
            risk["decision"] = "SECONDARY_CHECK"

        else:

            risk["level"] = "LOW_RISK"
            risk["decision"] = "PASS"

        # -------------------------------------------------
        # FINAL SCREENING STATUS
        # -------------------------------------------------

        if risk["level"] == "HIGH_RISK":

            screening_status = "HIGH RISK"

        elif risk["level"] in [
            "MEDIUM_RISK",
            "REVIEW_REQUIRED"
        ]:

            screening_status = "REVIEW"

        else:

            screening_status = "VERIFIED"

        # -------------------------------------------------
        # SAVE SCREENING CASE
        # -------------------------------------------------

        case_id = f"VG-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"

        screening_case = {
            "case_id": case_id,
            "filename": file.filename,
            "content_type": file.content_type,
            "document_type": document_type,
            "name": name,
            "date_of_birth": dob,
            "id_number": id_number,
            "validity": validity,
            "validation": validation,
            "reference_verification": (
                reference_verification
            ),
            "face_verification": face_verification,
            "tampering_analysis": tampering,
            "risk_assessment": risk,
            "screening_status": screening_status,
            "screened_at": datetime.utcnow()
        }

        try:

            screening_cases.insert_one(
                screening_case
            )

        except Exception as db_error:

            print(
                "Screening history save error:",
                db_error
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