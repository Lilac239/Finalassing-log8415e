#!/bin/bash
set -euo pipefail

SCRIPTS_DIR="scripts"
WORKER_IPS_FILE="$SCRIPTS_DIR/worker_ips.txt"

# ✅ Mets ici le vrai nom de ta clé (selon ton projet)
PEM_KEY="$SCRIPTS_DIR/log8415e-key.pem"

# --- Replication variables (produits par deploy_manager.sh) ---
MANAGER_PRIVATE_IP="$(tr -d '\r\n' < "$SCRIPTS_DIR/manager_private_ip.txt")"
LOG_FILE="$(tr -d '\r\n' < "$SCRIPTS_DIR/master_log_file.txt")"
LOG_POS="$(tr -d '\r\n' < "$SCRIPTS_DIR/master_log_pos.txt")"

echo "Setting up Replication."
echo "Source: $MANAGER_PRIVATE_IP | File: $LOG_FILE | Pos: $LOG_POS"

# Remove CRs from the worker_ips file (Windows -> Linux)
WORKER_IPS="$(tr -d '\r' < "$WORKER_IPS_FILE")"

SERVER_ID_COUNTER=2

for WORKER_IP in $WORKER_IPS; do
  WORKER_IP="$(echo "$WORKER_IP" | tr -d '\r\n')"
  [ -z "$WORKER_IP" ] && continue

  echo "--------------------------------------------------"
  echo "Configuring Worker (Replica) at $WORKER_IP"
  echo "--------------------------------------------------"

  ssh -o StrictHostKeyChecking=no -i "$PEM_KEY" "ubuntu@$WORKER_IP" bash -s <<EOF
set -euo pipefail

# 1) Install dependencies
sudo apt-get update -y
sudo apt-get install -y mysql-server mysql-client sysbench wget tar

# 2) Configure MySQL (bind to private IP + server-id + relay log)
CONFIG_FILE="/etc/mysql/mysql.conf.d/mysqld.cnf"
PRIVATE_IP=\$(hostname -I | awk '{print \$1}')

# Ensure bind-address matches private IP
if grep -q "^bind-address" "\$CONFIG_FILE"; then
  sudo sed -i "s/^bind-address.*/bind-address = \$PRIVATE_IP/" "\$CONFIG_FILE"
else
  echo "bind-address = \$PRIVATE_IP" | sudo tee -a "\$CONFIG_FILE" >/dev/null
fi

# Ensure replication settings exist (idempotent)
if ! grep -q "^server-id" "\$CONFIG_FILE"; then
  echo "" | sudo tee -a "\$CONFIG_FILE" >/dev/null
  echo "server-id = $SERVER_ID_COUNTER" | sudo tee -a "\$CONFIG_FILE" >/dev/null
fi

if ! grep -q "^relay-log" "\$CONFIG_FILE"; then
  echo "relay-log = /var/log/mysql/mysql-relay-bin.log" | sudo tee -a "\$CONFIG_FILE" >/dev/null
fi

# On worker we do NOT need binlog_do_db (only master needs it), but ok if present.
# We'll avoid forcing binlog on worker.

# 3) Restart MySQL
sudo systemctl restart mysql
sudo systemctl enable mysql

# 4) Ensure root password + remote root for proxy
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root'; FLUSH PRIVILEGES;" || true

sudo mysql -u root -proot -e "CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED WITH mysql_native_password BY 'root';" || true
sudo mysql -u root -proot -e "ALTER USER 'root'@'%' IDENTIFIED WITH mysql_native_password BY 'root';" || true
sudo mysql -u root -proot -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION; FLUSH PRIVILEGES;" || true

# 5) Load Sakila (idempotent)
cd ~
if [ ! -d "sakila-db" ]; then
  wget -q https://downloads.mysql.com/docs/sakila-db.tar.gz
  tar -xzf sakila-db.tar.gz
fi

# Create DB if not exists
mysql -u root -proot -e "CREATE DATABASE IF NOT EXISTS sakila;" || true

# Load schema/data only if tables not present
TABLE_COUNT=\$(mysql -u root -proot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='sakila';" 2>/dev/null || echo "0")
if [ "\$TABLE_COUNT" = "0" ]; then
  mysql -u root -proot sakila < sakila-db/sakila-schema.sql
  mysql -u root -proot sakila < sakila-db/sakila-data.sql
fi

# 6) Configure replication (THIS is the part that was broken in your output)
# Make sure replica_user exists on master (done in deploy_manager.sh)
mysql -u root -proot -e "STOP REPLICA;" || true

mysql -u root -proot -e "CHANGE REPLICATION SOURCE TO \
  SOURCE_HOST='$MANAGER_PRIVATE_IP', \
  SOURCE_USER='replica_user', \
  SOURCE_PASSWORD='password', \
  SOURCE_LOG_FILE='$LOG_FILE', \
  SOURCE_LOG_POS=$LOG_POS;"

mysql -u root -proot -e "START REPLICA;"

echo "--> Replication Status:"
mysql -u root -proot -e "SHOW REPLICA STATUS\G" | egrep "Replica_IO_Running|Replica_SQL_Running|Last_IO_Error|Last_SQL_Error|Source_Host|Source_Log_File|Read_Source_Log_Pos" || true
EOF

  SERVER_ID_COUNTER=$((SERVER_ID_COUNTER + 1))
done

echo "All Workers Configured."
