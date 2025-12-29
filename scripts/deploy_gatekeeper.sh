#!/bin/bash

# Directory and File Setups
SCRIPTS_DIR="scripts"
PEM_KEY="$SCRIPTS_DIR/log8415e-key.pem" #log8415e-key
CLUSTER_JSON="$SCRIPTS_DIR/cluster_info.json"
GATEKEEPER_IP_FILE="$SCRIPTS_DIR/gatekeeper_ip.txt"
GATEKEEPER_FILE="$SCRIPTS_DIR/gatekeeper.py"

# 2. Extract Gatekeeper Public IP
echo "Extracting Gatekeeper IP..."
GATEKEEPER_IP=$(cat $GATEKEEPER_IP_FILE)

echo "Deploying Gatekeeper to: $GATEKEEPER_IP"

# 3. Prepare Remote Directory & Copy Files
echo "--> Creating remote directory..."
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$GATEKEEPER_IP "mkdir -p /home/ubuntu/gatekeeper"

echo "--> Copying files (gatekeeper.py and cluster_info.json)..."
# The Gatekeeper needs cluster_info.json to find the Proxy's Private IP
scp -o StrictHostKeyChecking=no -i $PEM_KEY $GATEKEEPER_FILE $CLUSTER_JSON ubuntu@$GATEKEEPER_IP:/home/ubuntu/gatekeeper/

# 4. Install Dependencies and Run
echo "--> Installing dependencies and starting Gatekeeper..."
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$GATEKEEPER_IP <<EOF
  set -e
  
  # Update and install Python
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv

  cd /home/ubuntu/gatekeeper

  # Create Virtual Env
  python3 -m venv venv
  source venv/bin/activate

  # Install Python Libraries
  # Flask for the API, requests to forward calls to the Proxy
  pip install --upgrade pip
  pip install flask requests

  # Stop any existing instance
  sudo pkill -f "python3 gatekeeper.py" || true

  # Run Gatekeeper in background on Port 8080
  echo "Starting Gatekeeper..."
  sudo nohup ./venv/bin/python3 gatekeeper.py > gatekeeper.log 2>&1 &
  
  sleep 2
  
  # Verify it's running
  if pgrep -f "gatekeeper.py" > /dev/null; then
      echo "Gatekeeper is running!"
  else
      echo "Gatekeeper failed to start. Check gatekeeper.log"
      cat gatekeeper.log
  fi
EOF

echo "--------------------------------------------------"
echo "Gatekeeper Deployment Complete."
echo "Public Endpoint: http://$GATEKEEPER_IP"
echo "--------------------------------------------------"