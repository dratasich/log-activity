#!/bin/sh

SCRIPT_PATH=$(dirname $(realpath $0))
cd "$SCRIPT_PATH"

# config
month=$(date '+%Y-%m')
result_path=/home/denise/repos/tar-writer/

echo "Run 'report.py -m ${month}_m365calendar.json'"
poetry run python report.py -m "${month}_m365calendar.json"

echo "Copy results to $result_path"
cp working_time.csv $result_path
cp activities.csv $result_path
