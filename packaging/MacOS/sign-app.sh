#!/bin/bash

APP_DIR="./image/Xpra.app"
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
fi

if [ ! -z "${CODESIGN_KEYNAME}" ]; then
		echo "Signing with key '${CODESIGN_KEYNAME}'"
        codesign --deep --force --verify --verbose --sign "Developer ID Application: ${CODESIGN_KEYNAME}" ${APP_DIR}
else
		echo "Signing skipped (no keyname)"
fi
