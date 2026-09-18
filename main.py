from datetime import datetime, timezone
from difflib import SequenceMatcher
from dotenv import load_dotenv
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
from pathlib import Path
from typing import Any
from typing import Any
from typing import Any
from uuid import uuid4
import os
import requests
import sys
import time

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

REFERER = os.getenv("REFERER", "")

# 0 = no limit
# 5 = process only the first 5 businesses
TEST_LIMIT = 0

MAX_DISTANCE_METERS = 300

PAGE_SIZE = 3

REQUEST_DELAY_SECONDS = 0.1

TIMEOUT_SECONDS = 20

URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.id,"
    "places.nationalPhoneNumber,"
    "places.formattedAddress,"
    "places.location,"
    "places.shortFormattedAddress,"
    "places.viewport,"
    "places.googleMapsUri,"
    "places.regularOpeningHours,"
    "places.displayName,"
    "places.currentOpeningHours,"
    "places.currentSecondaryOpeningHours,"
    "places.regularSecondaryOpeningHours"
)

HEADERS = {
    "Content-Type": "application/json",
    "X-Goog-FieldMask": FIELD_MASK,
    "X-Goog-Api-Key": API_KEY,
    "Referer": REFERER,
}

PAYMENT_LOCATIONS_RESULTS_FOLDER = (
    Path(__file__).resolve().parent / "Payment Locations - Results"
)

# ============================================================
# INPUT
# ============================================================

PAYMENT_LOCATIONS_FOLDER = Path(__file__).resolve().parent / "Payment Locations"

FIELD_MARKERS = {
    "name": "name: Store Name",
    "address": "name: Store Address",
    "latitude": "name: Latitude",
    "longitude": "name: Longitude",
}

def extract_line_value(line: str) -> str:
    value = line.strip()
    if ":" in value:
        value = value.split(":", 1)[1].strip()
    return value.strip("\"'")


def parse_business_file(file_path: Path) -> dict[str, Any]:
    lines = file_path.read_text(encoding="utf-8-sig").splitlines()
    values: dict[str, str] = {
        "name": "",  # name is optional
    }
    for index, line in enumerate(lines):
        for field_name, marker in FIELD_MARKERS.items():
            if marker in line:
                value_index = index + 4
                if value_index >= len(lines):
                    raise ValueError(
                        f"{file_path}: the line located "
                        f"4 lines below '{marker}' does not exist."
                    )
                value = extract_line_value(lines[value_index])
                if not value:
                    value = ""
                    # raise ValueError(
                    #     f"{file_path}: the value of '{field_name}' is empty."
                    # )
                values[field_name] = value  # takes the last version
    required_fields = {"address", "latitude", "longitude"}  # name is optional
    missing_fields = required_fields - values.keys()
    if missing_fields:
        raise ValueError(
            f"{file_path}: Missing field: "
            f"{', '.join(sorted(missing_fields))}."
        )
    try:
        latitude = float(values["latitude"])
        longitude = float(values["longitude"])
    except ValueError as error:
        # raise ValueError(
        #     f"{file_path}: latitude or longitude are not valid numbers."
        # ) from error
        print(f"Skipping {file_path}")
        return None
    return {
        "name": values["name"],
        "address": values["address"],
        "latitude": latitude,
        "longitude": longitude,
        "source_file": str(
            file_path.relative_to(PAYMENT_LOCATIONS_FOLDER)
        ),
    }

def load_businesses() -> list[dict[str, Any]]:
    if not PAYMENT_LOCATIONS_FOLDER.is_dir():
        raise FileNotFoundError(
            f"Folder not found: {PAYMENT_LOCATIONS_FOLDER}"
        )
    files = sorted(
        path
        for path in PAYMENT_LOCATIONS_FOLDER.rglob("*")
        if path.is_file()
    )
    businesses: list[dict[str, Any]] = []
    for path in files:
        result = parse_business_file(path)
        if result:  # Only append if the result is not None or empty
            businesses.append(result)
    return businesses

BUSINESSES: list[dict[str, Any]] = load_businesses()


# ============================================================
# GOOGLE PLACES
# ============================================================

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def search_business(business: dict[str, Any]) -> dict[str, Any]:
    """
    Search Google Places using the business name + address,
    biased toward the known coordinates.
    """
    query = f"{business['name']}, {business['address']}"
    payload = {
        "textQuery": query,
        # Bias the search toward the coordinates we already know.
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": business["latitude"],
                    "longitude": business["longitude"],
                },
                "radius": 500.0,
            }
        },
        "pageSize": PAGE_SIZE,
    }
    response = requests.post(
        URL,
        headers=HEADERS,
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": response.text,
        }
    data = response.json()
    places = data.get("places", [])
    places = [
        p for p in places
        if distance_meters(
            business["latitude"],
            business["longitude"],
            p["location"]["latitude"],
            p["location"]["longitude"],
        ) <= MAX_DISTANCE_METERS
    ]
    if not places:
        return {
            "ok": True,
            "results": [],
        }
    best_place = max(
        places,
        key=lambda p: similarity(
            business["name"],
            p["displayName"]["text"]
        )
    )
    return {
        "ok": True,
        "results": [best_place],
    }


# ============================================================
# OUTPUT
# ============================================================

def print_result(
    index: int,
    total: int,
    business: dict[str, Any],
    result: dict[str, Any],
) -> None:
    print()
    print("=" * 80)
    print(f"[{index}/{total}] {business['name']}")
    print(f"Address: {business['address']}")
    if not result["ok"]:
        print(f"ERROR ({result['status_code']}):")
        print(result["error"])
        return
    places = result["results"]
    if not places:
        print("NO RESULTS")
        return
    print(f"Candidates: {len(places)}")
    print()
    for candidate_index, place in enumerate(places, start=1):
        display_name = place.get("displayName", {}).get("text")
        print(f"--- Candidate {candidate_index} ---")
        print(f"Place ID:       {place.get('id')}")
        print(f"Name:           {display_name}")
        print(f"Address:        {place.get('formattedAddress')}")
        print(f"Short address:  {place.get('shortFormattedAddress')}")
        print(f"Phone:          {place.get('nationalPhoneNumber')}")
        print(f"Maps URL:       {place.get('googleMapsUri')}")
        current_hours = place.get("currentOpeningHours")
        if current_hours:
            print("Current hours:  YES")
        else:
            print("Current hours:  NO")
        regular_hours = place.get("regularOpeningHours")
        if regular_hours:
            print("Regular hours:  YES")
        else:
            print("Regular hours:  NO")
        print()

def find_last_line(
    lines: list[str],
    text: str,
    file_path: Path,
) -> int:
    matches = [
        index
        for index, line in enumerate(lines)
        if line.strip() == text
    ]
    if not matches:
        raise ValueError(
            f"{file_path}: no se encontró '{text}'."
        )
    return matches[-1]

def get_place_id(result: dict[str, Any]) -> str | None:
    google_result = result.get("google", {})
    if not google_result.get("ok"):
        return None
    places = google_result.get("results", [])
    if not places:
        return None
    place_id = places[0].get("id")
    if not place_id:
        raise ValueError(
            f"Place ID not found for "
            f"{result['business']['source_file']}."
        )
    return place_id


def create_result_file(
    result: dict[str, Any],
    updated_date: str,
) -> None:
    business = result["business"]
    place_id = get_place_id(result)
    if place_id is None:
        return
    relative_path = Path(business["source_file"])
    source_file = PAYMENT_LOCATIONS_FOLDER / relative_path
    destination_file = (
        PAYMENT_LOCATIONS_RESULTS_FOLDER / relative_path
    )
    if not source_file.is_file():
        raise FileNotFoundError(
            f"Original file not found: {source_file}"
        )
    text = source_file.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError(
            f"{source_file}: the file is empty."
        )
    new_revision = str(uuid4())
    version_index = find_last_line(
        lines,
        "----version----",
        source_file,
    )
    revision_line_index = version_index + 3
    if revision_line_index >= len(lines):
        raise ValueError(
            f"{source_file}: the revision located "
            f"3 lines below '----version----' does not exist."
        )
    if not lines[revision_line_index].strip().startswith("revision:"):
        raise ValueError(
            f"{source_file}: missing 'revision:' in line "
            f"{revision_line_index + 1}."
        )
    lines[revision_line_index] = f"revision: {new_revision}"
    revision_field_index = find_last_line(
        lines,
        "name: __Revision",
        source_file,
    )
    revision_value_index = revision_field_index + 4
    if revision_value_index >= len(lines):
        raise ValueError(
            f"{source_file}: the value of __Revision does not exist."
        )
    lines[revision_value_index] = new_revision
    updated_field_index = find_last_line(
        lines,
        "name: __Updated",
        source_file,
    )
    updated_value_index = updated_field_index + 4
    if updated_value_index >= len(lines):
        raise ValueError(
            f"{source_file}: the value of __Updated does not exist."
        )
    lines[updated_value_index] = updated_date
    lines[-1] = r"sitecore\admin"
    place_id_field = [
        "",
        "----field----",
        "field: {D62F908D-74BF-4987-9CAB-3B6982F1ADAA}",
        "name: Place ID",
        "key: place id",
        f"content-length: {len(place_id.encode('utf-8'))}",
        "",
        place_id,
    ]
    insert_index = revision_line_index + 2
    lines[insert_index:insert_index] = place_id_field
    destination_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination_file.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

# ============================================================
# MAIN
# ============================================================

def main() -> None:
    if not API_KEY or API_KEY == "":
        print(
            "ERROR: Set GOOGLE_MAPS_API_KEY"
        )
        sys.exit(1)
    total_available = len(BUSINESSES)
    if TEST_LIMIT > 0:
        businesses = BUSINESSES[:TEST_LIMIT]
    else:
        businesses = BUSINESSES
    total = len(businesses)
    print("=" * 80)
    print("Google Places batch lookup")
    print("=" * 80)
    print(f"Total businesses: {total_available}")
    print(f"Processing:       {total}")
    print(f"Test limit:       {TEST_LIMIT}")
    print()
    results: list[dict[str, Any]] = []
    for index, business in enumerate(businesses, start=1):
        result = search_business(business)
        print_result(
            index,
            total,
            business,
            result,
        )
        results.append(
            {
                "business": business,
                "google": result,
            }
        )
        # Don't delay after the last request.
        if index < total:
            time.sleep(REQUEST_DELAY_SECONDS)

    # --------------------------------------------------------
    # Save complete results
    # --------------------------------------------------------

    PAYMENT_LOCATIONS_RESULTS_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )
    updated_date = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    created_files = 0
    for result in results:
        place_id = get_place_id(result)
        if place_id is None:
            continue
        create_result_file(
            result,
            updated_date,
        )
        created_files += 1
    print()
    print("=" * 80)
    print(
        f"Created {created_files} files in: "
        f"{PAYMENT_LOCATIONS_RESULTS_FOLDER}"
    )
    print("=" * 80)

if __name__ == "__main__":
    main()
