#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

KEY_FILE="E:\\xpra.pfx"

SIGNTOOL="${PROGRAMFILES}\\Microsoft SDKs\\Windows\\v7.1A\\Bin\\signtool"
if [ ! -e "${SIGNTOOL}" ]; then
	PROGRAMFILES_X86="C:\\Program Files (x86)"
	SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x64\\signtool"
	if [ ! -e "${SIGNTOOL}" ]; then
		SIGNTOOL="${PROGRAMFILES_X86}\\Windows Kits\\8.1\\Bin\\x86\\signtool"
	fi
fi
if [ ! -e "${SIGNTOOL}" ]; then
	echo "signtool.exe not found"
	exit 1
fi

SIGNTOOL_LOG="win32/signtool.log"
echo "SIGNTOOL=${SIGNTOOL}"
echo "SIGNTOOL=${SIGNTOOL}" > ${SIGNTOOL_LOG}
echo "Signing with $KEY_FILE, see ${SIGNTOOL_LOG} for output"
echo "Signing with $KEY_FILE" > ${SIGNTOOL_LOG}
for x in `ls *msi *exe`; do
	echo "* $x"
	echo "* $x" >> ${SIGNTOOL_LOG}
	cmd.exe //c "${SIGNTOOL}" sign //v //f "${KEY_FILE}" //t "http://timestamp.comodoca.com/authenticode" "$x" >> ${SIGNTOOL_LOG}
	err=$?
	if [ "$err" != "0" ]; then
		echo "error $err"
		tail -n 10 ${SIGNTOOL_LOG}
		echo
	fi
done
