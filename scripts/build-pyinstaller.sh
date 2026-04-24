#!/bin/bash
# scripts/build-pyinstaller.sh
# Baut eine portable .exe/.App mit PyInstaller
#
# Nutzung:
#   ./scripts/build-pyinstaller.sh [version]
#   Beispiel: ./scripts/build-pyinstaller.sh 1.0.0

set -e

VERSION="${1:-1.0.0}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="${PROJECT_DIR}/dist"
RELEASE_DIR="${DIST_DIR}/BTCRechnung"

echo "=== BTCRechnung PyInstaller Build v${VERSION} ==="
echo ""

# Aufräumen
rm -rf "${DIST_DIR}/BTCRechnung" "${DIST_DIR}/BTCRechnung.zip"

echo "Starte PyInstaller..."
cd "${PROJECT_DIR}"
"${PROJECT_DIR}/.venv/bin/pyinstaller" BTCRechnung.spec --clean --noconfirm 2>&1 | tail -5

echo ""
echo "Erstelle data-Ordner..."
mkdir -p "${RELEASE_DIR}/data"
touch "${RELEASE_DIR}/data/.gitkeep"

echo "Erstelle ZIP..."
cd "${DIST_DIR}"
zip -r "BTCRechnung-${VERSION}.zip" "BTCRechnung/" -x "*/__pycache__/*" -x "*/.DS_Store"

SIZE=$(du -h "${DIST_DIR}/BTCRechnung-${VERSION}.zip" | cut -f1)
echo ""
echo "=== Fertig ==="
echo "Datei: ${DIST_DIR}/BTCRechnung-${VERSION}.zip"
echo "Größe: ${SIZE}"
echo ""
echo "Zum Testen:"
echo "  cd ${RELEASE_DIR}"
echo "  ./BTCRechnung"
