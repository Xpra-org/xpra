# ![MS Windows](../images/icons/windows.png) Building MS Windows Binaries

## Setup
* install [MSYS2](https://www.msys2.org/) and update the system: run `pacman -Syu` until all the updates are applied
* from a MinGW shell, run this setup script: [SETUP.sh](https://github.com/Xpra-org/xpra/tree/master/packaging/MSWindows/SETUP.sh)


## Optional dependencies
* install [TortoiseSVN](https://tortoisesvn.net/) to support [SSH](../Network/SSH.md) via PuTTY plink - if the default backend is not sufficient
* to build [NVENC](../Usage/NVENC.md) or NVFBC support, install [CUDA](https://developer.nvidia.com/cuda-downloads) and [visualstudio](https://visualstudio.microsoft.com/) or [visualstudio express](https://visualstudio.microsoft.com/vs/express/)

To be able to generate EXE packages, install [verpatch](https://github.com/pavel-a/ddverpatch) and [InnoSetup](http://www.jrsoftware.org/isinfo.php).


## Build
From the source directory, just run the build script [BUILD.py](https://github.com/Xpra-org/xpra/tree/master/packaging/MSWindows/BUILD.py)
