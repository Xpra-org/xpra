#!/bin/bash

BASH="bash -x"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

if [ `arch` == "x86_64" ]; then
	$BASH ./libcuda1.sh
	$BASH ./libnvidia-fbc1.sh
fi
$BASH ./xserver-xorg-video-dummy.sh
$BASH ./xpra.sh
