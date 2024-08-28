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

```shell
ln -sf $(pwd)/gtk-osx-build/jhbuildrc-gtk-osx ~/.config/jhbuildrc
ln -sf $(pwd)/gtk-osx-build/jhbuildrc-custom ~/.config/jhbuildrc-custom
```
</details>

Bootstrap:
```shell
jhbuild update
jhbuild bootstrap-gtk-osx
```

Optional: install [pandoc](https://pandoc.org/installing.html#macos)

## Build all the libraries
```shell
jhbuild build
#some python libraries have to be installed via pip in a jhbuild shell:
jhbuild shell
pip3 install --prefix $JHBUILD_PREFIX bcrypt
pip3 install --prefix $JHBUILD_PREFIX packaging
pip3 install --prefix $JHBUILD_PREFIX parsing
pip3 install --prefix $JHBUILD_PREFIX typing_extensions
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
