# ![MacOS](../images/icons/osx.png) Building MacOS Binaries

## Setup
Install [XCode](https://developer.apple.com/xcode/) and its command line tools.

<details>
  <summary>Setup gtk-osx</summary>

Download the latest version of the [gtk-osx](https://wiki.gnome.org/Projects/GTK/OSX/Building) setup script and run it:
```shell
git clone https://github.com/Xpra-org/gtk-osx-build
cd gtk-osx-build
sh gtk-osx-setup.sh
```
This will have installed `jhbuild` in `~/.new_local/bin`, so let's add this to our `$PATH`:
```shell
export PATH=$PATH:~/.new_local/bin/
```
</details>
<details>
  <summary>Configure `jhbuild` to use our modules</summary>

From the `gtk-osx-build` directory, run:
```shell
ln -sf "$(realpath .)/jhbuildrc-gtk-osx" ~/.config/jhbuildrc
ln -sf "$(realpath .)/jhbuildrc-custom" ~/.config/jhbuildrc-custom
```
</details>

Bootstrap:
```shell
jhbuild bootstrap-gtk-osx
```

Optional: install [pandoc](https://pandoc.org/installing.html#macos)

## Build all the libraries

First, make sure that all the modulesets will be using the same system libffi
as the one used by Python:
```commandline
cat > ${JHBUILD_PREFIX}/lib/pkgconfig/libffi.pc << EOF
Version: 3.4.6
Libs: -L${libdir} -lffi
Cflags: -I${includedir}
antoine@Mac-mini ~ % cat /Users/antoine/gtk/inst/lib/pkgconfig/libffi.pc
prefix=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr
libdir=${prefix}/lib
includedir=${prefix}/include/ffi

Name: libffi
Description: Library supporting Foreign Function Interfaces
Version: 3.4.6
Libs: -L${libdir} -lffi
Cflags: -I${includedir}
EOF
```
```shell
jhbuild update
jhbuild build
```

## Build and Package Xpra
```shell
git clone https://github.com/Xpra-org/xpra
cd xpra/packaging/MacOS/
sh ./make-app.sh
sh ./make-DMG.sh
sh ./make-PKG.sh
```
Signing the resulting `.app`, `DMG` and `PKG` images requires setting up certificates.
