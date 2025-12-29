#!/bin/bash

# Directory and File Setups
SCRIPTS_DIR="scripts"
PEM_KEY="$SCRIPTS_DIR/log8415e-key.pem"
CLUSTER_JSON="$SCRIPTS_DIR/cluster_info.json"
PROXY_IP_FILE="$SCRIPTS_DIR/proxy_ip.txt"
PROXY_FILE="$SCRIPTS_DIR/proxy.py"

PROXY_IP=$(cat $PROXY_IP_FILE)

echo "Deploying Proxy to: $PROXY_IP"

# 3. Prepare Remote Directory & Copy Files
echo "--> Creating remote directory..."
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$PROXY_IP "mkdir -p /home/ubuntu/proxy"

echo "--> Copying files (proxy.py and cluster_info.json)..."
# The proxy needs cluster_info.json to know the Private IPs of the Manager and Workers
scp -o StrictHostKeyChecking=no -i $PEM_KEY $PROXY_FILE $CLUSTER_JSON ubuntu@$PROXY_IP:/home/ubuntu/proxy/

# 4. Install Dependencies and Run
echo "--> Installing dependencies and starting Proxy..."
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$PROXY_IP <<EOF
  set -e
  
  # Update and install Python + Ping (Required for 'Customized' strategy)
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv iputils-ping

  cd /home/ubuntu/proxy

  # Create Virtual Env
  python3 -m venv venv
  source venv/bin/activate

  # Install Python Libraries
  # Flask for the API, mysql-connector-python for DB connections
  pip install --upgrade pip
  pip install flask mysql-connector-python requests

  # Stop any existing instance of the proxy (if redeploying)
  sudo pkill -f "python3 proxy.py" || true

  # Run Proxy in background
  # Using sudo because it binds to port 80
  echo "Starting Proxy on Port 80..."
  sudo nohup ./venv/bin/python3 proxy.py > proxy.log 2>&1 &
  
  sleep 2
  
  # Verify it's running
  if pgrep -f "proxy.py" > /dev/null; then
      echo "Proxy is running!"
  else
      echo "Proxy failed to start. Check proxy.log"
      cat proxy.log
  fi
EOF

echo "--------------------------------------------------"
echo "Proxy Deployment Complete."
echo "URL: http://$PROXY_IP"
echo "--------------------------------------------------"