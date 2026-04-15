#!/usr/bin/env python3
"""Rebuild hosts_geo.json using the geocode cache."""
import csv, json

cache = json.load(open("geocode_cache.json"))
rows = list(csv.DictReader(open("ollama_gpu_hosts.csv")))

hosts = []
for row in rows:
    key = f"{row.get('city','').strip()}|{row.get('country','').strip()}"
    geo = cache.get(key)
    if not geo:
        continue
    vram_gb = int(row.get("gpu_vram_bytes", 0) or 0) / (1024**3)
    hosts.append({
        "ip": row["ip"],
        "port": int(row["port"]),
        "lat": geo["lat"],
        "lon": geo["lon"],
        "org": row.get("org", ""),
        "country": row.get("country", "").strip(),
        "city": row.get("city", "").strip(),
        "gpu": row.get("gpu_name", ""),
        "vram_gb": round(vram_gb, 1),
        "models": row.get("available_models", ""),
    })

with open("webapp/hosts_geo.json", "w") as f:
    json.dump(hosts, f)

print(f"Wrote {len(hosts)} hosts (from {len(rows)} total)")

# Verify Madrid
for h in hosts:
    if h["ip"] == "93.174.5.66":
        print(f"Madrid check: lat={h['lat']}, lon={h['lon']}")
