#!/bin/zsh

# Check if a ticker argument was provided.
if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <ticker> <date> <time>"
  exit 1
fi

ticker=$1
dat=$2
tim=$3

# Run the command with the provided ticker and the fixed parameters.
poetry run python ticksonic-databento.py "$ticker" 10000 100000 "$dat" "$tim"
