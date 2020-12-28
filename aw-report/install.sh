#!/bin/sh

SCRIPT_PATH=$(dirname $(realpath $0))
INSTALL_PATH="/usr/local/bin"
CMD="$INSTALL_PATH/aw-report"

rm -f "$CMD"
ln -s "$SCRIPT_PATH"/run.sh "$CMD"
