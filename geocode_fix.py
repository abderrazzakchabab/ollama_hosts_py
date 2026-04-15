#!/usr/bin/env python3
"""
Retry failed geocodes with cleaned-up queries + country-capital fallback.
"""

import json
import time
import requests

CACHE_FILE = "geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "OllamaGlobeViz/1.0 (research project)"}

# Clean up long country names
COUNTRY_FIXES = {
    "Bolivia, Plurinational State of": "Bolivia",
    "Brunei Darussalam": "Brunei",
    "Congo, The Democratic Republic of the": "Democratic Republic of the Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Iran, Islamic Republic of": "Iran",
    "Korea, Republic of": "South Korea",
    "Lao People's Democratic Republic": "Laos",
    "Moldova, Republic of": "Moldova",
    "Palestine, State of": "Palestine",
    "Russian Federation": "Russia",
    "Syrian Arab Republic": "Syria",
    "Taiwan, Province of China": "Taiwan",
    "Tanzania, United Republic of": "Tanzania",
    "Venezuela, Bolivarian Republic of": "Venezuela",
    "Viet Nam": "Vietnam",
}


def geocode(query):
    params = {"q": query, "format": "json", "limit": 1, "accept-language": "en"}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            results = resp.json()
            if results:
                return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}
    except Exception as e:
        print(f"  Error: {e}")
    return None


def main():
    cache = json.load(open(CACHE_FILE))
    failed = {k: v for k, v in cache.items() if v is None}
    print(f"[*] {len(failed)} failed entries to retry")

    fixed = 0
    for i, key in enumerate(sorted(failed.keys())):
        city, country = key.split("|", 1)

        # Fix country name
        clean_country = COUNTRY_FIXES.get(country, country)

        # Strategy 1: city + cleaned country
        result = geocode(f"{city}, {clean_country}")
        if result:
            cache[key] = result
            fixed += 1
            time.sleep(1.1)
            if fixed % 20 == 0:
                print(f"  [{fixed}] {city}, {clean_country} -> OK")
                json.dump(cache, open(CACHE_FILE, "w"))
            continue

        time.sleep(1.1)

        # Strategy 2: just the city name
        result = geocode(city)
        if result:
            cache[key] = result
            fixed += 1
            time.sleep(1.1)
            if fixed % 20 == 0:
                print(f"  [{fixed}] {city} (alone) -> OK")
                json.dump(cache, open(CACHE_FILE, "w"))
            continue

        time.sleep(1.1)

        # Strategy 3: just the country (use country center as fallback)
        result = geocode(clean_country)
        if result:
            cache[key] = result
            fixed += 1
            time.sleep(1.1)
            continue

        time.sleep(1.1)

    json.dump(cache, open(CACHE_FILE, "w"))
    total_resolved = sum(1 for v in cache.values() if v is not None)
    print(f"\n[*] Fixed {fixed} entries. Total resolved: {total_resolved}/{len(cache)}")


if __name__ == "__main__":
    main()
