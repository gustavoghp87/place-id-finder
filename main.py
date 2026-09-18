# Steps:
#  1. Copy the "Payment Locations" folder in the same directory as this script.
#  2. Set your Google Maps API key in the .env file.
#  3. Set the referrer in the .env file.
#  4. Create a virtual environment and install the required packages.
#  5. Run this script.
#  6. Replace the TDS items with the result in the folder "Payment Locations - results"


from dotenv import load_dotenv
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
from typing import Any
from typing import Any
import json
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
TEST_LIMIT = 5

MAX_DISTANCE_METERS = 300

REQUEST_DELAY_SECONDS = 0.1

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
        # We only need a small number of candidates.
        "pageSize": 5,
    }
    response = requests.post(
        URL,
        headers=HEADERS,
        json=payload,
        timeout=20,
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
    return {
        "ok": True,
        "results": places,
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

    output_file = "places_results.json"
    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
        )
    print()
    print("=" * 80)
    print(f"Saved results to: {output_file}")
    print("=" * 80)

if __name__ == "__main__":
    main()
