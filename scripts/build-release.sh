#!/bin/bash
# build-release.sh
# Erstellt ein Release-ZIP für BTCRechnung
#
# Nutzung:
#   ./scripts/build-release.sh [version]
#   Beispiel: ./scripts/build-release.sh 1.0.0

set -e

VERSION="${1:-1.0.0}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${PROJECT_DIR}/build"
RELEASE_NAME="btcrechnung-${VERSION}"
RELEASE_DIR="${BUILD_DIR}/${RELEASE_NAME}"
ZIP_FILE="${BUILD_DIR}/${RELEASE_NAME}.zip"

echo "=== BTCRechnung Release Build v${VERSION} ==="
echo ""

# Aufräumen
rm -rf "${BUILD_DIR}"
mkdir -p "${RELEASE_DIR}"

echo "Kopiere Dateien..."

# App-Code
cp -r "${PROJECT_DIR}/app" "${RELEASE_DIR}/app"

# Start-Skripte (aus release-files/)
cp "${PROJECT_DIR}/release-files/start.sh" "${RELEASE_DIR}/start.sh"
cp "${PROJECT_DIR}/release-files/start.bat" "${RELEASE_DIR}/start.bat"
chmod +x "${RELEASE_DIR}/start.sh"

# README
cp "${PROJECT_DIR}/release-files/README.md" "${RELEASE_DIR}/README.md"

# Requirements
cp "${PROJECT_DIR}/requirements.txt" "${RELEASE_DIR}/requirements.txt"

# Docs
mkdir -p "${RELEASE_DIR}/docs"
cp "${PROJECT_DIR}/docs/wallet-setup.md" "${RELEASE_DIR}/docs/wallet-setup.md"

# Lizenz
cp "${PROJECT_DIR}/LICENSE" "${RELEASE_DIR}/LICENSE"

# Leerer data-Ordner
mkdir -p "${RELEASE_DIR}/data"
touch "${RELEASE_DIR}/data/.gitkeep"

# Statik-Dateien
cp -r "${PROJECT_DIR}/app/static" "${RELEASE_DIR}/app/static" 2>/dev/null || true

# Benutzer-Assets entfernen (falls vorhanden)
rm -f "${RELEASE_DIR}/cert.pem"
rm -f "${RELEASE_DIR}/key.pem"

# Aufräumen in der Kopie
find "${RELEASE_DIR}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${RELEASE_DIR}" -name "*.pyc" -delete 2>/dev/null || true
rm -rf "${RELEASE_DIR}/app/static/sw.js" 2>/dev/null || true

echo "Erstelle ZIP..."
cd "${BUILD_DIR}"
zip -r "${ZIP_FILE}" "${RELEASE_NAME}/" -x "*/__pycache__/*" "*/.DS_Store"

SIZE=$(du -h "${ZIP_FILE}" | cut -f1)
echo ""
echo "=== Fertig ==="
echo "Datei: ${ZIP_FILE}"
echo "Größe: ${SIZE}"
echo ""
echo "Zum Testen:"
echo "  cd ${BUILD_DIR}"
echo "  unzip ${RELEASE_NAME}.zip"
echo "  cd ${RELEASE_NAME}"
echo "  ./start.sh"
