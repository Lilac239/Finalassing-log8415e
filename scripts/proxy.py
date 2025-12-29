import json
import random
import subprocess
import time
from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

# --- Configuration ---
DB_USER = "root"
DB_PASS = "root"
DB_NAME = "sakila"

# Load Cluster Configuration
# We expect cluster_info.json to be SCP'd to the server alongside this script
try:
    with open("cluster_info.json", "r") as f:
        cluster_data = json.load(f)
        # Use Private IPs because Proxy acts as Trusted Host inside the VPC
        MANAGER_NODE = cluster_data['manager']['private_ip']
        WORKER_NODES = [w['private_ip'] for w in cluster_data['workers']]
except FileNotFoundError:
    print("Error: cluster_info.json not found. Please ensure it is deployed.")
    MANAGER_NODE = None
    WORKER_NODES = []

# --- Helper Functions ---

def get_db_connection(host):
    """Establishes a connection to a specific MySQL node."""
    try:
        connection = mysql.connector.connect(
            host=host,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            auth_plugin='mysql_native_password',
            connect_timeout=2
        )
        return connection
    except Error as e:
        print(f"Error connecting to {host}: {e}")
        return None

def get_ping_time(host):
    """Pings a host and returns the average latency in ms."""
    try:
        # Run ping command (count=1, timeout=1s)
        # Using system ping to measure network latency as requested for 'Customized' strategy
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '1', host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            # Extract time=X.X ms from output
            output = result.stdout
            if "time=" in output:
                time_ms = float(output.split("time=")[1].split(" ")[0])
                return time_ms
    except Exception as e:
        print(f"Ping error for {host}: {e}")
    return float('inf') # Return infinity if unreachable

def determine_query_type(sql):
    """
    Analyzes SQL to determine if it is a READ or WRITE operation.
    Proxy decides whether a request is a READ or a WRITE.
    """
    sql_upper = sql.strip().upper()
    if sql_upper.startswith("SELECT"):
        return "READ"
    return "WRITE"

# --- Strategy Implementations ---

def strategy_direct_hit():
    """
    Direct Hit: Forward all requests to the Manager node.
    Directly forward incoming requests to MySQL master node.
    """
    return MANAGER_NODE

def strategy_random():
    """
    Random: Randomly select a worker node.
    Randomly select a worker and send the request to it.
    """
    if not WORKER_NODES:
        return MANAGER_NODE
    return random.choice(WORKER_NODES)

def strategy_customized():
    """
    Customized: Measure ping time of all workers and forward to the fastest.
    Measure ping time of all workers and forward to one with lower response time.
    """
    if not WORKER_NODES:
        return MANAGER_NODE
    
    best_node = None
    lowest_latency = float('inf')

    for node in WORKER_NODES:
        latency = get_ping_time(node)
        if latency < lowest_latency:
            lowest_latency = latency
            best_node = node
            
    return best_node if best_node else MANAGER_NODE

# --- Main Request Handler ---

@app.route('/query', methods=['POST'])
def handle_query():
    """
    Entry point for the Proxy.
    Expects JSON: { "query": "SELECT...", "strategy": "random" }
    """
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"error": "No query provided"}), 400

    sql_query = data['query']
    strategy_type = data.get('strategy', 'direct_hit').lower()
    
    # 1. Determine Query Type (READ vs WRITE)
    query_type = determine_query_type(sql_query)
    
    target_node = None

    # 2. Route based on Type and Strategy
    # All WRITE operations must be sent to the manager.
    if query_type == "WRITE":
        target_node = MANAGER_NODE
    else:
        # All READ operations are sent to the workers.
        # Proxy determines type... needs to decide where to send it.
        if strategy_type == "direct_hit":
            target_node = strategy_direct_hit()
        elif strategy_type == "random":
            target_node = strategy_random()
        elif strategy_type == "customized":
            target_node = strategy_customized()
        else:
            # Fallback
            target_node = strategy_direct_hit()

    # 3. Execute Query
    if not target_node:
        return jsonify({"error": "No available node found"}), 503

    conn = get_db_connection(target_node)
    if not conn:
        return jsonify({"error": f"Failed to connect to node {target_node}"}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql_query)
        
        result = None
        if query_type == "READ":
            result = cursor.fetchall()
        else:
            conn.commit()
            result = {"affected_rows": cursor.rowcount}
            
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "success",
            "executed_on": target_node,
            "strategy_used": strategy_type,
            "query_type": query_type,
            "data": result
        })

    except Error as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Proxy is running", "manager": MANAGER_NODE, "workers": WORKER_NODES}), 200

if __name__ == '__main__':
    # Run on port 8080 or 5000
    app.run(host='0.0.0.0', port=8080)
