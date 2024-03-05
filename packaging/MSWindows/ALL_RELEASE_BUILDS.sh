#!/bin/bash

DO_INSTALLER=${DO_INSTALLER:-1}
RUN_INSTALLER=${RUN_INSTALLER:-0}
DO_ZIP=${DO_ZIP:-1}
DO_MSI=${DO_MSI:-1}

MSWINDOWS_DIR=`dirname $(readlink -f $0)`

for DO_FULL in 1 0; do
	echo "********************************************************************************"
	DO_FULL=${DO_FULL} DO_ZIP=${DO_ZIP} DO_INSTALLER=${DO_INSTALLER} RUN_INSTALLER=${RUN_INSTALLER} DO_MSI=${DO_MSI} PYTHON=python3 sh ${MSWINDOWS_DIR}/MINGW_BUILD.sh /silent
done
