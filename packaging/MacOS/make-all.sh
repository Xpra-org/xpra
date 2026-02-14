#!/bin/bash

if [ -z "${CODESIGN_KEYNAME}" ]; then
	export CODESIGN_KEYNAME="xpra.org"
fi

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "${MACOS_SCRIPT_DIR}" || exit 1

./make-app.sh && ./make-DMG.sh && ./make-PKG.sh
