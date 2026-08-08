# Building RPMs


<div class="docs-section-heading" markdown="1">

## Repositories

</div>
You must enable the following repositories to be able to install all the build dependencies:

| Distributions     | Dependency                                         | Installation                                         | Notes                                                  |
|-------------------|----------------------------------------------------|------------------------------------------------------|--------------------------------------------------------|
| RHEL and clones   | [EPEL](https://docs.fedoraproject.org/en-US/epel/) | `dnf install epel-release`                           | use `epel-next-release` on CentOS stream               |
| RHEL and clones   | `Power Tools`                                      | `dnf config-manager --set-enabled powertools`        | also known as `PowerTools` on some variants / versions |
| RHEL 9 and clones | `CRB`                                              | `dnf config-manager --set-enabled crb`               |
| All               | [rpmfusion](https://rpmfusion.org/)                | [configuration](https://rpmfusion.org/Configuration) |

<div class="docs-section-heading" markdown="1">

## Install Build Requirements

</div>
The spec file can be found here:
https://github.com/Xpra-org/xpra/tree/master/packaging/rpm/xpra.spec

```shell
dnf builddep xpra.spec
```
You may also refer to the more generic list of [dependencies](Dependencies.md)

Alternatively, if you want to install a more limited set of build dependencies,
you can use the `dev-env` build subcommand which will honour setup arguments. ie:
```shell
./setup.py dev-env --minimal --with-openh264
```
_(available in xpra v6.1 onwards)_


<div class="docs-section-heading" markdown="1">

## Build

</div>
```shell
python3 ./setup.py install
```

<div class="docs-section-heading" markdown="1">

## ![RPM](../images/icons/rpm.png)

</div>
The quick and easy way:
```shell
mkdir -p ~/rpmbuild/SOURCES/ >& /dev/null
git clone https://github.com/Xpra-org/xpra
cd xpra
python3 ./setup.py sdist --formats=xz
cp dist/*xz patches/* ~/rpmbuild/SOURCES/
rpmbuild -ba ./packaging/rpm/xpra.spec
ls -s ~/rpmbuild/RPMS/*/
```
This builds fresh packages from git master. \
You can also use other branches, tags or download a [source release](https://xpra.org/src/) instead.
