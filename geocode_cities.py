#!/usr/bin/env python3
"""
Geocode hosts by city+country using OpenStreetMap Nominatim API.
This gives precise city-center coordinates instead of approximate IP geolocation.
Produces webapp/hosts_geo.json for the globe visualization.
"""

import csv
import json
import time
import requests
import sys

INPUT_CSV = "ollama_gpu_hosts.csv"
OUTPUT_JSON = "webapp/hosts_geo.json"
CACHE_FILE = "geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "OllamaGlobeViz/1.0 (research project)"}


def load_cache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def geocode_city(city, country, cache):
    """Geocode a city+country pair using Nominatim."""
    key = f"{city}|{country}"
    if key in cache:
        return cache[key]

    # Try city + country first
    params = {
        "q": f"{city}, {country}",
        "format": "json",
        "limit": 1,
        "accept-language": "en",
    }

    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                cache[key] = {"lat": lat, "lon": lon}
                return cache[key]

        # Fallback: try just the city name
        params["q"] = city
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                cache[key] = {"lat": lat, "lon": lon}
                return cache[key]

    except Exception as e:
        print(f"    Error geocoding {city}, {country}: {e}")

    cache[key] = None
    return None


def main():
    import os
    os.makedirs("webapp", exist_ok=True)

    # Read CSV
    with open(INPUT_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[*] Loaded {len(rows)} hosts from CSV")

    # Get unique city/country pairs
    pairs = set()
    for r in rows:
        city = r.get("city", "").strip()
        country = r.get("country", "").strip()
        if city and country:
            pairs.add((city, country))
    print(f"[*] {len(pairs)} unique city/country pairs to geocode")

    # Load cache
    cache = load_cache()
    cached_count = sum(1 for c, co in pairs if f"{c}|{co}" in cache)
    print(f"[*] {cached_count} already cached, {len(pairs) - cached_count} to fetch")

    # Geocode each pair (Nominatim rate limit: 1 req/sec)
    done = 0
    for city, country in sorted(pairs):
        key = f"{city}|{country}"
        if key not in cache:
            result = geocode_city(city, country, cache)
            done += 1
            status = "OK" if result else "MISS"
            if done % 20 == 0 or done == len(pairs) - cached_count:
                save_cache(cache)
                print(f"    [{done}/{len(pairs) - cached_count}] {city}, {country} -> {status}")
            time.sleep(1.1)  # Nominatim requires max 1 req/sec

    save_cache(cache)

    resolved = sum(1 for v in cache.values() if v is not None)
    print(f"[*] Geocoding complete: {resolved}/{len(pairs)} resolved")

    # Build output JSON
    hosts = []
    skipped = 0
    for row in rows:
        city = row.get("city", "").strip()
        country = row.get("country", "").strip()
        key = f"{city}|{country}"

        geo = cache.get(key)
        if not geo:
            skipped += 1
            continue

        vram_gb = int(row.get("gpu_vram_bytes", 0) or 0) / (1024**3)
        hosts.append({
            "ip": row["ip"],
            "port": int(row["port"]),
            "lat": geo["lat"],
            "lon": geo["lon"],
            "org": row.get("org", ""),
            "country": country,
            "city": city,
            "gpu": row.get("gpu_name", ""),
            "vram_gb": round(vram_gb, 1),
            "models": row.get("available_models", ""),
        })

    with open(OUTPUT_JSON, "w") as f:
        json.dump(hosts, f)

    print(f"[*] Wrote {len(hosts)} hosts to {OUTPUT_JSON} (skipped {skipped})")


if __name__ == "__main__":
    main()
