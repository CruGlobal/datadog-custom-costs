#!/bin/bash
set -e

# Extract Python version from .tool-versions
PYTHON_VERSION=$(grep '^python' .tool-versions | awk '{print $2}')

if [ -z "$PYTHON_VERSION" ]; then
  echo "Error: Could not find Python version in .tool-versions"
  exit 1
fi

echo "Building with Python version: $PYTHON_VERSION"

# Build Docker image with the extracted Python version
docker buildx build \
  --build-arg PYTHON_VERSION="$PYTHON_VERSION" \
  $DOCKER_ARGS \
  .
