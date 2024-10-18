#!/bin/bash

MSWINDOWS_DIR=`dirname $(readlink -f $0)`

${MSWINDOWS_DIR}/BUILD.py --full
${MSWINDOWS_DIR}/BUILD.py --no-full
