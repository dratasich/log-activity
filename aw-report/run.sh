#!/bin/sh

SCRIPT_PATH=$(dirname $(realpath $0))

cd "$SCRIPT_PATH"
poetry run ./report.py -c issue
