# Xpra Configuration

The most common configuration options are available directly from the main GUI tool.\
Simply run `xpra` and click on the `Configure` button, or run the subcommand: `xpra configure`.

***

Most other important xpra settings can be configured from the command line or through xpra's configuration files.

You can find some example configuration files here: [sample /etc/xpra/ directory](https://xpra.org/conf/)

The configuration files use the exact same format as the command line options, which can be shown using `xpra --help`, just without the `--` prefix.\
The manual is also shipped with all binary installations and should be easily accessible. (ie: `man xpra`)

_(some more obscure features can be configured using environment variables)_

***

Starting with version 6.3, settings can be changed permanently from the command line:
```shell
xpra set dpi 120
```
To erase this setting:
```shell
xpra unset dpi
```

***

### Configuration Files Location

The exact location of the configuration files varies widely from platform to platform, and even from one version of the OS to another.
* for unix-like operating systems, the system configuration files can usually be found in `/etc/xpra` and the per-user settings can be placed in `~/.config/xpra` - you can also run the `xpra/platform/paths.py` script for more details
* on Mac OS X, we ship a command line tool found under `Xpra.app/Contents/Helpers/Path_info` which will show the file locations, the default location for user configuration files should be `~/Library/Application Support/Xpra` you can also use - `
~/.config/xpra`
* on MS Windows, run the `Path_info.exe` tool found in the Xpra installation folder


----

You should generally not edit the system default configuration files, as those may be overwritten whenever xpra is (re)installed.
Use the per-user configuration files instead, or add your own configuration file.
