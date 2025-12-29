#!/bin/bash

set -e

echo "======================================================================"
echo "Launching AWS Infrastructure"
echo "======================================================================"

python scripts/instance_setup.py

echo "Infrastructure launched successfully. Waiting 30s for SSH services to stabilize..."
sleep 30

echo "======================================================================"
echo "Deploying MySQL Cluster"
echo "======================================================================"

echo "Deploying MySQL Manager..."
bash scripts/deploy_manager.sh

echo "Deploying MySQL Workers..."
bash scripts/deploy_worker.sh

echo "======================================================================"
echo "Benchmarking MySQL"
echo "======================================================================"

echo "Starting Mysql Benchmark "
bash scripts/benchmark_mysql.sh

echo "======================================================================"
echo "Deploying Cloud Patterns"
echo "======================================================================"

echo "Deploying Proxy Pattern..."
bash scripts/deploy_proxy.sh

echo "Deploying Gatekeeper Pattern..."
bash scripts/deploy_gatekeeper.sh

echo "======================================================================"
echo "Benchmarking"
echo "======================================================================"

echo "Waiting 10s for services to fully initialize..."
sleep 10

echo "Starting Benchmark..."
python scripts/benchmark.py

echo ""
echo "======================================================================"
echo "DEMO COMPLETE"
echo "======================================================================"
echo "To tear down resources, run: bash clean_demo.sh"