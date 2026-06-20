#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELECTRON_APP="${ROOT_DIR}/node_modules/electron/dist/Electron.app"
APP_NAME="Dante Multimodal Dashboard"
APP_DIR="/Applications/${APP_NAME}.app"
APP_RESOURCES="${APP_DIR}/Contents/Resources"
APP_PAYLOAD="${APP_RESOURCES}/app"
ICON_FILE="DanteMultimodalDashboard.icns"

if [[ ! -d "${ELECTRON_APP}" ]]; then
  echo "Electron runtime not found; attempting Electron postinstall."
  node "${ROOT_DIR}/node_modules/electron/install.js"
fi

if [[ ! -d "${ELECTRON_APP}" ]]; then
  echo "Electron runtime not found: ${ELECTRON_APP}" >&2
  echo "Run: pnpm install && node node_modules/electron/install.js" >&2
  exit 1
fi

if [[ -d "${APP_DIR}" ]]; then
  BACKUP="${APP_DIR}.backup-$(date +%Y%m%d-%H%M%S)"
  mv "${APP_DIR}" "${BACKUP}"
  echo "Backed up existing app to: ${BACKUP}"
fi

cp -R "${ELECTRON_APP}" "${APP_DIR}"
rm -rf "${APP_PAYLOAD}"
mkdir -p "${APP_PAYLOAD}" "${APP_PAYLOAD}/assets"

cp "${ROOT_DIR}/electron/main.cjs" "${APP_PAYLOAD}/main.cjs"
cp "${ROOT_DIR}/electron/preload.cjs" "${APP_PAYLOAD}/preload.cjs"
cp "${ROOT_DIR}/electron/assets/${ICON_FILE}" "${APP_PAYLOAD}/assets/${ICON_FILE}"
cp "${ROOT_DIR}/electron/assets/${ICON_FILE}" "${APP_RESOURCES}/${ICON_FILE}"

cat > "${APP_PAYLOAD}/package.json" <<JSON
{
  "name": "dante-multimodal-dashboard",
  "version": "1.0.0",
  "private": true,
  "main": "main.cjs"
}
JSON

/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName ${APP_NAME}" "${APP_DIR}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName ${APP_NAME}" "${APP_DIR}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.vidigal.dante-multimodal-dashboard" "${APP_DIR}/Contents/Info.plist"
if /usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" "${APP_DIR}/Contents/Info.plist" >/dev/null 2>&1; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile ${ICON_FILE}" "${APP_DIR}/Contents/Info.plist"
else
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string ${ICON_FILE}" "${APP_DIR}/Contents/Info.plist"
fi

plutil -lint "${APP_DIR}/Contents/Info.plist" >/dev/null
xattr -dr com.apple.quarantine "${APP_DIR}" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "${APP_DIR}" 2>/dev/null || true

echo "Built ${APP_DIR}"
