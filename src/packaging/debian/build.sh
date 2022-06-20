#!/bin/bash

BASH="bash -x"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

lsb_release -c | grep stretch
if [ "$?" == "0" ]; then
	$BASH ./ffmpeg-xpra.sh
fi
if [ `arch` == "x86_64" ]; then
	$BASH ./libcuda1.sh
	$BASH ./libnvidia-fbc1.sh
fi
$BASH ./xpra-html5.sh
$BASH ./xpra.sh
