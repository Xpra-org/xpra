#!/bin/bash

# verify that each .deb / .ddeb is a complete archive before it is published,
# a failing 'tar' (ie: under qemu-user emulation) can leave dpkg-deb output
# with only the control member and no data member

if [ "$#" == "0" ]; then
	echo "verify-debs: no packages to verify" >&2
	exit 1
fi

FAILED=0
for deb in "$@"; do
	if ! dpkg-deb --info "$deb" > /dev/null || ! dpkg-deb --fsys-tarfile "$deb" > /dev/null; then
		echo "verify-debs: invalid package: $deb" >&2
		FAILED=1
	fi
done
exit $FAILED
