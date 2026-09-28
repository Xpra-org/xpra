#!/bin/bash

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
LIGHT="${LIGHT:=0}"
if [ "${LIGHT}" == "1" ]; then
  APP_NAME="Xpra-Light"
else
  APP_NAME="Xpra"
fi

APP_DIR="${MACOS_SCRIPT_DIR}/image/${APP_NAME}.app"
ZIP="${MACOS_SCRIPT_DIR}/image/${APP_NAME}.zip"

ditto -c -k --keepParent "${APP_DIR}" "${ZIP}"    # notarytool only accepts a zip, dmg or pkg
xcrun notarytool submit "${ZIP}" --keychain-profile xpra-notary --wait
xcrun stapler staple "${APP_DIR}"
spctl --assess -vvv --type execute "${APP_DIR}"
