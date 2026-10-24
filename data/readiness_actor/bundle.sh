#!/bin/sh
# Copy the readiness check and what it imports into src/data so this folder builds on its own (Apify source files).
set -e
cd "$(dirname "$0")"
rm -rf src/data && mkdir -p src/data/claim_check src/data/fit_checker src/data/mirror
touch src/data/__init__.py src/data/mirror/__init__.py
cp ../readiness.py ../seller_report.py src/data/
cp ../claim_check/__init__.py ../claim_check/fetch.py ../claim_check/real_scan.py src/data/claim_check/
for f in __init__.py normalize.py tables.py depth.py power.py gpu_lengths.py depth_data.json gpu_lengths.json gpu_power.json; do
  cp "../fit_checker/$f" src/data/fit_checker/
done
cp ../mirror/normalize.py src/data/mirror/
echo "bundled src/data/: .actorignore makes apify push upload it although .gitignore skips it; check that the push lists src/data/readiness.py"
