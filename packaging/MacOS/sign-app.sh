#!/bin/bash

APP_DIR="./image/Xpra.app"
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
fi

if [ ! -z "${CODESIGN_KEYNAME}" ]; then
		echo "Signing with key '${CODESIGN_KEYNAME}'"
		# verify that it is unlocked:
		if [ -z "${KEYCHAIN}" ]; then
			KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
			echo "using default login keychain ${KEYCHAIN}"
		fi
		if ! security show-keychain-info "$KEYCHAIN" 2>/dev/null; then
			echo "Keychain is locked, cannot sign!"
			exit 1
		fi
		codesign --deep --force --verify --verbose --sign "${CODESIGN_KEYNAME}" ${APP_DIR}
else
		echo "Signing skipped (no keyname)"
fi
