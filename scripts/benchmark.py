# benchmark.py
import os
import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import matplotlib.pyplot as plt
import numpy as np


# =========================
# Configuration (à ajuster)
# =========================

# 1) Fichier cluster_info.json (généré par boto_up.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLUSTER_CONFIG = os.path.join(SCRIPT_DIR, "cluster_info.json")

# 2) Token API (doit matcher gatekeeper.py)
API_TOKEN = "secure-token-123"

# 3) Port Gatekeeper
# - None => auto (essaie 80 puis 8080)
# - sinon mets 8080 (souvent) ou 80
FORCE_GATEKEEPER_PORT = None  # ex: 8080

# 4) Charge benchmark (commence petit, puis augmente)
REQUEST_COUNT = 1000
CONCURRENCY = 10

# 5) Requêtes SQL
READ_QUERY = "SELECT * FROM actor LIMIT 1;"
WRITE_QUERY = "INSERT INTO actor (first_name, last_name) VALUES ('TEST', 'BENCHMARK');"

# Stratégies testées (doivent matcher ton gatekeeper/proxy)
STRATEGIES = ["direct_hit", "random", "customized"]

# Headers
HEADERS = {"x-api-key": API_TOKEN, "Content-Type": "application/json"}


# =========================
# Helpers
# =========================

def load_cluster_info() -> dict:
    if not os.path.exists(CLUSTER_CONFIG):
        raise FileNotFoundError(
            f"{CLUSTER_CONFIG} not found.\n"
            f"Run boto_up.py first and make sure cluster_info.json is created in the same folder as benchmark.py."
        )
    with open(CLUSTER_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def build_gatekeeper_base_url(public_ip: str, port: int) -> str:
    return f"http://{public_ip}:{port}"


def sanity_check(base_url: str, timeout: int = 5) -> tuple[bool, str]:
    """
    Vérifie rapidement si le service répond sur /query (même si 401/403, c'est OK => le serveur est up).
    """
    url = base_url + "/query"
    payload = {"query": "SELECT 1;", "strategy": "direct_hit"}
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=timeout)
        # Si le serveur répond (200/4xx), on considère que le port est bon.
        return True, f"Server responded with HTTP {r.status_code}"
    except requests.exceptions.ConnectionError as e:
        return False, f"ConnectionError: {e}"
    except requests.exceptions.ConnectTimeout as e:
        return False, f"ConnectTimeout: {e}"
    except Exception as e:
        return False, f"Other error: {e}"


def resolve_gatekeeper_url() -> str:
    data = load_cluster_info()
    public_ip = data.get("gatekeeper", {}).get("public_ip")
    if not public_ip:
        raise RuntimeError("cluster_info.json missing gatekeeper.public_ip")

    ports_to_try = []
    if FORCE_GATEKEEPER_PORT is not None:
        ports_to_try = [FORCE_GATEKEEPER_PORT]
    else:
        ports_to_try = [80, 8080]

    last_msg = None
    for p in ports_to_try:
        base = build_gatekeeper_base_url(public_ip, p)
        ok, msg = sanity_check(base, timeout=5)
        last_msg = f"{base} -> {msg}"
        if ok:
            print(f"[OK] Gatekeeper reachable: {base} ({msg})")
            return base + "/query"

    raise RuntimeError(
        "Gatekeeper not reachable on tried ports.\n"
        f"Tried: {ports_to_try}\n"
        f"Last check: {last_msg}\n"
        "Fix: verify gatekeeper service is running and SG allows inbound on the correct port."
    )


GATEKEEPER_URL = resolve_gatekeeper_url()


def send_request(query: str, strategy: str) -> tuple[bool, float, str]:
    payload = {"query": query, "strategy": strategy}

    start_time = time.time()
    try:
        r = requests.post(GATEKEEPER_URL, json=payload, headers=HEADERS, timeout=10)
        latency_ms = (time.time() - start_time) * 1000

        if r.status_code == 200:
            return True, latency_ms, "OK"
        else:
            # On garde l'info d'erreur mais on n'explose pas
            return False, latency_ms, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, 0.0, str(e)


def run_benchmark(strategy: str, op_name: str, query: str) -> dict:
    print(f"--> Starting {op_name} test for strategy: '{strategy}'")
    latencies = []
    success = 0
    fail = 0
    first_failure = None

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(send_request, query, strategy) for _ in range(REQUEST_COUNT)]

        for i, fut in enumerate(as_completed(futures), start=1):
            ok, latency, msg = fut.result()
            if ok:
                success += 1
                latencies.append(latency)
            else:
                fail += 1
                if first_failure is None:
                    first_failure = msg

            if i % 100 == 0 or i == REQUEST_COUNT:
                print(f"    Processed {i}/{REQUEST_COUNT} requests...", end="\r")

    print("\n    Done.")
    if first_failure:
        print(f"    [First Failure]: {first_failure}")

    avg = statistics.mean(latencies) if latencies else 0.0
    mn = min(latencies) if latencies else 0.0
    mx = max(latencies) if latencies else 0.0
    success_rate = (success / REQUEST_COUNT) * 100.0

    print(f"    Results for {strategy} - {op_name}:")
    print(f"      Success: {success}/{REQUEST_COUNT}")
    print(f"      Failed:  {fail}/{REQUEST_COUNT}")
    print(f"      Avg Latency: {avg:.2f} ms")
    print(f"      Min Latency: {mn:.2f} ms")
    print(f"      Max Latency: {mx:.2f} ms")
    print("-" * 50)

    return {
        "strategy": strategy,
        "type": op_name,
        "avg_ms": avg,
        "min_ms": mn,
        "max_ms": mx,
        "success_rate": success_rate,
        "success_count": success,
        "failure_count": fail,
    }


def save_results(results: list[dict]) -> str:
    out = os.path.join(SCRIPT_DIR, "benchmark_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return out


def generate_graph(results: list[dict]) -> str:
    strategies_labels = ["Direct hit", "Random", "Customized"]
    strategies_keys = ["direct_hit", "random", "customized"]

    writes = []
    reads = []

    for key in strategies_keys:
        w = next((r["avg_ms"] for r in results if r["strategy"] == key and r["type"] == "WRITE"), 0)
        r = next((r["avg_ms"] for r in results if r["strategy"] == key and r["type"] == "READ"), 0)
        writes.append(w)
        reads.append(r)

    x = np.arange(len(strategies_labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 6))
    rects1 = ax.bar(x - width / 2, writes, width, label="Write")
    rects2 = ax.bar(x + width / 2, reads, width, label="Read")

    def add_labels(rects):
        for rect in rects:
            h = rect.get_height()
            ax.annotate(
                f"{h:.1f}",
                xy=(rect.get_x() + rect.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )

    add_labels(rects1)
    add_labels(rects2)

    ax.set_ylabel("Average Latency (ms)")
    ax.set_title("Benchmark Results")
    ax.set_xticks(x)
    ax.set_xticklabels(strategies_labels)
    ax.legend()

    out = os.path.join(SCRIPT_DIR, "benchmark_results.png")
    plt.savefig(out, bbox_inches="tight")
    print(f"Graph saved to {out}")
    return out


def main():
    print("==================================================")
    print(f"Targeting Gatekeeper at: {GATEKEEPER_URL}")
    print(f"Total Requests per test: {REQUEST_COUNT}")
    print(f"Concurrency: {CONCURRENCY}")
    print("==================================================\n")

    # Protection : si gatekeeper down, on s'arrête ici (resolve_gatekeeper_url a déjà check)
    results = []

    for strategy in STRATEGIES:
        res_w = run_benchmark(strategy, "WRITE", WRITE_QUERY)
        results.append(res_w)
        time.sleep(2)

        res_r = run_benchmark(strategy, "READ", READ_QUERY)
        results.append(res_r)
        time.sleep(2)

    print("\n\n================ FINAL SUMMARY ================")
    print(f"{'Strategy':<15} | {'Type':<10} | {'Success %':<10} | {'Avg Latency (ms)':<15}")
    print("-" * 60)
    for r in results:
        print(f"{r['strategy']:<15} | {r['type']:<10} | {r['success_rate']:<10.1f} | {r['avg_ms']:<15.2f}")
    print("================================================")

    json_path = save_results(results)
    print(f"Results saved to {json_path}")

    generate_graph(results)


if __name__ == "__main__":
    main()
