#!/bin/sh
# Ingest every PDF under the CaseLinker repo into the DB via src/main.py
# (use after clearing Railway/Postgres or local SQLite).
#
# POSIX sh (macOS /bin/sh, Railway); no bash-4 mapfile.
#
# Usage (from repo root):
#   ./scripts/ingest_all_pdfs.sh
#   DATABASE_URL=... ./scripts/ingest_all_pdfs.sh   # Railway Postgres
#
set -e

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO_ROOT" || exit 1

if [ -d venv ]; then
  # shellcheck source=/dev/null
  . venv/bin/activate
fi

find_pdfs() {
  find "$REPO_ROOT" -type f -name "*.pdf" \
    -not -path "*/.git/*" \
    -not -path "*/venv/*" \
    -not -path "*/.venv/*" \
    -not -path "*/node_modules/*"
}

COUNT=$(find_pdfs | wc -l | tr -d ' ')
if [ "$COUNT" -eq 0 ]; then
  echo "No PDFs found under $REPO_ROOT" >&2
  exit 1
fi

echo "Found $COUNT PDF(s); running pipeline..." >&2
find_pdfs | sort | while IFS= read -r f; do
  echo "  - $f" >&2
done

find "$REPO_ROOT" -type f -name "*.pdf" \
  -not -path "*/.git/*" \
  -not -path "*/venv/*" \
  -not -path "*/.venv/*" \
  -not -path "*/node_modules/*" \
  -print0 | sort -z | xargs -0 python3 src/main.py
