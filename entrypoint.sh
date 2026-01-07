#!/bin/sh
set -e

# Job router - runs different scripts based on JOB environment variable
# Usage: Set JOB=GITHUB or JOB=NEON in ECS task definition

case "$JOB" in
  GITHUB)
    echo "Starting GitHub cost data collection..."
    exec python github_costs.py "$@"
    ;;
  NEON)
    echo "Starting Neon cost data collection..."
    exec python neon_costs.py "$@"
    ;;
  *)
    echo "Error: JOB environment variable must be set to GITHUB or NEON"
    echo "Current value: ${JOB:-<not set>}"
    exit 1
    ;;
esac
