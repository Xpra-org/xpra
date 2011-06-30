#!/bin/bash

rm -fr xpra
mkdir xpra
rsync -rCplogt ./src/* xpra
rsync -rCplogt ./debian xpra/
cd xpra
debuild -us -uc -b
