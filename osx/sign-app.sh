#!/bin/bash

IMAGE_DIR="./image/Xpra.app"

if [ ! -z "${CODESIGN_KEYNAME}" ]; then
		echo "Signing with key '${CODESIGN_KEYNAME}'"
        codesign --deep --force --verify --verbose --sign "Developer ID Application: ${CODESIGN_KEYNAME}" ${IMAGE_DIR}
else
		echo "Signing skipped (no keyname)"
fi
