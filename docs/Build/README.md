# Platform specific instructions:
Please refer to the instructions most appropriate for your build platform:
* [Fedora, CentOS / RHEL](./RPM.md)
* [Debian and Ubuntu](./Debian.md)
* [MS Windows](./MSWindows.md)
* [MacOS](./MacOS.md)
* [Others](./Other.md)

# Overview
Before attempting to build from source, make sure that all the required [dependencies](./Dependencies.md) are installed.

The platform specific documentation above usually also includes the commands required for installing the build time dependencies.


# Download the xpra source code
Use one of the following locations:
* `github`: https://github.com/Xpra-org/xpra and https://github.com/Xpra-org/xpra-html5
* `pypi`: https://pypi.org/project/xpra/ (releases only)
* `xpra.org`: https://xpra.org/src/ (releases only)

# Build
```shell
python3 ./setup.py install
```

# Caveats
* **Do not** mix source installation with binary packages. Remove one completely before installing the other
* Current versions of xpra require python3, for python2 use the 3.x LTS branch - see [versions](https://github.com/Xpra-org/xpra/wiki/Versions)
