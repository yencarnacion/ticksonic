#!/bin/zsh

# Check if a ticker argument was provided.
if [ -z "$1" ]; then
  echo "Usage: $0 <ticker>"
  exit 1
fi

ticker=$1

# Run the command with the provided ticker and the fixed parameters.
poetry run python ticksonic.py "$ticker" 6000 60000
