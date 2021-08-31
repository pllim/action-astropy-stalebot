#!/bin/bash -l

PYTHON=$(which python3.8)
echo "PYTHON=${PYTHON}"

$PYTHON /stale_pull_requests.py
$PYTHON /stale_issues.py
