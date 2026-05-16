#!/bin/sh
# Ingest every PDF under the CaseLinker repo into the DB via src/main.py
# (use after clearing Railway/Postgres or local SQLite).
#
# POSIX sh (macOS /bin/sh, Railway); no bash-4 mapfile.
#
# Usage (from repo root):
#   ./scripts/run/ingest_all_pdfs.sh
#   ./scripts/run/ingest_all_pdfs.sh --no-aggregate
#   DATABASE_URL=... ./scripts/run/ingest_all_pdfs.sh   # Railway Postgres
#
# --no-aggregate: skip aggregate federal reports so you can load state/ICAC PDFs
# first, then ingest NCMEC / DOJ separately. Skips when the PDF basename (case-
# insensitive) matches:
#   NCMEC / CyberTipline: *ncmec*, *cybertipline*, *cyber*tipline*
#   DOJ CEOS / Archives: *doj*ceos*, *doj*archiv*
#
set -e

NO_AGGREGATE=0
for arg in "$@"; do
  case "$arg" in
    --no-aggregate) NO_AGGREGATE=1 ;;
    -h | --help)
      cat <<'EOF' >&2
Usage: scripts/run/ingest_all_pdfs.sh [--no-aggregate]

  (default)       Ingest every PDF under the repo (including NCMEC / DOJ).
  --no-aggregate  Skip PDFs whose basename looks like NCMEC/CyberTipline or
                  DOJ CEOS/Archives (see header comment in this script).
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (use --help)" >&2
      exit 1
      ;;
  esac
done

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO_ROOT" || exit 1

if [ -d venv ]; then
  # shellcheck source=/dev/null
  . venv/bin/activate
fi

# Write one path per line (sorted) to stdout.
filtered_sorted_pdf_paths() {
  find "$REPO_ROOT" -type f -name "*.pdf" \
    -not -path "*/.git/*" \
    -not -path "*/venv/*" \
    -not -path "*/.venv/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/tmp/*" \
    -not -path "*/scrape_output/*" \
    2>/dev/null |
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      [ -f "$f" ] || continue
      if [ "$NO_AGGREGATE" -eq 1 ]; then
        bn=$(basename "$f" | tr '[:upper:]' '[:lower:]')
        case "$bn" in
          *ncmec* | *cybertipline* | *cyber*tipline*) continue ;;
          *doj*ceos* | *doj*archiv*) continue ;;
        esac
      fi
      printf '%s\n' "$f"
    done | sort
}

LIST=$(mktemp "${TMPDIR:-/tmp}/ingest_pdf_list.XXXXXX")
trap 'rm -f "$LIST"' EXIT

filtered_sorted_pdf_paths >"$LIST"

COUNT=$(wc -l <"$LIST" | tr -d '[:space:]')
if [ "$COUNT" -eq 0 ]; then
  if [ "$NO_AGGREGATE" -eq 1 ]; then
    echo "No PDFs left after --no-aggregate filter under $REPO_ROOT" >&2
  else
    echo "No PDFs found under $REPO_ROOT" >&2
  fi
  exit 1
fi

echo "Found $COUNT PDF(s); running pipeline..." >&2
while IFS= read -r f; do
  echo "  - $f" >&2
done <"$LIST"

# Avoid xargs-only pipelines (ARG_MAX-safe for typical ingest sizes; POSIX sh).
set --
while IFS= read -r f; do
  [ -n "$f" ] || continue
  set -- "$@" "$f"
done <"$LIST"
python3 src/main.py "$@"
