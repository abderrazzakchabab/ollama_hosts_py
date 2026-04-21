# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Discovers publicly exposed Ollama instances with GPUs via Shodan, geocodes them, and visualizes them on an interactive 3D globe.

## Pipeline (run in order)

```bash
# 1. Scan Shodan for Ollama hosts with GPUs → ollama_gpu_hosts.csv
export SHODAN_API_KEY="your_key_here"
python ollama_gpu_scanner.py

# 2. Geocode hosts by city/country via Nominatim → geocode_cache.json + webapp/hosts_geo.json
python geocode_cities.py

# 3. (Optional) Retry failed geocodes with cleaned country names
python geocode_fix.py

# 4. (Optional) Rebuild hosts_geo.json from existing cache without re-geocoding
python rebuild_json.py

# 5. Serve the webapp
cd webapp && python -m http.server 8080
```

## Dependencies

```bash
pip install shodan requests
```

No requirements.txt exists — dependencies are only `shodan` and `requests`.

## Architecture

**Data flow:** Shodan API → `ollama_gpu_hosts.csv` → geocoding → `webapp/hosts_geo.json` → browser globe

**Scripts:**
- `ollama_gpu_scanner.py` — queries Shodan (`port:11434 product:"Ollama"`), then probes each host via `/api/ps`, `/api/tags`, `/api/show`, and `/api/generate` to detect GPU presence. Uses `ThreadPoolExecutor` (20 workers) for parallel probing. GPU detection uses size_vram > 0, model_info keys, or inferred throughput > 30 tok/s.
- `geocode_cities.py` — preferred geocoder; uses Nominatim (OSM) at 1 req/sec; maintains `geocode_cache.json` to avoid re-querying.
- `geocode_hosts.py` — alternative geocoder using ip-api.com batch API (by IP, not city).
- `geocode_fix.py` — retries `None` entries in `geocode_cache.json` with normalized country names (see `COUNTRY_FIXES` dict) and progressively looser queries.
- `rebuild_json.py` — regenerates `webapp/hosts_geo.json` from the CSV + existing cache, without any network calls.

**Webapp (`webapp/index.html`):** Pure browser app using Three.js (CDN, v0.170.0). Loads `hosts_geo.json` via `fetch`. Renders a textured Earth sphere with host points colored by VRAM tier (green/yellow/red/pink). Points are drawn with a custom GLSL shader for glow. Supports raycaster-based hover tooltips, indexed search (country/city/org/model/IP), and auto-rotation toggle.

## Key constants

- `ollama_gpu_scanner.py`: `MAX_WORKERS=20`, `REQUEST_TIMEOUT=10s`, GPU throughput threshold `>30 tok/s`
- `geocode_cities.py`: Nominatim rate limit `1.1s` delay between requests
- `geocode_hosts.py`: ip-api.com rate limit `4.5s` delay per batch of 100
- `webapp/index.html`: `GLOBE_RADIUS=5`, `POINT_BASE_SIZE=0.04`
