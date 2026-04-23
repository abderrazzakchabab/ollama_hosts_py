# 5,000+ Ollama Instances Exposed to the Internet — And Most Don't Know It

*How a single environment variable silently exposes your local LLM to anyone on the internet — and what we found when we went looking.*

---

## The One-Liner That Opens Your AI to the World

If you have ever run a local LLM with Ollama and followed a tutorial that included Docker or remote access, you have probably seen this command:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

It looks harmless. It is not.

Setting `OLLAMA_HOST=0.0.0.0` tells Ollama to listen on **every network interface** — not just `localhost`. On a VPS, home server, or cloud VM with no firewall in front, that single variable puts your model inference API directly on the public internet with **zero authentication**.

---

## What Can an Attacker Do With an Open Ollama Port?

Ollama's REST API has no built-in authentication. Anyone who can reach port `11434` can:

| Endpoint | What it exposes |
|---|---|
| `GET /api/tags` | List every model you have downloaded |
| `POST /api/generate` | Run inference on your GPU — on **your electricity bill** |
| `POST /api/pull` | Pull new models to your disk |
| `POST /api/show` | Read model metadata and system prompts |
| `DELETE /api/delete` | **Delete your models** |
| `POST /api/chat` | Full multi-turn conversation with any loaded model |

There is no rate limit, no API key, no IP allowlist. The only barrier is knowing the IP address — and Shodan knows them all.

### Concrete risks

- **GPU hijacking** — attackers run massive inference jobs for free on your hardware, driving your cloud compute bill to hundreds or thousands of dollars overnight.
- **Data exfiltration** — any model loaded with a custom system prompt (containing proprietary instructions, RAG context, or business logic) is fully readable via `/api/show`.
- **Model manipulation** — an attacker can pull a backdoored or jailbroken model onto your server, replacing a trusted model name.
- **Pivoting** — the host running Ollama often has other services on the same internal network. An exposed API becomes a foothold.
- **Prompt injection at scale** — researchers can freely study, benchmark, or abuse your deployed models without your knowledge or consent.

---

## We Went Looking — Here Is What We Found

Using the Shodan query `port:11434 product:"Ollama"`, we scanned every publicly reachable Ollama instance and probed each one to detect GPU presence. The results were collected, geocoded, and rendered on an interactive 3D globe at **[ollama.chabab.online](https://ollama.chabab.online)**.

![Interactive 3D globe showing 5,062 publicly exposed Ollama GPU hosts across 95 countries](https://www.chabab.tech/screenshot.png)

*ollama.chabab.online — 5,062 publicly exposed Ollama hosts with GPU, spanning 95 countries. Green = <8 GB VRAM, yellow = 8–16 GB, red = 16–24 GB, pink = >24 GB.*

### The numbers

| Metric | Count |
|---|---|
| Total exposed Ollama hosts (GPU-confirmed) | **5,062** |
| Countries represented | **95** |
| Hosts with measurable VRAM data | **1,682** |
| Shodan estimates for *all* Ollama hosts (including CPU) | **~50,000+** |

The top countries by exposed host count:

| Country | Hosts |
|---|---|
| Germany | 1,019 |
| United States | 912 |
| China | 818 |
| France | 447 |
| South Korea | 195 |
| Finland | 156 |
| India | 151 |
| Singapore | 110 |
| United Kingdom | 98 |
| Canada | 87 |

These are not abandoned servers. Many had models actively loaded in memory (`/api/ps` returned running processes). Some had frontier models — **Llama 3.3 70B**, **DeepSeek-R1**, **Qwen2.5-72B** — running on high-end consumer GPUs. One host in Germany had over 48 GB of VRAM actively serving inference.

---

## How the Scanner Works — `ollama_gpu_scanner.py`

The script is straightforward and is [available on GitHub](https://github.com/abderrazzakchabab/ollama_hosts_py).

### Phase 1 — Discover hosts via Shodan

```python
SHODAN_QUERY = 'port:11434 product:"Ollama"'

def get_shodan_results(api_key: str, query: str) -> list[dict]:
    api = shodan.Shodan(api_key)
    results = api.search(query, page=1)
    # paginate through all results (100 per page)
    ...
```

Shodan has already done the scanning. We just query its index. Each result gives us `ip`, `port`, `org`, `country`, and `city` — all from Shodan's passive data, so no active probing yet.

### Phase 2 — Probe each host for GPU evidence

For each discovered host we fire up to 4 API calls, in order of reliability:

```python
def check_ollama_gpu(host: dict) -> dict | None:
    base_url = f"http://{ip}:{port}"

    # Step 1: /api/ps — running models show size_vram > 0 if GPU is used
    resp = requests.get(f"{base_url}/api/ps", timeout=10)

    # Step 2: /api/tags — enumerate available models
    resp = requests.get(f"{base_url}/api/tags", timeout=10)

    # Step 3: /api/show on first model — check model_info for GPU keys
    resp = requests.post(f"{base_url}/api/show", json={"name": model_names[0]}, timeout=10)

    # Step 4: /api/generate with 1 token — if throughput > 30 tok/s, infer GPU
    resp = requests.post(f"{base_url}/api/generate",
        json={"model": first_model, "prompt": "hi", "stream": False,
              "options": {"num_predict": 1}}, timeout=30)
    tokens_per_sec = eval_count / (eval_duration / 1e9)
    if tokens_per_sec > 30:
        gpu_detected = True
```

The throughput heuristic (`>30 tok/s → GPU`) is the most novel part. CPU inference on typical models tops out around 10–15 tok/s; any consumer GPU easily clears 30 tok/s on a 1-token generation.

### Phase 3 — Parallel execution

```python
with ThreadPoolExecutor(max_workers=20) as executor:
    future_to_host = {executor.submit(check_ollama_gpu, host): host for host in hosts}
    for future in as_completed(future_to_host):
        result = future.result()
        if result:
            gpu_hosts.append(result)
```

20 workers run in parallel. On a fast connection, scanning a few thousand hosts takes minutes, not hours.

### Phase 4 — Geocode and visualize

`geocode_cities.py` takes the CSV output and resolves each `city, country` pair to coordinates via the OpenStreetMap Nominatim API (rate-limited to 1 req/sec; a cache in `geocode_cache.json` prevents re-fetching). The result is `webapp/hosts_geo.json`, consumed by the Three.js globe in `webapp/index.html`.

---

## The Full Pipeline

```
Shodan API
    │
    ▼
ollama_gpu_scanner.py  ──▶  ollama_gpu_hosts.csv
                                      │
                                      ▼
                          geocode_cities.py  ──▶  geocode_cache.json
                                      │
                                      ▼
                              rebuild_json.py  ──▶  webapp/hosts_geo.json
                                                              │
                                                              ▼
                                                    webapp/index.html
                                                    (Three.js 3D Globe)
```

---

## How to Fix It

If you are running Ollama, check right now:

```bash
# Is Ollama listening on 0.0.0.0?
ss -tlnp | grep 11434
```

If you see `0.0.0.0:11434`, you are exposed. Fix it:

### Option 1 — Bind to localhost only (simplest)

```bash
# Default — only local access
OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

### Option 2 — Firewall the port

```bash
# UFW
sudo ufw deny 11434

# iptables
sudo iptables -A INPUT -p tcp --dport 11434 -j DROP
```

### Option 3 — Put a reverse proxy with auth in front

Use Nginx or Caddy with `auth_basic` or a bearer token check. Never expose the raw Ollama API.

### Option 4 — If you need remote access, use a VPN or SSH tunnel

```bash
# SSH tunnel — forward remote port to local
ssh -L 11434:localhost:11434 user@your-server
```

Then connect your client to `localhost:11434`. Zero exposure.

---

## Responsible Disclosure Note

The scanner collects only data that the hosts **voluntarily broadcast** to any TCP client. No model weights, user data, or credentials were accessed. The visualization does not display IP addresses in a way that facilitates targeted abuse. The goal is awareness, not exploitation.

If your IP appears on the map and you want it removed — secure the port. The moment Ollama stops answering on `0.0.0.0`, the host drops out of future scans.

---

## GitHub

The full source — scanner, geocoder, and 3D globe — is open source:

**[github.com/abderrazzakchabab/ollama_hosts_py](https://github.com/abderrazzakchabab/ollama_hosts_py)**

Pull requests welcome. The globe is live at **[ollama.chabab.online](https://ollama.chabab.online)**.

---

*If this post helped you lock down your Ollama instance, share it. The more people know about `OLLAMA_HOST=0.0.0.0`, the smaller this map gets.*
