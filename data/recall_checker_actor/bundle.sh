#!/bin/sh
# Copy the recall check into src/data so this folder builds on its own (Apify source files).
set -e
cd "$(dirname "$0")"
rm -rf src/data && mkdir -p src/data
touch src/data/__init__.py
cp ../recalls.py ../recall_checker.py src/data/
