SCRIPTS_DIR="scripts"
MANAGER_IP_FILE="$SCRIPTS_DIR/manager_ip.txt"
WORKER_IPS_FILE="$SCRIPTS_DIR/worker_ips.txt"
PEM_KEY="$SCRIPTS_DIR/log8415e-key.pem"

WORKER_IPS=$(tr -d '\r' < $WORKER_IPS_FILE)
MANAGER_IP=$(cat $MANAGER_IP_FILE)

ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$MANAGER_IP <<EOF
  echo "--> Preparing Sysbench..."
  sudo sysbench /usr/share/sysbench/oltp_read_only.lua \
    --mysql-db=sakila \
    --mysql-user=root \
    --mysql-password=root \
    prepare

  echo "--> Running Sysbench..."
  sudo sysbench /usr/share/sysbench/oltp_read_only.lua \
    --mysql-db=sakila \
    --mysql-user=root \
    --mysql-password=root \
    run > sysbench_results.txt

  echo "--> Sysbench Results:"
  cat sysbench_results.txt
EOF

for WORKER_IP in $WORKER_IPS; do
  echo "--------------------------------------------------"

  ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$WORKER_IP <<EOF
    echo "--> Preparing Sysbench..."
    sudo sysbench /usr/share/sysbench/oltp_read_only.lua \
        --mysql-db=sakila \
        --mysql-user=root \
        --mysql-password=root \
        prepare

    echo "--> Running Sysbench..."
    sudo sysbench /usr/share/sysbench/oltp_read_only.lua \
        --mysql-db=sakila \
        --mysql-user=root \
        --mysql-password=root \
        run > sysbench_results.txt

    echo "--> Sysbench Results:"
    cat sysbench_results.txt
EOF
done