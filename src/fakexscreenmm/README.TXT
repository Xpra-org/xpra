	= libfakeXscreenmm =


1) What it is
This library can be used to override the default X11
library calls DisplayWidthMM and DisplayHeightMM
to expose customized screen physical dimensions.

It is inspired by fakexinerama, and uses the same technique.


2) Configuration file
This library tries to load its configuration from the file:
	~/.$DISPLAY-fakexscreenmm

The file follows a simple but strict format:
* use "#" at the beginning of a line for comments
* the first line that is not a comment MUST contain the number of screens defined in the file
* the number of screens MUST be a valid positive number between 1 and 10
* each of the following lines that are not comments MUST define each of the screen
* all screens MUST be defined
* each screen MUST consist of two numeric values separated by a single space: xmm ymm
  this defines the size of the display in millimeters


3) Example Configuration File:
# 2 screens:
2
# Laptop Main screen "LVDS1":
283 212
# External LCD screen "HDMI1":
677 423


4) Building it
gcc -O2 -Wall fakeXscreenmm.c -fPIC -o libfakeXscreenmm.so.1.0 -shared


5) Using it
LD_PRELOAD=/path/to/libfakeXscreenmm.so.1.0 yourapplication
