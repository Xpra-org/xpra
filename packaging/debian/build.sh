#!/bin/bash

BASH="bash -x"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

$BASH ./libcuda1.sh
$BASH ./libnvidia-fbc1.sh
$BASH ./xpra.sh
