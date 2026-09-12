"""
VERIGUARD - Officer Account Setup
Phase 1: Create / update an authorized officer in MongoDB.

This script only creates the officers collection/account.
It does NOT modify screening_cases, reference_passports, OCR,
tampering, face verification, analytics, or reports.
"""
from datetime import datetime, timezone
from getpass import getpass
from hashlib import pbkdf2_hmac
from secrets import token_bytes
from pymongo import MongoClient

MONGODB_URI = "mongodb://localhost:27017"
DATABASE_NAME = "veriguard"
COLLECTION_NAME = "officers"


def hash_password(password: str, salt: bytes) -> str:
    return pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000).hex()


def main():
    print("\n" + "=" * 56)
    print(" VERIGUARD — AUTHORIZED OFFICER SETUP")
    print(" Phase 1 — MongoDB officer account")
    print("=" * 56)

    username = input("\nOfficer ID / Username: ").strip()
    name = input("Officer Name: ").strip()
    designation = input("Designation [Security Officer]: ").strip() or "Security Officer"

    if not username or not name:
        print("\nERROR: Username and officer name are required.")
        return

    password = getpass("Password: ")
    confirm = getpass("Confirm Password: ")

    if not password:
        print("\nERROR: Password cannot be empty.")
        return
    if password != confirm:
        print("\nERROR: Passwords do not match.")
        return
    if len(password) < 8:
        print("\nERROR: Password must contain at least 8 characters.")
        return

    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        db = client[DATABASE_NAME]
        officers = db[COLLECTION_NAME]
        officers.create_index("username", unique=True)

        salt = token_bytes(32)
        password_hash = hash_password(password, salt)
        now = datetime.now(timezone.utc)
        existing = officers.find_one({"username": username})

        if existing:
            answer = input(f"\nOfficer '{username}' already exists. Replace credentials? (y/N): ").strip().lower()
            if answer != "y":
                print("No changes made.")
                return
            officers.update_one(
                {"username": username},
                {"$set": {
                    "name": name,
                    "designation": designation,
                    "password_hash": password_hash,
                    "password_salt": salt.hex(),
                    "active": True,
                    "updated_at": now,
                }}
            )
            print("\nOfficer account updated successfully.")
        else:
            officers.insert_one({
                "officer_id": f"OFF-{username.upper()}",
                "username": username,
                "name": name,
                "designation": designation,
                "password_hash": password_hash,
                "password_salt": salt.hex(),
                "active": True,
                "created_at": now,
                "updated_at": now,
                "last_login": None,
            })
            print("\nOfficer account created successfully.")

        print(f"Officer ID : {username}")
        print(f"Name       : {name}")
        print(f"Designation: {designation}")
        print("Active     : True")
        print("\nMongoDB: veriguard.officers")
        print("Password is stored as a salted PBKDF2-SHA256 hash.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
