	= libfakeXinerama =


1) What it is
This fake library can be used to override the default libXinerama
library and expose customized screen dimensions.


2) Origins
This code is based on fakexinerama,
which used to live here:
http://home.kde.org/~seli/fakexinerama
but this link is now dead.

I found another copy here:
https://github.com/asafge/xrdp_dualmon/tree/master/fakexinerama


3) Modifications
This version is modified to allow multiple displays for the same user.
Instead of looking for its configuration in the file:
	~/.fakexinerama
It will first attempt to load its configuration from the file:
	~/.$DISPLAY-fakexinerama

We also rename it to prevent overwriting or conflicting with
the real libXinerama shared library.

As with the rest of the X11 code, it used the MIT license.


4) Configuration file
The .fakexinerama configuration file follows a simple but strict format:
* use "#" at the beginning of a line for comments
* the first line that is not a comment MUST contain the number of screens defined in the file,
* the number of screens MUST be a valid positive number between 1 and 10
* each of the following lines that are not comments MUST define each of the screen
* all screens MUST be defined
* each screen MUST consist of four numeric values separated by a single space: x y w h
  this defines the area of the display that belongs to the given screen


5) Example Configuration File:
# 2 screens:
2
# Laptop Main screen "LVDS1":
0 0 1366 768
# External LCD screen "HDMI1":
1366 0 1920 1080


6) Building it
gcc -O2 -Wall fakeXinerama.c -fPIC -o libfakeXinerama.so.1.0 -shared


7) Using it
LD_PRELOAD=/path/to/libfakeXinerama.so.1.0 yourapplication
