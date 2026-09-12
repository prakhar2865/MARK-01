from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import ConnectionFailure
from datetime import datetime, timezone, timedelta
import os

# =========================================================
# VERIGUARD MONGODB
# =========================================================

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "veriguard")

client = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
)
db = client[DATABASE_NAME]

reference_passports = db["reference_passports"]
screening_cases = db["screening_cases"]
dataset_metadata = db["dataset_metadata"]
officers = db["officers"]
auth_sessions = db["auth_sessions"]
audit_logs = db["audit_logs"]

# Internal collection used only for atomic case-number generation.
case_counters = db["case_counters"]


# =========================================================
# CONNECTION
# =========================================================

def test_connection():
    try:
        client.admin.command("ping")
        return True
    except ConnectionFailure:
        return False


# =========================================================
# INDEXES
# =========================================================

def ensure_indexes():
    """
    Create safe indexes for the collections used by VERIGUARD.

    These are idempotent: running this function repeatedly does not
    create duplicate indexes.
    """
    try:
        # Reference lookup: passport number is the primary lookup key.
        reference_passports.create_index(
            [("passport_number", ASCENDING)],
            name="idx_reference_passport_number",
            unique=True,
            sparse=True,
        )

        # Screening history / analytics / reports.
        screening_cases.create_index(
            [("screened_at", DESCENDING)],
            name="idx_screening_screened_at",
        )
        screening_cases.create_index(
            [("case_id", ASCENDING)],
            name="idx_screening_case_id",
            unique=True,
        )
        screening_cases.create_index(
            [("screening_status", ASCENDING), ("screened_at", DESCENDING)],
            name="idx_screening_status_date",
        )
        screening_cases.create_index(
            [("document_type", ASCENDING), ("screened_at", DESCENDING)],
            name="idx_screening_document_date",
        )
        screening_cases.create_index(
            [("screened_by.officer_id", ASCENDING), ("screened_at", DESCENDING)],
            name="idx_screening_officer_date",
        )
        screening_cases.create_index(
            [("risk_assessment.score", DESCENDING)],
            name="idx_screening_risk_score",
        )

        # Officer login.
        officers.create_index(
            [("username", ASCENDING)],
            name="idx_officer_username",
            unique=True,
        )

        # Session TTL: MongoDB removes expired sessions automatically.
        auth_sessions.create_index(
            [("expires_at", ASCENDING)],
            name="idx_auth_session_expiry",
            expireAfterSeconds=0,
        )
        auth_sessions.create_index(
            [("token_hash", ASCENDING)],
            name="idx_auth_token_hash",
            unique=True,
        )

        # Audit trail.
        audit_logs.create_index(
            [("timestamp", DESCENDING)],
            name="idx_audit_timestamp",
        )
        audit_logs.create_index(
            [("event", ASCENDING), ("timestamp", DESCENDING)],
            name="idx_audit_event_date",
        )
        audit_logs.create_index(
            [("officer.officer_id", ASCENDING), ("timestamp", DESCENDING)],
            name="idx_audit_officer_date",
        )
        audit_logs.create_index(
            [("case_id", ASCENDING)],
            name="idx_audit_case_id",
            sparse=True,
        )

        # Counter collection already has MongoDB's built-in unique _id index.
        # No custom _id index is required (MongoDB rejects unique option on _id index specs).

        return True

    except Exception as exc:
        print("MongoDB index warning:", exc)
        return False


# Create indexes when the backend imports db.py.
ensure_indexes()


# =========================================================
# FINAL CASE ID
# =========================================================

def generate_case_id():
    """
    Generate a concurrency-safe, human-readable case ID.

    Example:
        VG-20260911-000001
        VG-20260911-000002

    The numeric sequence is generated atomically by MongoDB, so two
    simultaneous screenings cannot intentionally receive the same ID.
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")

    counter = case_counters.find_one_and_update(
        {"_id": "screening_case"},
        {
            "$inc": {"sequence": 1},
            "$set": {"updated_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    sequence = int(counter.get("sequence", 1))
    return f"VG-{date_part}-{sequence:06d}"


# =========================================================
# RETENTION / SECURITY
# =========================================================

DEFAULT_SCREENING_RETENTION_DAYS = int(
    os.getenv("SCREENING_RETENTION_DAYS", "365")
)


def purge_expired_screening_cases(
    retention_days: int = DEFAULT_SCREENING_RETENTION_DAYS,
    dry_run: bool = True,
):
    """
    Retention helper for old screening records.

    Safety default is dry_run=True.
    It never deletes anything unless the caller explicitly passes
    dry_run=False.

    This avoids silently deleting SIH demo/evidence records.
    """
    retention_days = max(1, int(retention_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    query = {"screened_at": {"$lt": cutoff}}
    count = screening_cases.count_documents(query)

    if dry_run:
        return {
            "dry_run": True,
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "eligible_cases": count,
            "deleted": 0,
        }

    result = screening_cases.delete_many(query)

    return {
        "dry_run": False,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "eligible_cases": count,
        "deleted": result.deleted_count,
    }


def sanitize_screening_case(case: dict) -> dict:
    """
    Remove authentication secrets if an accidental secret field is
    ever passed into a screening record.
    """
    blocked_keys = {
        "password",
        "password_hash",
        "password_salt",
        "token",
        "token_hash",
        "access_token",
        "session_token",
    }

    cleaned = dict(case)

    for key in blocked_keys:
        cleaned.pop(key, None)

    # Never allow authentication secrets inside nested officer/session data.
    officer = cleaned.get("screened_by")
    if isinstance(officer, dict):
        officer = dict(officer)
        for key in blocked_keys:
            officer.pop(key, None)
        cleaned["screened_by"] = officer

    return cleaned
