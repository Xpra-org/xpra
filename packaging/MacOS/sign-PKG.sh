#!/bin/bash

set -e

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
LIGHT="${LIGHT:=0}"
if [ "${LIGHT}" == "1" ]; then
  APP_NAME="Xpra-Light"
else
  APP_NAME="Xpra"
fi

export CODESIGN_KEYNAME="${CODESIGN_KEYNAME:=Developer ID Installer}"
NOTARY_PROFILE="${NOTARY_PROFILE:=xpra-notary}"
# verify that it is unlocked:
if [ -z "${KEYCHAIN}" ]; then
  KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
  echo "using default login keychain ${KEYCHAIN}"
fi
if ! security show-keychain-info "$KEYCHAIN" 2>/dev/null; then
    echo "Keychain is locked, cannot sign!"
    exit 1
fi

PKG=$(echo "${MACOS_SCRIPT_DIR}/image/${APP_NAME}"*.pkg)

productsign --timestamp --sign "$CODESIGN_KEYNAME" "${PKG}" image/signed.pkg
mv image/signed.pkg "${PKG}"
pkgutil --check-signature "${PKG}"

xcrun notarytool submit "${PKG}" --keychain-profile "${NOTARY_PROFILE}" --wait
xcrun stapler staple "${PKG}"
spctl --assess -vvv --type install "${PKG}"

# replace the unsigned copy made by make-PKG.sh:
ditto "${PKG}" "${HOME}/Desktop/"
