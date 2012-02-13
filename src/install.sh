#!/bin/sh

set -e
rm -rf build install
python make_constants_pxi.py wimpiggy/lowlevel/constants.txt wimpiggy/lowlevel/constants.pxi
CFLAGS=-O0 python setup.py install
