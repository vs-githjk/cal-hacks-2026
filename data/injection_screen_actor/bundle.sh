#!/bin/sh
# Copy Bazaar Shield's rules (Lane D's shield/, unchanged: copied, never edited) into src/shield so this folder builds
# on its own (Apify source files). core.py imports classifier.py, so it is copied too; src/screen.py never turns it on.
set -e
cd "$(dirname "$0")"
rm -rf src/shield && mkdir -p src/shield/rules
cp ../../shield/__init__.py ../../shield/core.py ../../shield/classifier.py ../../shield/text.py src/shield/
cp ../../shield/rules/*.py src/shield/rules/
echo "bundled src/shield/: .actorignore makes apify push upload it although .gitignore skips it; check that the push lists src/shield/core.py"
