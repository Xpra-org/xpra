Most xpra features can be configured from the command line or through xpra's configuration files.

You can find some example configuration files here: [sample /etc/xpra/ directory](https://xpra.org/conf/)

The configuration files use the exact same format as the command line options, which is documented in the [manual page](https://xpra.org/manual.html), just without the `--` prefix.\
The manual is also shipped with all binary installations and should be easily accessible. (ie: `man xpra`)

_(some more obscure features can be configured using environmentent variables)_


## Configuration Files Location

The exact location of the configuration files varies widely from platform to platform, and even from one version of the OS to another.
* for unix-like operating systems, the system configuration files can usually be found in `/etc/xpra` and the per-user settings can be placed in `~/.config/xpra` - you can also run the `xpra/platform/path.py` script for more details
* on Mac OS X, we ship a command line tool found under `Xpra.app/Contents/Helpers/Path_info` which will show you the file locations, the default location for user configuration files should be `~/Library/Application Support/Xpra` you can also use - `
~/.config/xpra`, although this is deprecated
* on MS Windows, you can run the `Path_info.exe` tool found in the Xpra installation folder


----

You should generally not edit the system default configuration files, as those may be overwritten whenever xpra is (re)installed.
Use the per-user configuration files instead, or add your own configuration file.
