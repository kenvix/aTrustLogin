#!/bin/bash

export DISPLAY=":1"

while ! xset q >/dev/null 2>&1; do
    echo "Waiting for X11 to start..."
    sleep 3
done

while true; do
    python3 /opt/atrust-autologin/launcher.py
    status=$?
    case "$status" in
        0)
            echo "Autologin command completed successfully."
            break
            ;;
        2)
            echo "Autologin configuration is invalid. Check ATRUST_OPTS."
            exit 2
            ;;
        *)
            echo "Autologin exited with status $status. Retrying in 30 seconds."
            sleep 30
            ;;
    esac
done
