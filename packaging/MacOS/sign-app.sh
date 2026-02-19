#!/bin/bash

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
APP_DIR="${MACOS_SCRIPT_DIR}/image/Xpra.app"
CONTENTS_DIR="${APP_DIR}/Contents"
X11_DIR="${CONTENTS_DIR}/Frameworks/X11"

export CODESIGN_KEYNAME="${CODESIGN_KEYNAME:=-}"

# for libraries and executables:
function sign_runtime() {
  codesign --remove-signature "$@"
  codesign --sign "${CODESIGN_KEYNAME}" --options runtime --timestamp "$@"
}

# for plain python modules:
function sign() {
  codesign --remove-signature "$@"
  codesign --sign "${CODESIGN_KEYNAME}" "$@"
}

export -f sign
export -f sign_runtime

echo "*******************************************************************************"
echo "Signing"
echo "  so"
find "${CONTENTS_DIR}/" -type f -name "*.so" -exec bash -c 'sign_runtime "$0"' {} \;
echo "  dylibs"
find "${CONTENTS_DIR}/" -type f -name "*.dylib" -exec bash -c 'sign_runtime "$0"' {} \;
echo "  pyc"
find "${CONTENTS_DIR}/" -type f -name "*.pyc" -exec bash -c 'sign "$0"' {} \;

if [ -d "${X11_DIR}/bin" ]; then
    sign_runtime "${X11_DIR}/bin/"*
fi
echo "  Frameworks/bin"
sign_runtime "${CONTENTS_DIR}/Frameworks/bin/"*
echo "  Helpers"
sign_runtime "${CONTENTS_DIR}/Helpers/"*
echo "  MacOS/Xpra"
sign_runtime "${CONTENTS_DIR}/MacOS/Xpra"
echo "  Xpra_NoDock.app"
sign_runtime "${CONTENTS_DIR}/Xpra_NoDock.app"
echo "  Xpra.app"
sign_runtime "${APP_DIR}"

echo "Verification"
echo "  extended attributes (should be empty)"
xattr -l "${APP_DIR}"
# Verify just the bundle seal, then deep verification (checks all components)
echo "  signature"
codesign --verify --verbose=1 "${APP_DIR}" && codesign --verify --deep --strict --verbose=1 "${APP_DIR}"
echo "  gatekeeper"
spctl --status
spctl --assess -vvv --type execute "${APP_DIR}"

echo "*******************************************************************************"
echo "Copying Xpra.app to ~/Desktop"
ditto "${APP_DIR}" "${HOME}/Desktop/Xpra.app"
