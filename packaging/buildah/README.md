# Container Builds with [buildah](https://buildah.io/)

## Setup the build containers
```
./setup_build_containers.sh
```

## Run the build
```
./build_all.sh
```

The resulting `RPM` and `DEB` packages are found in the `./repo` directory.


## Options
You may want to specify which distributions you want to setup:
```
RPM_DISTROS="Fedora:34" ./setup_build_containers.sh
DISTROS="Fedora:34" ./build_all.sh
```

For more details, refer to the (ugly) scripts themselves.
