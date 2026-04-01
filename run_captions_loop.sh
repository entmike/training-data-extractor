#!/bin/bash
# Runs the captions step in a loop, restarting on failure

source .venv/bin/activate

while true; do
    echo "[$(date)] Starting captions step..."
    ltx2-build --config config.yaml --step captions
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] Captions step completed successfully. Exiting loop."
        break
    fi

    echo "[$(date)] Captions step exited with code $EXIT_CODE. Restarting in 5 seconds..."
    sleep 5
done
