#!/usr/bin/env python3
"""
Scan Shodan for public Ollama instances and check which ones have GPUs.
Writes results to a CSV file.

Requirements:
    pip install shodan requests

Usage:
    export SHODAN_API_KEY="your_key_here"
    python ollama_gpu_scanner.py
"""

import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import shodan

SHODAN_QUERY = 'port:11434 product:"Ollama"'
OUTPUT_CSV = "ollama_gpu_hosts.csv"
REQUEST_TIMEOUT = 10  # seconds per request
MAX_WORKERS = 20


def get_shodan_results(api_key: str, query: str) -> list[dict]:
    """Search Shodan and return list of host results."""
    api = shodan.Shodan(api_key)
    hosts = []
    page = 1

    print(f"[*] Searching Shodan: {query}")
    try:
        results = api.search(query, page=page)
        total = results["total"]
        print(f"[*] Total results found: {total}")

        for match in results["matches"]:
            hosts.append({
                "ip": match["ip_str"],
                "port": match["port"],
                "org": match.get("org", "N/A"),
                "country": match.get("location", {}).get("country_name", "N/A"),
                "city": match.get("location", {}).get("city", "N/A"),
            })

        # Fetch additional pages (Shodan returns 100 per page)
        while len(hosts) < total:
            page += 1
            try:
                results = api.search(query, page=page)
                if not results["matches"]:
                    break
                for match in results["matches"]:
                    hosts.append({
                        "ip": match["ip_str"],
                        "port": match["port"],
                        "org": match.get("org", "N/A"),
                        "country": match.get("location", {}).get("country_name", "N/A"),
                        "city": match.get("location", {}).get("city", "N/A"),
                    })
                print(f"    Fetched page {page} ({len(hosts)}/{total})")
            except shodan.APIError as e:
                print(f"[!] Shodan API error on page {page}: {e}")
                break

    except shodan.APIError as e:
        print(f"[!] Shodan API error: {e}")
        sys.exit(1)

    print(f"[*] Collected {len(hosts)} hosts")
    return hosts


def check_ollama_gpu(host: dict) -> dict | None:
    """
    Check if an Ollama instance has a GPU by querying its API.

    Strategy:
      1. GET /api/ps   -> shows running models with GPU layer info
      2. GET /api/tags -> lists available models (fallback to load one)

    Returns enriched host dict if GPU detected, else None.
    """
    ip = host["ip"]
    port = host["port"]
    base_url = f"http://{ip}:{port}"

    gpu_info = {
        "gpu_detected": False,
        "gpu_name": "",
        "gpu_vram_bytes": 0,
        "running_models": "",
        "available_models": "",
    }

    try:
        # Step 1: Check /api/ps for running models with GPU info
        resp = requests.get(f"{base_url}/api/ps", timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            running_names = []

            for model in models:
                name = model.get("name", "unknown")
                running_names.append(name)
                size_vram = model.get("size_vram", 0)
                size = model.get("size", 0)

                # If size_vram > 0, GPU is being used
                if size_vram > 0:
                    gpu_info["gpu_detected"] = True
                    gpu_info["gpu_vram_bytes"] = max(gpu_info["gpu_vram_bytes"], size_vram)

                # Check details.gpu_layers or similar fields
                details = model.get("details", {})
                if details:
                    gpu_name = details.get("gpu", "")
                    if gpu_name:
                        gpu_info["gpu_name"] = gpu_name

            gpu_info["running_models"] = ", ".join(running_names)

        # Step 2: Check /api/tags for available models
        resp = requests.get(f"{base_url}/api/tags", timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            model_names = [m.get("name", "unknown") for m in models]
            gpu_info["available_models"] = ", ".join(model_names[:10])  # cap at 10

            # Step 3: If no running models found, try /api/show on first available model
            # to get more system details
            if not gpu_info["gpu_detected"] and model_names:
                try:
                    resp = requests.post(
                        f"{base_url}/api/show",
                        json={"name": model_names[0]},
                        timeout=REQUEST_TIMEOUT,
                    )
                    if resp.status_code == 200:
                        show_data = resp.json()
                        model_info = show_data.get("model_info", {})

                        # Check for GPU-related keys in model_info
                        for key, val in model_info.items():
                            if "gpu" in key.lower():
                                gpu_info["gpu_detected"] = True
                                if isinstance(val, str):
                                    gpu_info["gpu_name"] = val
                except Exception:
                    pass

        # Step 4: If still unknown, try a minimal generate to trigger GPU detection
        # The /api/generate response sometimes includes GPU info in headers or metrics
        if not gpu_info["gpu_detected"] and gpu_info["available_models"]:
            first_model = gpu_info["available_models"].split(",")[0].strip()
            try:
                resp = requests.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": first_model,
                        "prompt": "hi",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    gen_data = resp.json()
                    # Check eval metrics — GPU inference is significantly faster
                    eval_count = gen_data.get("eval_count", 0)
                    eval_duration = gen_data.get("eval_duration", 1)
                    if eval_count > 0 and eval_duration > 0:
                        tokens_per_sec = eval_count / (eval_duration / 1e9)
                        # GPU typically > 30 tok/s, CPU typically < 15 tok/s
                        if tokens_per_sec > 30:
                            gpu_info["gpu_detected"] = True
                            gpu_info["gpu_name"] = gpu_info["gpu_name"] or f"Unknown (inferred, {tokens_per_sec:.1f} tok/s)"

                    # After generate, re-check /api/ps — model should now be loaded
                    resp2 = requests.get(f"{base_url}/api/ps", timeout=REQUEST_TIMEOUT)
                    if resp2.status_code == 200:
                        ps_data = resp2.json()
                        for model in ps_data.get("models", []):
                            size_vram = model.get("size_vram", 0)
                            if size_vram > 0:
                                gpu_info["gpu_detected"] = True
                                gpu_info["gpu_vram_bytes"] = max(
                                    gpu_info["gpu_vram_bytes"], size_vram
                                )
                            details = model.get("details", {})
                            if details.get("gpu"):
                                gpu_info["gpu_name"] = details["gpu"]
            except Exception:
                pass

    except requests.exceptions.RequestException:
        print(f"    [-] {ip}:{port} — connection failed")
        return None
    except Exception as e:
        print(f"    [-] {ip}:{port} — error: {e}")
        return None

    if gpu_info["gpu_detected"]:
        vram_gb = gpu_info["gpu_vram_bytes"] / (1024**3) if gpu_info["gpu_vram_bytes"] else 0
        gpu_label = gpu_info["gpu_name"] or "Detected (name unknown)"
        vram_str = f"{vram_gb:.1f} GB" if vram_gb > 0 else "N/A"
        print(f"    [+] {ip}:{port} — GPU: {gpu_label} | VRAM: {vram_str}")
        return {**host, **gpu_info}

    print(f"    [ ] {ip}:{port} — no GPU detected")
    return None


def write_csv(gpu_hosts: list[dict], output_path: str):
    """Write GPU-equipped hosts to CSV."""
    if not gpu_hosts:
        print("[!] No GPU hosts found. CSV not written.")
        return

    fieldnames = [
        "ip",
        "port",
        "org",
        "country",
        "city",
        "gpu_name",
        "gpu_vram_bytes",
        "running_models",
        "available_models",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(gpu_hosts)

    print(f"[*] Wrote {len(gpu_hosts)} GPU hosts to {output_path}")


def main():
    api_key = os.environ.get("SHODAN_API_KEY")
    if not api_key:
        print("Error: Set SHODAN_API_KEY environment variable.")
        print("  export SHODAN_API_KEY='your_key_here'")
        sys.exit(1)

    # 1. Gather hosts from Shodan
    hosts = get_shodan_results(api_key, SHODAN_QUERY)
    if not hosts:
        print("[!] No hosts found. Exiting.")
        sys.exit(0)

    # 2. Check each host for GPU in parallel
    print(f"\n[*] Checking {len(hosts)} hosts for GPU...")
    gpu_hosts = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_host = {
            executor.submit(check_ollama_gpu, host): host for host in hosts
        }
        for future in as_completed(future_to_host):
            result = future.result()
            if result:
                gpu_hosts.append(result)

    # 3. Write CSV
    print(f"\n[*] Summary: {len(gpu_hosts)}/{len(hosts)} hosts have GPU")
    write_csv(gpu_hosts, OUTPUT_CSV)


if __name__ == "__main__":
    main()
