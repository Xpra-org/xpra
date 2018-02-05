#!/bin/bash

DO_INSTALLER=${DO_INSTALLER:-1}
RUN_INSTALLER=${RUN_INSTALLER:-0}
DO_ZIP=${DO_ZIP:-1}
DO_MSI=${DO_MSI:-1}

for PYTHON in python2 python3; do
	for CLIENT_ONLY in 0 1; do
		echo "********************************************************************************"
		CLIENT_ONLY=${CLIENT_ONLY} DO_ZIP=${DO_ZIP} DO_INSTALLER=${DO_INSTALLER} RUN_INSTALLER=${RUN_INSTALLER} DO_MSI=${DO_MSI} PYTHON=$PYTHON sh win32/MINGW_BUILD.sh /silent
	done
done
