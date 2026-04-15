#!/usr/bin/env python3
"""
Geocode CSV hosts by IP using ip-api.com batch API (free, no key needed).
Produces hosts_geo.json for the globe visualization.
"""

import csv
import json
import time
import requests

INPUT_CSV = "ollama_gpu_hosts.csv"
OUTPUT_JSON = "webapp/hosts_geo.json"

def batch_geocode_ips(ips, batch_size=100):
    """Geocode IPs using ip-api.com batch endpoint (max 100 per request)."""
    results = {}
    for i in range(0, len(ips), batch_size):
        batch = ips[i:i + batch_size]
        payload = [{"query": ip, "fields": "query,lat,lon,status"} for ip in batch]
        try:
            resp = requests.post(
                "http://ip-api.com/batch?fields=query,lat,lon,status",
                json=payload,
                timeout=30,
            )
            if resp.status_code == 200:
                for item in resp.json():
                    if item.get("status") == "success":
                        results[item["query"]] = {
                            "lat": item["lat"],
                            "lon": item["lon"],
                        }
            # Rate limit: 15 requests per minute for batch
            if i + batch_size < len(ips):
                time.sleep(4.5)
        except Exception as e:
            print(f"  Error on batch {i}: {e}")

        done = min(i + batch_size, len(ips))
        print(f"  Geocoded {done}/{len(ips)} IPs ({len(results)} resolved)")

    return results


def main():
    import os
    os.makedirs("webapp", exist_ok=True)

    # Read CSV
    with open(INPUT_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"[*] Loaded {len(rows)} hosts from CSV")

    # Get unique IPs
    unique_ips = list(set(row["ip"] for row in rows))
    print(f"[*] {len(unique_ips)} unique IPs to geocode")

    # Geocode
    print("[*] Geocoding via ip-api.com batch API...")
    geo = batch_geocode_ips(unique_ips)
    print(f"[*] Successfully geocoded {len(geo)} IPs")

    # Build output
    hosts = []
    for row in rows:
        ip = row["ip"]
        if ip not in geo:
            continue
        vram_gb = int(row.get("gpu_vram_bytes", 0) or 0) / (1024**3)
        hosts.append({
            "ip": ip,
            "port": int(row["port"]),
            "lat": geo[ip]["lat"],
            "lon": geo[ip]["lon"],
            "org": row.get("org", ""),
            "country": row.get("country", ""),
            "city": row.get("city", ""),
            "gpu": row.get("gpu_name", ""),
            "vram_gb": round(vram_gb, 1),
            "models": row.get("available_models", ""),
        })

    with open(OUTPUT_JSON, "w") as f:
        json.dump(hosts, f)

    print(f"[*] Wrote {len(hosts)} hosts to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
