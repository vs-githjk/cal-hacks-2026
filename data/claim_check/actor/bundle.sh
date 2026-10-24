#!/bin/sh
# Copy the claim check and the fit tables it needs into src/ so this folder builds on its own (apify push).
set -e
cd "$(dirname "$0")"
rm -rf src/data && mkdir -p src/data/claim_check src/data/fit_checker
touch src/data/__init__.py
cp ../__init__.py src/data/claim_check/__init__.py
cp ../../fit_checker/tables.py src/data/fit_checker/tables.py
touch src/data/fit_checker/__init__.py
sed -i.bak 's/^from data\.fit_checker\.tables/from src.data.fit_checker.tables/' src/data/claim_check/__init__.py && rm src/data/claim_check/__init__.py.bak
