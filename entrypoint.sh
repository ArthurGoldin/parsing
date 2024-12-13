#!/bin/bash

# Automatically resolve stale lock files and assign an available display
export DISPLAY=:99
for i in $(seq 99 110); do
    if [ ! -f /tmp/.X${i}-lock ]; then
        export DISPLAY=:$i
        break
    fi
done

# Clean up any stale lock file
if [ -f /tmp/.X${DISPLAY#:}-lock ]; then
    echo "Removing stale lock file: /tmp/.X${DISPLAY#:}-lock"
    rm -f /tmp/.X${DISPLAY#:}-lock
fi

# Start Xvfb
echo "Starting Xvfb on $DISPLAY..."
Xvfb $DISPLAY -screen 0 1280x1024x16 -nolisten tcp -auth /dev/null &
XVFB_PID=$!

# Ensure Xvfb starts correctly
if ! pidof Xvfb > /dev/null; then
    echo "Error: Failed to start Xvfb"
    exit 1
fi

# Wait for Xvfb to initialize
sleep 2

# Log DISPLAY
echo "Using DISPLAY: $DISPLAY"

# Handle termination signals to clean up
trap "echo 'Stopping Xvfb...'; kill $XVFB_PID; exit 0" SIGTERM SIGINT

# Execute the main command
echo "Executing: $@"
exec "$@"
