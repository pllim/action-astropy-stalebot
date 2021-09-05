#!/bin/bash -l

PYTHON=$(which python3.8)
echo "PYTHON=${PYTHON}"

$PYTHON /stale_pull_requests.py

sleep 1m  # Wait 1 minute

$PYTHON /stale_issues.py
