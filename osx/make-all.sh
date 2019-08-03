#!/bin/sh

if [ -z "${CODESIGN_KEYNAME}" ]; then
	export CODESIGN_KEYNAME="Antoine Martin"
fi

./make-app.sh && ./sign-app.sh && ./make-DMG.sh && ./make-PKG.sh
