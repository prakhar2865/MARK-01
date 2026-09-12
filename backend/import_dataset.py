from datasets import load_dataset
from db import reference_passports
from datetime import datetime


DATASET_NAME = "ud-synthetic/indian-passports"


def clean(value):
    if value is None:
        return ""

    value = str(value).strip()

    if value.lower() == "null":
        return ""

    return value.strip('"')


def import_dataset():

    print("=" * 60)
    print("LOADING DATASET")
    print("=" * 60)

    ds = load_dataset(DATASET_NAME)
    rows = ds["train"]

    valid_documents = []

    for row_number, row in enumerate(rows, start=1):

        index_value = clean(row.get("__index_level_0__"))

        # Find the large semicolon-separated data field
        data_value = ""

        for key, value in row.items():
            if key != "__index_level_0__" and value is not None:
                data_value = clean(value)
                break

        # Skip the alternate MRZ/gender rows
        if not index_value or not data_value:
            continue

        index_fields = index_value.split(";")
        data_fields = data_value.split(";")

        # We need:
        # 9 fields from index
        # 13 fields from data
        if len(index_fields) < 9:
            continue

        if len(data_fields) < 13:
            continue

        # -----------------------------
        # IDENTITY FIELDS
        # -----------------------------

        passport_number = clean(index_fields[0])
        surname = clean(index_fields[1])
        given_name = clean(index_fields[2])
        signature = clean(index_fields[3])
        date_of_birth = clean(index_fields[4])
        date_of_issue = clean(index_fields[5])
        date_of_expiry = clean(index_fields[6])
        sex = clean(index_fields[7])
        birth_city = clean(index_fields[8])

        # -----------------------------
        # PASSPORT METADATA
        # -----------------------------

        state = clean(data_fields[0])
        place_of_issue = clean(data_fields[1])
        authority = clean(data_fields[2])
        authority_code = clean(data_fields[3])
        height_cm = clean(data_fields[4])
        personal_number = clean(data_fields[5])
        nationality = clean(data_fields[6])
        nationality_in = clean(data_fields[7])
        nationality_code = clean(data_fields[8])
        document_type = clean(data_fields[9])
        mrz_line1 = clean(data_fields[10])
        mrz_line2 = clean(data_fields[11])
        mrz = clean(data_fields[12])

        # -----------------------------
        # CLEAN MRZ
        # -----------------------------

        mrz_line1 = mrz_line1.strip('"')
        mrz_line2 = mrz_line2.strip('"')
        mrz = mrz.strip('"')

        # -----------------------------
        # PLACE OF BIRTH
        # -----------------------------

        if birth_city and state:
            place_of_birth = f"{birth_city}, {state}"
        else:
            place_of_birth = birth_city or state

        # -----------------------------
        # GENDER
        # -----------------------------

        if sex.upper() == "M":
            gender = "male"
        elif sex.upper() == "F":
            gender = "female"
        else:
            gender = ""

        # -----------------------------
        # BASIC VALIDATION
        # -----------------------------

        if not passport_number:
            continue

        if not surname:
            continue

        if not given_name:
            continue

        if not date_of_birth:
            continue

        if not date_of_expiry:
            continue

        if not nationality:
            continue

        document = {
            "passport_number": passport_number,
            "surname": surname,
            "given_name": given_name,
            "signature": signature,
            "date_of_birth": date_of_birth,
            "date_of_issue": date_of_issue,
            "date_of_expiry": date_of_expiry,
            "sex": sex,
            "place_of_birth": place_of_birth,
            "place_of_issue": place_of_issue,
            "authority": authority,
            "authority_code": authority_code,
            "height_cm": height_cm,
            "personal_number": personal_number,
            "nationality": nationality,
            "nationality_in": nationality_in,
            "nationality_code": nationality_code,
            "document_type": document_type,
            "mrz_line1": mrz_line1,
            "mrz_line2": mrz_line2,
            "mrz": mrz,
            "gender": gender,
            "dataset_source": DATASET_NAME,
            "dataset_split": "train",
            "imported_at": datetime.utcnow()
        }

        valid_documents.append(document)

        print(
            f"✓ {passport_number} | "
            f"{given_name} {surname} | "
            f"DOB: {date_of_birth}"
        )

    print()
    print("=" * 60)
    print("VALID DOCUMENTS:", len(valid_documents))
    print("=" * 60)

    if valid_documents:

        result = reference_passports.insert_many(valid_documents)

        print("Inserted into MongoDB:", len(result.inserted_ids))

    else:
        print("No valid documents found.")

    print()
    print("=" * 60)
    print("IMPORT COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    import_dataset()