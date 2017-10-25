#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

KEY_FILE="E:\\xpra.pfx"

SIGNTOOL="${PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool"
if [ ! -e "${SIGNTOOL}" ]; then
	SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool"
fi

SIGNTOOL_LOG="win32/signtool.log"
echo "Signing with $KEY_FILE"
echo "Signing with $KEY_FILE" > ${SIGNTOOL_LOG}
for x in `ls *msi *exe`; do
	echo "* $x"
	echo "* $x" >> ${SIGNTOOL_LOG}
	cmd.exe //c "${SIGNTOOL}" sign //v //f "${KEY_FILE}" //t "http://timestamp.comodoca.com/authenticode" "$x" >> ${SIGNTOOL_LOG}
	if [ $? != "0" ]; then
		echo "error $?"
		tail -n 10 ${SIGNTOOL_LOG}
		echo
	fi
done
