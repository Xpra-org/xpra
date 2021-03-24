# ![Webcam](https://xpra.org/icons/webcam.png) Webcam

This feature allows client webcams attached to be exposed to the applications running on the server.

The webcam is not forwarded by default unless the webcam command line option enabled, or the webcam is activated manually from the system tray menu.


## Installation
Clients only rely on [opencv](http://opencv.org/) and its python bindings.

The server side is only supported on Linux. It relies on a virtual video device, you must install the [v4l2loopback](https://github.com/umlaeute/v4l2loopback) kernel module from and load it:
```shell
modprobe v4l2loopback devices=1 exclusive_caps=0
```
Some distributions may load the module with the wrong setting: `exclusive_caps=1` (ie: Ubuntu, see [#1596](https://github.com/Xpra-org/xpra/issues/1596))

The user running the xpra session must be able to access the video devices (ie: usually requires adding the user to the `video` group)


## Usage
The server should work out of the box provided that the kernel module is loaded.

You can enable the webcam from the client's system tray menu, or using the command line option `webcam=on`, you can also specify which video device to forward on the command line `--webcam=/dev/video2`.


## Limitations
* only supported with Linux servers
* work in progress, see [#1030](https://github.com/Xpra-org/xpra/issues/1030)
* framerate is low
* low resolution (hardcoded colorspace dependencies)
* no support for multiple sessions per server..
* limited detection of devices added or removed from the system
* excessive bandwidth usage
* server setup requires an out of tree kernel module
* MS Windows client builds have very unreliable support


## Debugging
<details>
  <summary>Diagnostics</summary>

* use the `-d webcam` [debug logging flag](../Usage/Logging.md)
* run `xpra webcam-info` on the server to locate the virtual video devices:
  ```shell
  Found 1 virtual video device:
  /dev/video1
  ```
* run `xpra webcam` on the client to run the webcam capture test application (aka `Webcam_Test` on MS Windows and MacOS).
</details>

<details>
  <summary>Issues</summary>

* [#1030](https://github.com/Xpra-org/xpra/issues/1030) original feature ticket
* [#1113](https://github.com/Xpra-org/xpra/issues/1113) improve webcam support
* [#1596](https://github.com/Xpra-org/xpra/issues/1596) Webcam is greyed out, even when v4l2loopback device is present
* [#1833](https://github.com/Xpra-org/xpra/issues/1833) API regression
</details>
