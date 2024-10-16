#!/bin/bash

MSWINDOWS_DIR=`dirname $(readlink -f $0)`

for DO_FULL in 1 0; do
	echo "********************************************************************************"
	DO_FULL=${DO_FULL} ${MSWINDOWS_DIR}/BUILD.py
done
