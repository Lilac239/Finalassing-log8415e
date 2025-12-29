#!/bin/bash

# Directory setups
SCRIPTS_DIR="scripts"
MANAGER_IP_FILE="$SCRIPTS_DIR/manager_ip.txt"
PEM_KEY="$SCRIPTS_DIR/log8415e-key.pem"

MANAGER_IP=$(cat $MANAGER_IP_FILE)

echo "--------------------------------------------------"
echo "Configuring Manager (Source) at $MANAGER_IP"
echo "--------------------------------------------------"

ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$MANAGER_IP <<EOF
  set -e
  
  # 1. Install MySQL & Sysbench
  sudo apt-get update -y
  sudo apt-get install mysql-server sysbench -y
  
  # 2. Stop MySQL to configure
  sudo systemctl stop mysql

  # 3. Configure mysqld.cnf the mysql server configuration file
  CONFIG_FILE="/etc/mysql/mysql.conf.d/mysqld.cnf"
  # add the source server ip
  PRIVATE_IP=\$(hostname -I | awk '{print \$1}')
  sudo sed -i "s/^bind-address.*/bind-address = \$PRIVATE_IP/" \$CONFIG_FILE
  
  # Idempotent config appending
  if ! grep -q "server-id = 1" \$CONFIG_FILE; then
      echo "" | sudo tee -a \$CONFIG_FILE
      echo "server-id = 1" | sudo tee -a \$CONFIG_FILE
      echo "log_bin = /var/log/mysql/mysql-bin.log" | sudo tee -a \$CONFIG_FILE
      echo "binlog_do_db = sakila" | sudo tee -a \$CONFIG_FILE
  fi

  # 4. Restart MySQL
  sudo systemctl start mysql
  sudo systemctl enable mysql

  # 5. User Setup (FIXED for Idempotency)
  # Setup Local Root
  sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root'; FLUSH PRIVILEGES;"
  
  # Setup Remote Root (for Proxy) - Uses IF NOT EXISTS
  sudo mysql -u root -proot -e "CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED WITH mysql_native_password BY 'root';"
  sudo mysql -u root -proot -e "ALTER USER 'root'@'%' IDENTIFIED WITH mysql_native_password BY 'root';"
  sudo mysql -u root -proot -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%'; FLUSH PRIVILEGES;"

  # Setup Replica User - Uses IF NOT EXISTS
  sudo mysql -u root -proot -e "CREATE USER IF NOT EXISTS 'replica_user'@'%' IDENTIFIED WITH mysql_native_password BY 'password';"
  sudo mysql -u root -proot -e "ALTER USER 'replica_user'@'%' IDENTIFIED WITH mysql_native_password BY 'password';"
  sudo mysql -u root -proot -e "GRANT REPLICATION SLAVE ON *.* TO 'replica_user'@'%'; FLUSH PRIVILEGES;"

  # Install Sakila
  cd ~
  if [ ! -d "sakila-db" ]; then
      wget https://downloads.mysql.com/docs/sakila-db.tar.gz
      tar -xzvf sakila-db.tar.gz
  fi
  # Only import if tables don't exist (simple check) to save time, or just overwrite
  sudo mysql -u root -proot -e "SOURCE sakila-db/sakila-schema.sql;"
  sudo mysql -u root -proot -e "SOURCE sakila-db/sakila-data.sql;"

  # 6. Get Master Status
  sudo mysql -u root -proot -e "SHOW MASTER STATUS\G" > master_status.txt
EOF

# Retrieve the status and private IP locally
echo "Retrieving Master Log coordinates..."
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$MANAGER_IP "cat master_status.txt" > temp_status.txt

# Extract File and Position
LOG_FILE=$(grep "File:" temp_status.txt | awk '{print $2}')
LOG_POS=$(grep "Position:" temp_status.txt | awk '{print $2}')

# Retrieve Manager Private IP for the Workers
ssh -o StrictHostKeyChecking=no -i $PEM_KEY ubuntu@$MANAGER_IP "hostname -I | awk '{print \$1}'" > $SCRIPTS_DIR/manager_private_ip.txt
MANAGER_PRIVATE_IP=$(cat $SCRIPTS_DIR/manager_private_ip.txt)

if [ -z "$LOG_FILE" ] || [ -z "$LOG_POS" ]; then
    echo "Error: Could not retrieve replication coordinates."
    exit 1
fi

# Save info for the workers
echo "$LOG_FILE" > $SCRIPTS_DIR/master_log_file.txt
echo "$LOG_POS" > $SCRIPTS_DIR/master_log_pos.txt

echo "Manager Configured."
echo "   Private IP: $MANAGER_PRIVATE_IP"
echo "   Log File:   $LOG_FILE"
echo "   Log Pos:    $LOG_POS"