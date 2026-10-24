#!/bin/sh
# Copy the fit checker and its maker data into src/ so this folder builds on its own (Apify source files).
set -e
cd "$(dirname "$0")"
rm -rf src/data && mkdir -p src/data/fit_checker
touch src/data/__init__.py
for f in __init__.py normalize.py tables.py depth.py power.py build_check.py depth_data.json gpu_lengths.json gpu_power.json; do
  cp "../$f" src/data/fit_checker/
done
