import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Configuration ---
VALID_API_TOKEN = "secure-token-123"

# Load Cluster Configuration to find the Trusted Host (Proxy)
# Gatekeeper must forward to Proxy's PRIVATE IP on the Proxy PORT (here: 80)
try:
    with open("cluster_info.json", "r") as f:
        cluster_data = json.load(f)
        TRUSTED_HOST_IP = cluster_data["proxy"]["private_ip"]
        # ✅ FIX: Proxy is running on port 80 (not 8080)
        TRUSTED_HOST_URL = f"http://{TRUSTED_HOST_IP}:8080/query"
except Exception as e:
    print(f"Error loading cluster config: {e}")
    TRUSTED_HOST_IP = None
    TRUSTED_HOST_URL = None


def is_authenticated(req):
    token = req.headers.get("x-api-key")
    return token == VALID_API_TOKEN


def is_query_safe(sql: str):
    sql_upper = sql.strip().upper()

    forbidden_patterns = [
        "DROP TABLE",
        "DROP DATABASE",
        "TRUNCATE TABLE",
        "DELETE FROM",
        "SHUTDOWN",
        "GRANT",
        "REVOKE",
    ]

    for pattern in forbidden_patterns:
        if pattern in sql_upper:
            return False, f"Security Alert: Query contains forbidden command '{pattern}'"

    return True, "Safe"


@app.route("/query", methods=["POST"])
def handle_request():
    # 1) Auth
    if not is_authenticated(request):
        return jsonify({"error": "Unauthorized. Invalid or missing 'x-api-key'."}), 401

    data = request.get_json(silent=True)
    if not data or "query" not in data:
        return jsonify({"error": "No query provided"}), 400

    sql_query = data["query"]
    strategy = data.get("strategy", "direct_hit")

    # 2) Safety
    safe, msg = is_query_safe(sql_query)
    if not safe:
        return jsonify({"error": "Request Blocked by Gatekeeper", "details": msg}), 403

    # 3) Forward to Proxy (Trusted Host)
    if not TRUSTED_HOST_URL:
        return jsonify({"error": "Trusted Host configuration missing"}), 500

    try:
        resp = requests.post(
            TRUSTED_HOST_URL,
            json={"query": sql_query, "strategy": strategy},
            timeout=10
        )

        # Return Proxy response to client
        return (resp.content, resp.status_code, resp.headers.items())

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to reach Trusted Host", "details": str(e)}), 502


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "Gatekeeper Operational",
        "trusted_host": TRUSTED_HOST_IP
    }), 200


if __name__ == "__main__":
    # ✅ Gatekeeper exposed publicly on port 8080
    app.run(host="0.0.0.0", port=8080)
