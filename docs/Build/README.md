# Building Xpra

## Platform specific instructions:
Please refer to the instructions most appropriate for your build platform:
* [Fedora, CentOS / RHEL](./RPM.md)
* [Debian and Ubuntu](./Debian.md)
* [MS Windows](./MSWindows.md)
* [MacOS](./MacOS.md)
* [Others](./Other.md)


## Download the xpra source code
Use one of the following locations:
* `github`: https://github.com/Xpra-org/xpra and https://github.com/Xpra-org/xpra-html5
* `pypi`: https://pypi.org/project/xpra/ (releases only)
* `xpra.org`: https://xpra.org/src/ (releases only)

## Build
First, make sure that all the required [dependencies](./Dependencies.md) are installed, then:
```shell
git clone https://github.com/Xpra-org/xpra
cd xpra
python3 ./setup.py install --prefix=/usr
```

## Caveats
* **Do not** mix source installation with binary packages. Remove one completely before installing the other
* Current versions of xpra require python3, for python2 use the 3.x LTS branch - see [versions](https://github.com/Xpra-org/xpra/wiki/Versions)
