from dotenv import load_dotenv
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

REQUEST_DELAY_SECONDS = 0.1

URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.id,"
    "places.nationalPhoneNumber,"
    "places.formattedAddress,"
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

BUSINESSES: list[dict[str, Any]] = [
    {
        "name": "River Valley Credit Union",
        "address": "1369 Industrial Park Dr., Edmore, MI 48829",
        "latitude": 43.406215,
        "longitude": -85.0309697,
    },
]


# ============================================================
# GOOGLE PLACES
# ============================================================

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

    return {
        "ok": True,
        "results": data.get("places", []),
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
