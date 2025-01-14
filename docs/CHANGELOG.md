# Changelog

## [6.2.3] 2025-01-14
* Platforms, build and packaging:
    * [pillow 11.1.0](https://github.com/Xpra-org/xpra/commit/e6891f9dffa6f6ab8cd2b78418870350a3d0d3f8)
    * [`exe` installer standalone step](https://github.com/Xpra-org/xpra/commit/05ff96bfe332d5086ca1348984cee670e33cb18f)
    * [handle diverging RHEL clone packaging behaviour](https://github.com/Xpra-org/xpra/commit/cbcaa56c822e56a609406358e85114c32dc23568)
    * [move default package list for newer build script default](https://github.com/Xpra-org/xpra/commit/81a84f72bb2cdd500284cfb52f2fef16600819c2)
    * [invalid refresh rate detected on some MS Windows configurations](https://github.com/Xpra-org/xpra/commit/b9f1226888e296801313079edccf0315bd6156f0)
    * [normalize smooth scroll wheel values on macos](https://github.com/Xpra-org/xpra/commit/63d114716dce01beabcf7a49783f72404a7b3ca7)
* RHEL 10 builds:
    * [package Qt6 client](https://github.com/Xpra-org/xpra/commit/dd9043eebc3a7c697baa1e25bcce3d27fcedaa72)
    * [use `weston` + `Xwayland` as xvfb on RHEL 10](https://github.com/Xpra-org/xpra/commit/31f5ad2348e37c298996c7779956c8eb31e5a677)
    * [provide wrapper script for `weston` + `Xwayland`](https://github.com/Xpra-org/xpra/commit/98f8f7011dfdaed45b36ba50acc8f0b9ac8e8cd8)
    * [replace `noopenh264` with `openh264`](https://github.com/Xpra-org/xpra/commit/788456259fb3deae8b8361f814fd811dc35ab383)
    * [`AlmaLinux` `10-kitten` package list](https://github.com/Xpra-org/xpra/commit/c9a9e2c7834f5a9e746d6c57224aa17488ac2f55)
    * [`CentOS` `stream10` package list](https://github.com/Xpra-org/xpra/commit/745f3e8745277ad333b07776bc87c17e96be2ec2)
* Major:
    * [Network Manager API errors in some environments](https://github.com/Xpra-org/xpra/commit/ad855baecd62fc204c69508b59e0cfe908a0d634)
    * [websocket connection loss with some proxies sending empty payloads](https://github.com/Xpra-org/xpra/commit/9c4a12e6a9b4639de9bc348623e20760e39a8814)
    * [handle broken `pyopengl-accelerate` installations more gracefully](https://github.com/Xpra-org/xpra/commit/3d45e2986bb8fc962eaea4fea0e2b88ec2b9ee95)
    * [keyboard layout group regression](https://github.com/Xpra-org/xpra/commit/0e7dfbfd3b806fa723002d364238b1fdbeef1514)
* Encodings:
    * [batch delay increase compounded](https://github.com/Xpra-org/xpra/commit/6363c98caaaa5cb45769afdacb02e1eaf6530c64)
    * [avoid damage storms: switch to full frames earlier](https://github.com/Xpra-org/xpra/commit/eaf614d9976401da7352c99ffd341a07476baef0)
* Clipboard:
    * [always claim the clipboard selection when updated](https://github.com/Xpra-org/xpra/commit/8b1fd56e7e5e0198f2aed0d89b329bd7c9bcbcf6)
    * [always update the peer when the owner changes](https://github.com/Xpra-org/xpra/commit/e7e5f68ac6a2c89bcdf560b4d8ea02856f04cd12)
    * [remote clipboard option not honoured on some platorms](https://github.com/Xpra-org/xpra/commit/188a218edd1f719a81c64f038f48efa017ba49f7)
    * [allow all clipboards by default](https://github.com/Xpra-org/xpra/commit/c1bc57569eef7fa59796b9849c86d5e39b2e07bf)
* Desktop mode:
    * [better compatibility with some window managers when resizing](https://github.com/Xpra-org/xpra/commit/bcfdec08695ae86d2e1cd96a385ed1b264057940)
    * [handle fixed size desktops correctly](https://github.com/Xpra-org/xpra/commit/2a1854e3f2267c2bacce76bf0fe6d1900cf8e93a)
* Minor:
    * [toolbox examples do not run on some platforms](https://github.com/Xpra-org/xpra/commit/6bacd61ebc505a4de9d92f8cc166b466a390950a)
    * [`configure` tool incorrectly saves some options](https://github.com/Xpra-org/xpra/commit/d0959a3c2295b9b3f7fe8e6d0e963b1d8ffae1cf), [refresh-delay](https://github.com/Xpra-org/xpra/commit/ede996657aebd3acf9e4e9eeae8c08f6181edebd)
    * [hide 'configure shadow server' on light builds](https://github.com/Xpra-org/xpra/commit/7de653ee886aa9c5bab1eecb22ec481ee1db5f49)
    * [typo in `nvjpeg` encoder / decoder build switches](https://github.com/Xpra-org/xpra/commit/8f88a0659ae05fd7469160e4706d1924d6297cc3)
    * [`libexec` scripts installed twice](https://github.com/Xpra-org/xpra/commit/83825717f43800f49b47263f7d3024ffb0c9159a)
    * [icon glob lookup mismatch](https://github.com/Xpra-org/xpra/commit/a68bf4e0cdee8c5e5453bbc6803cdad80892aca4)
    * [division by zero on MS Windows](https://github.com/Xpra-org/xpra/commit/e55643b5e28bf4eee036f8378c0c15376f53565d)
    * [update keyboard layout mapping for `ku` and `ir`](https://github.com/Xpra-org/xpra/commit/9713037378b8f3333396f54b2f54073eddef25fd)
    * [avoid lowering quality for `text` content type](https://github.com/Xpra-org/xpra/commit/d6de44ee4a83acd1d6b6ee8ff4bd614831b2d81d), [avoid scaling and subsampling](https://github.com/Xpra-org/xpra/commit/f20feb96ec42f20e337b9c64d2a02b710208fa72)
    * [avoid potential logging loop](https://github.com/Xpra-org/xpra/commit/ac9dda62adfa03e4110f61a3cbf8dcef3b6256ad)
    * [close splash screen on server start error](https://github.com/Xpra-org/xpra/commit/b0d73d180762ee150124eb244ac6c591ee9b583f)
* Cosmetic:
    * [`openh264` license tag](https://github.com/Xpra-org/xpra/commit/1a18f6e8b0f1b86f2cb36c1d31028b8ff0b863a5)
    * [remove outdated Wayland clipboard warning](https://github.com/Xpra-org/xpra/commit/8d046ff38d4f15ed9a6df8191bce312076b158cd)
    * [typo](https://github.com/Xpra-org/xpra/commit/76cbf4d484a55b5f58f444a1e0cb7b6d73053bc9)
    * [strict mode type mismatch](https://github.com/Xpra-org/xpra/commit/43d6b1daa621511eff19b0a12de159f8ffe139b9)
    * [incorrect compression debug logging](https://github.com/Xpra-org/xpra/commit/7fcf253b5091bb06fe88393a2fa27a020c97e162)
    * [incorrect damage elapsed time in debug logging](https://github.com/Xpra-org/xpra/commit/61a63d3665e74547f048b3d80af0b1df33a46281)

## [6.2.2] 2024-12-10
* Platforms, build and packaging:
    * [MSYS2 aarch64 build fix](https://github.com/Xpra-org/xpra/commit/d4b078ee67e4024cb2c8a6aea69dba0fe7400c14) and [prefix detection](https://github.com/Xpra-org/xpra/commit/9161b51b82cc89347fd317513d1fdba463c85208)
    * [RPM support](https://github.com/Xpra-org/xpra/commit/9710928f2ee99ee7e0a2c6ecbbc82e3961eba9d2) for [per arch pkgconfig](https://github.com/Xpra-org/xpra/commit/423e9d353ef57cee93f913cd8d9e6582ac640d62)
    * [missing SVG loader on MS Windows](https://github.com/Xpra-org/xpra/commit/33f59f2126ccf6c26b7c1d28c1f35677b51986ac)
    * [loaders cache not populated on MS Windows](https://github.com/Xpra-org/xpra/commit/5985efd29669624b70d2e64add09a0809d651e91)
    * [`install-repo` file permission on Debian](https://github.com/Xpra-org/xpra/commit/d6ed81dfce74283c8ad8f772e3a3269164cbf84e)
    * [record which repository is targeted](https://github.com/Xpra-org/xpra/commit/fe83ee09b17c2a7e26b228a1d5fc208aa347c2aa)
    * [`libproxy` support for MS Windows clients](https://github.com/Xpra-org/xpra/commit/1e9e6ac3983ea23c1ce3e3114b62f8cdaa30a5f0)
    * [`PyOpenGL 3.1.8`](https://github.com/Xpra-org/xpra/commit/eb5f228919fadfed7a52ab6124f219e385645448) + [force upgrade](https://github.com/Xpra-org/xpra/commit/c9efad7907e5b309882023e32de21ab695a82e10)
    * [missing MacOS AES library](https://github.com/Xpra-org/xpra/commit/25b568965ddb388f3d21d666a722043dbf02351b)
    * [support providing build arguments using environment](https://github.com/Xpra-org/xpra/commit/cc345e3bb76349d9900dd391bca9e07c80f83cea)
    * [syntax errors in the MS Windows build setup script](https://github.com/Xpra-org/xpra/commit/121c33de3d8fe54ede6c7ca30f478b5e0a1823eb)
    * [`openh264` 2.5.0](https://github.com/Xpra-org/xpra/commit/580822e4a035e0a1a559b443f2392bce374eb979)
    * [`python-pillow` 11.0.0](https://github.com/Xpra-org/xpra/commit/03f6306a2b2a734fa1479fa50b02f7dca9f1c8bb)
    * [require `clang++` for building CUDA kernels on some Debian distributions](https://github.com/Xpra-org/xpra/commit/85a5462819a511a660792a8e25b1ad2d0d662c67) + [fixup](https://github.com/Xpra-org/xpra/commit/6966b65df8a1968ce687d2e68bf96bc3d2261c54)
    * [`install-dev` to honour Xdummy flag](https://github.com/Xpra-org/xpra/commit/759e2d7e18006ca20d62339b021ebe72e0da5a0e)
* SBOM:
    * [SBOM support on MS Windows](https://github.com/Xpra-org/xpra/commit/78a6e04cd39f694a38200dc059996ce02beb7ac1), [use it](https://github.com/Xpra-org/xpra/commit/4042c8355a6a9225bb9891d56b53931f4264a525), [fix it](https://github.com/Xpra-org/xpra/commit/ac7a860264680615db570a5e4ad4a014bf852952)
    * [record for CUDA](https://github.com/Xpra-org/xpra/commit/055d564d55f5bdd912af1402f8d1999cfb089bd8)
    * [record 'Light' builds](https://github.com/Xpra-org/xpra/commit/b4d43a6a2c1c95fd875f4881eaf64e4a00f38fb7)
    * [export to JSON](https://github.com/Xpra-org/xpra/commit/752294b7b8e58657196503afc2ed4dac6e311dbe)
    * [record pip packages](https://github.com/Xpra-org/xpra/commit/f2e321d14a8a2377a6bffb74e8bf22a7e5b3fa93) + [minor fixup](https://github.com/Xpra-org/xpra/commit/9ed57a446871897ef53509248f258076c4a9d12f)
* Encodings:
    * [honour `openh264` maximum dimensions](https://github.com/Xpra-org/xpra/commit/fc79af387508ec63e8ccc572306aef47d8bdbfbc)
    * [`rgb` errors at unusual bit depths](https://github.com/Xpra-org/xpra/commit/7796b6b8e72f37c68a44ac5ecfccd88cf3b0e680)
    * 10 bits per channel issues: [use pillow](https://github.com/Xpra-org/xpra/commit/c179eb4b24f884953dbc11e610fad6adece407be), [detect alpha channel correctly](https://github.com/Xpra-org/xpra/commit/e2c2f87a893fc0c46ae612b418824191729bfce8) [and encode it properly](https://github.com/Xpra-org/xpra/commit/e0ae9ee74380649d6587561f104d213365143199)
* System Tray Menu:
    * [options disabled once 'auto' is selected](https://github.com/Xpra-org/xpra/commit/6d4e6334179bc143107d5eac6463ae29d42f7d17)
    * [speed tuning disabled](https://github.com/Xpra-org/xpra/commit/f41a9f64fad92fa7a8c737011c98122e5c4aa6bf)
* Major:
    * [authentication options not honoured with some bind options](https://github.com/Xpra-org/xpra/commit/60e1377ac48d3de4e35819f4347666a343967cb4)
    * [disable workspace support on MS Windows to prevent crashes](https://github.com/Xpra-org/xpra/commit/e95d8674009145747af49f5b491a100d72051c6e)
    * [`start-gui` fails if no application is selected](https://github.com/Xpra-org/xpra/commit/fbc0a66451d5c1818e67a8097ff522b222802857)
    * [prevent padded image overflows](https://github.com/Xpra-org/xpra/commit/6d952d483299017ece05dd9b47b4913d14696967)
    * [`xpra top` corrupted output](https://github.com/Xpra-org/xpra/commit/129c5b1f2695ce2f085268134b1273cf94c4e56f), [initialization failure](https://github.com/Xpra-org/xpra/commit/fc8638d436fa09e98f2ecb324d249b4145763955)
    * [`vsock` connection errors](https://github.com/Xpra-org/xpra/commit/c0448d2988d5497aac72d528ed1edc9a13514a6e)
    * [printing errors on MS Windows](https://github.com/Xpra-org/xpra/commit/fbf1c7a3e393974fe8c7d7fc8bf266639f2d9731)
    * [use symlinks to prevent ssh agent forwarding setup errors](https://github.com/Xpra-org/xpra/commit/a6e1d44edff4202240de1d61e3aaf154e7417d56)
* Minor:
    * [clamp 'vrefresh' to a useful range](https://github.com/Xpra-org/xpra/commit/e289ac6094f45d0ba020642775d96b14e61a2575)
    * [`quic` connections are safe for authentication](https://github.com/Xpra-org/xpra/commit/aa7bd5adf0835d875020737d655f3bfae7faacac)
* Cosmetic:
    * [add missing autentication modules to documentation](https://github.com/Xpra-org/xpra/commit/3aa90b898e427fb4a3f4ade3be3e650848f4073c)
    * [add `pyopenssl` to dependencies documentation](https://github.com/Xpra-org/xpra/commit/4e7941fa8d18e6b90fa257bad34401a5aad5c81f)
    * [unnecessary import](https://github.com/Xpra-org/xpra/commit/6e389e0b1292897d46f46f39a33eb0b9551d5c2b)
    * [broken OpenGL drivers documentation link](https://github.com/Xpra-org/xpra/commit/0248d7db2845727b5f307fc64d76a9fb91d5f705)
    * [handle missing pillow more gracefully](https://github.com/Xpra-org/xpra/commit/631a5b2d7a5d4352ec2bda7e2fd6cf149ae4565f)
    * [show full icondata error](https://github.com/Xpra-org/xpra/commit/4e7d1194e9f29969b5f0f9b62a607454d2a0bb50)
    * [proxy error messages formatting](https://github.com/Xpra-org/xpra/commit/8df110bb8010aa48c3c062fc9614753232e57f68)

## [6.2.1] 2024-10-29
* System tray:
    * [paint errors with `mmap` mode](https://github.com/Xpra-org/xpra/commit/42e039eb3b5ab256a926f6be530ce5e54be96742)
    * [distorted paints](https://github.com/Xpra-org/xpra/commit/450f17a217a0f0361f20eb5b072646598a3ceeb7)
* Major:
    * [OpenGL errors with MS Windows clients](https://github.com/Xpra-org/xpra/commit/adc0487184923a7f08d3623b4ba2eb50feeb5276) [missing stderr](https://github.com/Xpra-org/xpra/commit/ee8827a44cad3a2a0e2d171c85979b3d9e425dc7)
    * [keycode mapping for Wayland clients](https://github.com/Xpra-org/xpra/commit/8df4acacccd1780e9ef3ecdcaf71e1194cb14cce)
    * [some windows not shown when there is a tray window being forwarded](https://github.com/Xpra-org/xpra/commit/445ea1d4f11cdfdac655c4729fd7af360a37b481)
    * [connection failures on some server platforms](https://github.com/Xpra-org/xpra/commit/66e69de7481241f47626fa48ab8691abaa3eb646)
* Minor:
    * [quality and speed options can be used with generic encodings](https://github.com/Xpra-org/xpra/commit/c4a4f3e2559a962301db1dbc60763540a1560a22)
    * [check `pam_start` return value in `pam` authentication module](https://github.com/Xpra-org/xpra/commit/33d71abe81eab7cdccce6e5366f9aa9d508b52a3)
    * [`install-repo` support for Debian and Ubuntu derivatives](https://github.com/Xpra-org/xpra/commit/a8dc44fa7e82381ca1a83b8f76a51e937e4a3247)
* Cosmetic:
    * [show which client backend values are acceptable](https://github.com/Xpra-org/xpra/commit/ae425f0fc919011755dff678c687fa2f04221239)
    * [log OpenGL probe errors](https://github.com/Xpra-org/xpra/commit/43e291cd691c9c8d2afd434f19a1da85d5771373)
    * [date in changelog](https://github.com/Xpra-org/xpra/commit/972da07248e2f51566ddf0ca189a0344a2f1c420)
    * [add Ubuntu `oracular` support to `install-repo` subcommand](https://github.com/Xpra-org/xpra/commit/c1a859c1d68a9198b5b5656857bd70a04be97a53)
    * [border color parsing deprecation warning](https://github.com/Xpra-org/xpra/commit/43be8ee67b0bba5ffc8589ac1bd23269ffffbd6b)

## [6.2.0] 2024-10-09
* Platforms, build and packaging:
    * [pycuda for Fedora 41](https://github.com/Xpra-org/xpra/issues/4332)
    * [move `opengl` module to top level](https://github.com/Xpra-org/xpra/commit/111afa5e028bea7b006bb6cb820e4104af8ba4e9)
    * [re-enable cython csc module](https://github.com/Xpra-org/xpra/commit/b89ed18a344a30780b69a3288f8e741287e81e0e)
* Fixes:
    * [AES padding](https://github.com/Xpra-org/xpra/issues/4372)
* Features:
    * [PoC PyQt6 client](https://github.com/Xpra-org/xpra/issues/4314)
    * [`minimal` command line switch](https://github.com/Xpra-org/xpra/issues/3953)
    * [option to completely disable all of GStreamer](https://github.com/Xpra-org/xpra/issues/4330)
    * [strongly enforce disabled subsystems](https://github.com/Xpra-org/xpra/issues/4307)
    * [watch for start menu file changes reliably, on all platforms](https://github.com/Xpra-org/xpra/issues/3335)
    * [improve transient and permanent hardware codec failures differently](https://github.com/Xpra-org/xpra/issues/4348)
    * [continue to remove GTK](https://github.com/Xpra-org/xpra/issues/3871)
    * [guess initial server display resolution](https://github.com/Xpra-org/xpra/issues/4302)
* Network:
    * [multi-processing proxy server with SSL](https://github.com/Xpra-org/xpra/issues/4362)
    * [more control commands for proxy instances](https://github.com/Xpra-org/xpra/issues/4363)
    * [inline more data in network packets](https://github.com/Xpra-org/xpra/issues/4366)
    * [SSL setup made easy](https://github.com/Xpra-org/xpra/issues/4288)

## [6.1] 2024-07-18
* Platforms, build and packaging:
    * [RHEL 10 builds](https://github.com/Xpra-org/xpra/issues/4282)
    * make it easier to [setup a development environment](https://github.com/Xpra-org/xpra/issues/4244) and [to install the repositories](https://github.com/Xpra-org/xpra/issues/4245)
* Encodings:
    * [faster scaling of subsampled images without OpenGL](https://github.com/Xpra-org/xpra/issues/4209)
    * [zero-copy drawing without OpenGL](https://github.com/Xpra-org/xpra/issues/4270)
    * [scale YUV before converting to RGB](https://github.com/Xpra-org/xpra/issues/4209)
    * [full range video compression](https://github.com/Xpra-org/xpra/issues/3837)
    * [GPU checks from a containerized environment](https://github.com/Xpra-org/xpra/pull/4257)
    * [colorspace fixes](https://github.com/Xpra-org/xpra/issues/3837)
* Network:
    * [WebTransport server](https://github.com/Xpra-org/xpra/issues/3376#issuecomment-2198059166)
    * [QUIC fast-open](https://github.com/Xpra-org/xpra/commit/475531d9d4433fa8ac89d5d0ce96744d8519e56d)
* Features:
    * [handle display scaling correctly on more platforms](https://github.com/Xpra-org/xpra/issues/4205)
    * [use native file chooser on some platforms](https://github.com/Xpra-org/xpra/issues/4222)
    * [support custom window grouping](https://github.com/Xpra-org/xpra/issues/4208)
    * [optional username verification for authentication modules](https://github.com/Xpra-org/xpra/issues/4294)
    * [resize virtual display to a specific resolution only](https://github.com/Xpra-org/xpra/issues/4279)
    * [filter environment exposed to xvfb subcommand](https://github.com/Xpra-org/xpra/issues/4252)
* Cosmetic:
    * many type hints added
    * linter warnings fixed

## [6.0] 2024-04-25
* Platforms, build and packaging:
    * [build packages for multiple python targets](https://github.com/Xpra-org/xpra/issues/3945)
    * [require and take advantage of Python 3.10+](https://github.com/Xpra-org/xpra/issues/3930)
    * [cythonize everything](https://github.com/Xpra-org/xpra/issues/3978) and [build test on git push](https://github.com/Xpra-org/xpra/commit/85bb9cf53d599f8133acc7efd63e052b4308e139)
    * [workaround for distributions incompatible with CUDA](https://github.com/Xpra-org/xpra/issues/3808)
    * [add `xpra-client-gnome` package](https://github.com/Xpra-org/xpra/commit/8a5c240e579da02db710c4cc17517aee570ed875)
    * [use the system provided xxHash library](https://github.com/Xpra-org/xpra/issues/3929)
    * [riscv64 builds](https://github.com/Xpra-org/xpra/issues/3936)
    * [PEP 517: pyproject.toml](https://github.com/Xpra-org/xpra/issues/4085)
* Features:
    * [OpenGL core profile](https://github.com/Xpra-org/xpra/issues/2467)
    * [`xpra configure` tool](https://github.com/Xpra-org/xpra/issues/3964)
    * [faster `mmap`](https://github.com/Xpra-org/xpra/issues/4013)
    * [make it easier to disable almost everything](https://github.com/Xpra-org/xpra/issues/3953), [audio](https://github.com/Xpra-org/xpra/issues/3835) or [video](https://github.com/Xpra-org/xpra/issues/3952)
    * [remove legacy compatibility](https://github.com/Xpra-org/xpra/issues/3592)
    * [try harder to locate the correct xauth file](https://github.com/Xpra-org/xpra/issues/3917)
    * [honour MacOS backing scale factor with OpenGL](https://github.com/Xpra-org/xpra/commit/efe31046f9dc25587e572975cbdc150c5be721f1)
    * [workspace support for MS Windows 10](https://github.com/Xpra-org/xpra/issues/1442)
    * [readonly memoryviews](https://github.com/Xpra-org/xpra/issues/4110)
* Network:
    * [abstract sockets](https://github.com/Xpra-org/xpra/issues/4098)
    * [wait for local server sockets to become available](https://github.com/Xpra-org/xpra/commit/53c5032ad7216770ee6198802d0fbbcf0799cdc1)
    * [enable websocket upgrades without the html5 client](https://github.com/Xpra-org/xpra/issues/3932)
    * [update ssh agent to active user](https://github.com/Xpra-org/xpra/issues/3593)
    * [use libnm to access network information](https://github.com/Xpra-org/xpra/issues/3623)
    * [ssl auto upgrade](https://github.com/Xpra-org/xpra/issues/3313)
    * [honour `/etc/ssh/ssh_config`](https://github.com/Xpra-org/xpra/issues/4083)
    * [`xpra list-clients`](https://github.com/Xpra-org/xpra/issues/4082)
* Cosmetic:
    * silence warnings: [#4023](https://github.com/Xpra-org/xpra/issues/4023), [#2177](https://github.com/Xpra-org/xpra/issues/2177), [#3988](https://github.com/Xpra-org/xpra/issues/3988), [#4028](https://github.com/Xpra-org/xpra/issues/4028)
    * [easier call tracing](https://github.com/Xpra-org/xpra/issues/4125)
    * [PEP 8: code style](https://github.com/Xpra-org/xpra/issues/4086)
* Documentation:
    * [ivshmem](https://github.com/Xpra-org/xpra/blob/master/docs/Subsystems/MMAP.md#virtio-shmem)
    * [subsystems](https://github.com/Xpra-org/xpra/issues/3981)
    * [authentication handlers](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md#client-syntax)
    * [record some SBOM data](https://github.com/Xpra-org/xpra/issues/4050)

## [5.0] 2023-07-18
* Major improvements:
    * [QUIC transport](https://github.com/Xpra-org/xpra/issues/3376)
    * [split packaging](https://github.com/Xpra-org/xpra/issues/3802)
    * [freedesktop screencast / remotedesktop](https://github.com/Xpra-org/xpra/issues/3750) for X11 and Wayland
    * ease of use: [easier basic commands](https://github.com/Xpra-org/xpra/issues/3841), [open html5 client](https://github.com/Xpra-org/xpra/issues/3842), [disable all audio features](https://github.com/Xpra-org/xpra/issues/3835)
* Platforms, build and packaging:
    * [Python 3.12 installations](https://github.com/Xpra-org/xpra/issues/3807)
    * [replace Python2 builds](https://github.com/Xpra-org/xpra/issues/3652)
    * [LTS feature deprecation](https://github.com/Xpra-org/xpra/issues/3592)
    * [stricter type checks](https://github.com/Xpra-org/xpra/issues/3927)
    * [more MacOS workarounds](https://github.com/Xpra-org/xpra/issues/3777)
* Server:
    * [try harder to find a valid menu prefix](https://github.com/Xpra-org/xpra/commit/a42e2343ee572ff2edb28ece0b38904969c75470)
    * [exit with windows](https://github.com/Xpra-org/xpra/issues/3595)
    * [side buttons with MS Windows shadow servers](https://github.com/Xpra-org/xpra/pull/3865)
    * [mirror client monitor layout](https://github.com/Xpra-org/xpra/issues/3749)
* Client:
    * [allow keyboard shortcuts in readonly mode](https://github.com/Xpra-org/xpra/issues/3899)
    * [show decoder statistics](https://github.com/Xpra-org/xpra/issues/3796)
    * [keyboard layout switching shortcut](https://github.com/Xpra-org/xpra/pull/3859)
    * [layout switching detection for MS Windows](https://github.com/Xpra-org/xpra/issues/3857)
    * [mirror mouse cursor when sharing](https://github.com/Xpra-org/xpra/issues/3767)
* Minor:
    * [generic exec authentication module](https://github.com/Xpra-org/xpra/issues/3790)
    * [audio `removesilence`](https://github.com/Xpra-org/xpra/issues/3709)
    * [make pulseaudio real-time and high-priority scheduling modes configurable](https://github.com/Xpra-org/xpra/pull/3893)
    * [use urrlib for parsing](https://github.com/Xpra-org/xpra/issues/3599)
    * [GTK removal progress](https://github.com/Xpra-org/xpra/issues/3871)
    * documentation updates and fixes: [broken links](https://github.com/Xpra-org/xpra/pull/3839), [typos](https://github.com/Xpra-org/xpra/pull/3836)
* Network:
    * [smaller handshake packet](https://github.com/Xpra-org/xpra/issues/3812)
    * [SSL auto-upgrade](https://github.com/Xpra-org/xpra/issues/3313)
    * [better IPv6](https://github.com/Xpra-org/xpra/issues/3853)
    * [new packet format](https://github.com/Xpra-org/xpra/issues/1942)
    * [ssh agent forwarding automatic switching when sharing](https://github.com/Xpra-org/xpra/issues/3593)
    * [use libnm to query network devices](https://github.com/Xpra-org/xpra/issues/3623)
    * [exclude more user data by default](https://github.com/Xpra-org/xpra/issues/3582)
* Encodings:
    * [use intra refresh](https://github.com/Xpra-org/xpra/issues/3830)
    * [`stream` encoding for desktop mode](https://github.com/Xpra-org/xpra/issues/3872)
    * [GStreamer codecs](https://github.com/Xpra-org/xpra/issues/3706)


## [4.4] 2022-10-01
* Platforms, build and packaging:
    * [Native LZ4 bindings](https://github.com/Xpra-org/xpra/issues/3601)
    * Safer native brotli bindings for [compression](https://github.com/Xpra-org/xpra/issues/3572) and [decompression](https://github.com/Xpra-org/xpra/issues/3258)
    * [Native qrencode bindings](https://github.com/Xpra-org/xpra/issues/3578)
    * [openSUSE build tweaks](https://github.com/Xpra-org/xpra/issues/3597), [Fedora 37](https://github.com/Xpra-org/xpra/commit/414a1ac9ae2775f1566a800aa1eb4688361f2c38), [Rocky Linux / Alma Linux / CentOS Stream : 8 and 9](https://github.com/Xpra-org/repo-build-scripts/commit/f53085abf3227e4b758c3f4c04fa96092fc2b599), [Oracle Linux](https://github.com/Xpra-org/repo-build-scripts/commit/56a2bf9a48e55924782eb777b05e2b37262868e5)
    * [Debian finally moved to `libexec`](https://github.com/Xpra-org/xpra/issues/3493)
    * [MS Windows taskbar integration](https://github.com/Xpra-org/xpra/issues/508)
    * [SSH server support on MS Windows, including starting shadow sessions](https://github.com/Xpra-org/xpra/issues/3626)
* Server:
    * [Configurable vertical refresh rate](https://github.com/Xpra-org/xpra/issues/3600)
    * [Virtual Monitors](https://github.com/Xpra-org/xpra/issues/56)
    * [Multi-monitor desktop mode](https://github.com/Xpra-org/xpra/issues/3524)
    * [Expand an existing desktop](https://github.com/Xpra-org/xpra/issues/3390)
    * [Exit with windows](https://github.com/Xpra-org/xpra/issues/3595)
    * [Full shadow keyboard mapping](https://github.com/Xpra-org/xpra/issues/2630)
    * [xwait subcommand](https://github.com/Xpra-org/xpra/issues/3386)
    * [guess content-type from parent pid](https://github.com/Xpra-org/xpra/issues/2753)
    * [cups print backend status report](https://github.com/Xpra-org/xpra/issues/1228)
    * [Override sockets on upgrade](https://github.com/Xpra-org/xpra/issues/3568)
    * [Allow additional options to X server invocation](https://github.com/Xpra-org/xpra/issues/3553)
    * Control commands for [modifying command environment](https://github.com/Xpra-org/xpra/issues/3502), and [read only flag](https://github.com/Xpra-org/xpra/issues/3466)
    * [Start new commands via a proxy server's SSH listener](https://github.com/Xpra-org/xpra/issues/2898)
* Shadow server:
    * [Geometry restrictions](https://github.com/Xpra-org/xpra/issues/3384)
    * [Shadow specific applications](https://github.com/Xpra-org/xpra/issues/3476)
* Client:
    * [Automatic keyboard grabs](https://github.com/Xpra-org/xpra/issues/3059)
    * [Pointer confinement](https://github.com/Xpra-org/xpra/issues/3059)
    * [Faster window initial data](https://github.com/Xpra-org/xpra/issues/3473)
    * [Improved DPI detection on MS Windows](https://github.com/Xpra-org/xpra/issues/1526)
    * [Show all current keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2779)
    * [Preserve all options when reconnecting](https://github.com/Xpra-org/xpra/issues/3207)
    * [Option to accept SSL mismatched host permanently](https://github.com/Xpra-org/xpra/issues/3305)
    * [Forward all command line options](https://github.com/Xpra-org/xpra/issues/3566)
    * [Smooth scrolling options](https://github.com/Xpra-org/xpra/issues/3127)
    * [Per-window scaling](https://github.com/Xpra-org/xpra/issues/3454) - experimental
    * [Workaround Wayland startup hangs](https://github.com/Xpra-org/xpra/issues/3630)
* Security and authentication:
    * [Configurable information disclosure](https://github.com/Xpra-org/xpra/issues/3582)
    * [Keycloak authentication](https://github.com/Xpra-org/xpra/issues/3486)
    * [Capability based authentication](https://github.com/Xpra-org/xpra/issues/3575)
    * [Authentication for web server scripts](https://github.com/Xpra-org/xpra/issues/3100)
    * [OTP authentication](https://github.com/Xpra-org/xpra/issues/2906)
    * [Workaround paramiko `No existing session` error](https://github.com/Xpra-org/xpra/issues/3223)
* Encodings and latency:
    * [Option to cap picture quality](https://github.com/Xpra-org/xpra/issues/3420)
    * [Expose scaling quality](https://github.com/Xpra-org/xpra/issues/3598)
    * [NVJPEG decoder](https://github.com/Xpra-org/xpra/issues/3504) (WIP - leaks memory)
    * [AVIF encoding](https://github.com/Xpra-org/xpra/issues/3457)
    * [selective `scroll` encoding detection](https://github.com/Xpra-org/xpra/issues/3519)
* Network:
    * [SOCKS proxy connection support](https://github.com/Xpra-org/xpra/issues/2105)
    * [SSH agent forwarding](https://github.com/Xpra-org/xpra/issues/2303)
    * [proxy network performance improvement](https://github.com/Xpra-org/xpra/issues/2976)
    * [SSH workarounds for polluted stream premable](https://github.com/Xpra-org/xpra/issues/3610)
* Misc:
    * [easier xpra subcommand invocation](https://github.com/Xpra-org/xpra/issues/3371)
* Refactoring and preparation for the next LTS release:
    * [Feature deprecation](https://github.com/Xpra-org/xpra/issues/3592)
    * [Remove "app menus" support](https://github.com/Xpra-org/xpra/issues/2163)
    * [Remove ancient complicated code](https://github.com/Xpra-org/xpra/issues/3537)
    * [Simplify the build file](https://github.com/Xpra-org/xpra/issues/3577)
    * [More robust info handlers](https://github.com/Xpra-org/xpra/issues/3509)
    * [Remove scary warnings](https://github.com/Xpra-org/xpra/issues/3625)
    * [f-strings](https://github.com/Xpra-org/xpra/issues/3579)


## [4.3] 2021-12-05
* Platforms, build and packaging:
	* [arm64 support](https://github.com/Xpra-org/xpra/issues/3291), including [nvenc and nvjpeg](https://github.com/Xpra-org/xpra/issues/3378)
	* [non-system header builds (eg: conda)](https://github.com/Xpra-org/xpra/issues/3360)
	* [fixed MacOS shadow start via ssh](https://github.com/Xpra-org/xpra/issues/3343)
	* [parallel builds](https://github.com/Xpra-org/xpra/issues/3255)
	* [don't ship too may pillow plugins](https://github.com/Xpra-org/xpra/issues/3133)
	* [easier access to documentation](https://github.com/Xpra-org/xpra/issues/3015)
	* [Python 3.10 buffer api compatibility](https://github.com/Xpra-org/xpra/issues/3031)
* Misc:
	* [make it easier to silence OpenGL validation warnings](https://github.com/Xpra-org/xpra/issues/3380)
	* [don't wait for printers](https://github.com/Xpra-org/xpra/issues/3170)
	* [make it easier to autostart](https://github.com/Xpra-org/xpra/issues/3134)
	* [`clean` subcommand](https://github.com/Xpra-org/xpra/issues/3099)
	* [flexible 'run_scaled' subcommand](https://github.com/Xpra-org/xpra/issues/3303)
	* [more flexible key shortcuts configuration](https://github.com/Xpra-org/xpra/issues/3183)
* Encodings and latency:
	* [significant latency and performance improvements](https://github.com/Xpra-org/xpra/issues/3337)
	* [spng decoder](https://github.com/Xpra-org/xpra/issues/3373) and [encoder](https://github.com/Xpra-org/xpra/issues/3374)
	* [jpeg with transparency](https://github.com/Xpra-org/xpra/issues/3367)
	* [faster argb module](https://github.com/Xpra-org/xpra/issues/3361)
	* [faster nvjpeg module using CUDA, add transparency](https://github.com/Xpra-org/xpra/issues/2984)
	* [faster xshape scaling](https://github.com/Xpra-org/xpra/issues/1226)
	* [downscale jpeg and webp](https://github.com/Xpra-org/xpra/issues/3333)
	* [disable av-sync for applications without audio](https://github.com/Xpra-org/xpra/issues/3351)
	* [opaque region support](https://github.com/Xpra-org/xpra/issues/3317)
	* [show FPS on client window](https://github.com/Xpra-org/xpra/issues/3311)
	* [nvenc to use the same device context as nvjpeg](https://github.com/Xpra-org/xpra/issues/3195)
	* [nvenc disable unsupported presets](https://github.com/Xpra-org/xpra/issues/3136)
* Network:
	* [make it easier to use SSL](https://github.com/Xpra-org/xpra/issues/3299)
	* [support more AES modes: GCM, CFB and CTR](https://github.com/Xpra-org/xpra/issues/3247)
	* [forked rencodeplus encoder](https://github.com/Xpra-org/xpra/issues/3229)
* Server:
	* [shadow specific areas or monitors](https://github.com/Xpra-org/xpra/issues/3320)
	* [faster icon lookup](https://github.com/Xpra-org/xpra/issues/3326)
	* [don't trust _NET_WM_PID](https://github.com/Xpra-org/xpra/issues/3251)
	* [move all sessions to a subdirectory](https://github.com/Xpra-org/xpra/issues/3217)
	* [more reliable server cleanup](https://github.com/Xpra-org/xpra/issues/3218)
	* [better VNC support](https://github.com/Xpra-org/xpra/issues/3256)
	* [more seamless server upgrades](https://github.com/Xpra-org/xpra/issues/541)
	* [source /etc/profile](https://github.com/Xpra-org/xpra/issues/3083)
	* [switch input method to ibus](https://github.com/Xpra-org/xpra/issues/2359)


## [4.2] 2021-05-18
* [use pinentry for password prompts](https://github.com/Xpra-org/xpra/issues/3002) and [ssh prompts](https://github.com/Xpra-org/xpra/commit/2d2022d184f31f53c2328b5e5ca804e5ea46ff6c)
* [nvjpeg encoder](https://github.com/Xpra-org/xpra/issues/2984) - also requires [this commit](https://github.com/Xpra-org/xpra-html5/commit/cd846f0055276ecd9b021767a13be05a16e833eb) to the [html5 client](https://github.com/Xpra-org/xpra-html5/)
* [gui for starting remote sessions](https://github.com/Xpra-org/xpra/issues/3070)
* new subcommands: `recover`, `displays`, `list-sessions`, `clean-displays`, `clean-sockets` - [#3098](https://github.com/Xpra-org/xpra/issues/3098), [#3099](https://github.com/Xpra-org/xpra/issues/3099)
* many fixes: [window initial position](https://github.com/Xpra-org/xpra/issues/2008), [focus](https://github.com/Xpra-org/xpra/issues/2852), non-opengl paint corruption, [slow rendering on MacOS](https://github.com/Xpra-org/xpra/commit/5ad0e767441454758b111f1c80baf49c10b964e8), build scripts, [handle smooth scroll events with wayland clients](https://github.com/Xpra-org/xpra/issues/3127), always lossy screen updates for terminals, [clipboard timeout](https://github.com/Xpra-org/xpra/issues/3086), [peercred auth options](https://github.com/Xpra-org/xpra/commit/e401e650c18974288d71cebc6491970698560a9f)
* support multiple clients using mmap simultaneously [with non-default file paths](https://github.com/Xpra-org/xpra/commit/ef936f461996915547141e8d02c15a57516d5ff0)
* [only synchronize xsettings with seamless servers](https://github.com/Xpra-org/xpra/commit/f7cbb40230ed5170859f5b5ea6cbd27ded3d3d02)
* automatic desktop scaling is now [disabled](https://github.com/Xpra-org/xpra/commit/092800cbe44716fb0adaf842de5bc95a6329527a)
* workaround for [gnome applications starting slowly](https://github.com/Xpra-org/xpra/issues/3109)

## [4.1] 2021-02-26
* Overhauled container based [build system](https://github.com/Xpra-org/xpra/tree/master/packaging/buildah)
* [Splash screen](https://github.com/Xpra-org/xpra/issues/2540)
* [`run_scaled` utility script](https://github.com/Xpra-org/xpra/issues/2813)
* Client:
	* [header bar option](https://github.com/Xpra-org/xpra/issues/2539) for window control menu
	* generate a [qrcode](https://github.com/Xpra-org/xpra/issues/2627) to connect
	* show all [keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2779)
	* [progress bar](https://github.com/Xpra-org/xpra/issues/2678) for file transfers
	* GTK cairo backend support for [more native bit depths](https://github.com/Xpra-org/xpra/issues/2839)
	* [disable xpra's keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2739) from the system tray menu
	* automatically [include the server log](https://github.com/Xpra-org/xpra/issues/2570) in bug reports
* OpenGL client backend:
	* render at [fixed bit depths](https://github.com/Xpra-org/xpra/issues/2826) with the `pixel-depth` option
	* support [more bit depths](https://github.com/Xpra-org/xpra/issues/2828)
* Clipboard:
	* [MacOS support](https://github.com/Xpra-org/xpra/issues/273) for images, more text formats, etc
	* [MS Windows](https://github.com/Xpra-org/xpra/issues/2619) support for images
	* [wayland](https://github.com/Xpra-org/xpra/issues/2927) clients
* Server:
	* [faster server startup](https://github.com/Xpra-org/xpra/issues/2815)
	* [`xpra list-windows`](https://github.com/Xpra-org/xpra/issues/2700) subcommand
	* new window control commands: [move - resize](https://github.com/Xpra-org/xpra/issues/2774), [map - unmap](https://github.com/Xpra-org/xpra/issues/3028)
	* remote logging: [from server to client](https://github.com/Xpra-org/xpra/issues/2749)
	* support [window re-stacking](https://github.com/Xpra-org/xpra/issues/2896)
* `xpra top`:
	* [show pids, shortcuts](https://github.com/Xpra-org/xpra/issues/2601)
	* more details in the [list view](https://github.com/Xpra-org/xpra/issues/2553)
	* show [speed and quality](https://github.com/Xpra-org/xpra/issues/2719)
* Display:
	* bumped maximum resolution [beyond 8K](https://github.com/Xpra-org/xpra/issues/2628)
	* [set the initial resolution](https://github.com/Xpra-org/xpra/issues/2772) more easily using the 'resize-display' option
* Encoding:
	* server side picture [downscaling](https://github.com/Xpra-org/xpra/issues/2052)
	* [libva](https://github.com/Xpra-org/xpra/issues/451) hardware accelerated encoding
	* NVENC [30-bit](https://github.com/Xpra-org/xpra/issues/1308) accelerated encoding
	* vpx [30-bit](https://github.com/Xpra-org/xpra/issues/1310)
	* x264 [30-bit](https://github.com/Xpra-org/xpra/issues/1462)
	* faster [30-bit RGB subsampling](https://github.com/Xpra-org/xpra/issues/2773)
	* scroll encoding now handled [more generically](https://github.com/Xpra-org/xpra/issues/2810)
	* [black and white](https://github.com/Xpra-org/xpra/issues/1713) mode
* Network:
	* [IGD / UPNP](https://github.com/Xpra-org/xpra/issues/2417)
	* [SO_KEEPALIVE](https://github.com/Xpra-org/xpra/issues/2420) option
	* clients can be [queried](https://github.com/Xpra-org/xpra/issues/2743) and [controlled](https://github.com/Xpra-org/xpra/issues/2856) using local sockets
	* specify connection attributes [using the connection string](https://github.com/Xpra-org/xpra/issues/2794)
	* [nested SSH tunnels](https://github.com/Xpra-org/xpra/issues/2867)
	* websocket [header modules](https://github.com/Xpra-org/xpra/issues/2874)
	* [specify the socket type](https://github.com/Xpra-org/xpra/issues/2914) with socket activation
	* expose the [packet flush flag](https://github.com/Xpra-org/xpra/issues/2975)
	* [`xpra shell`](https://github.com/Xpra-org/xpra/issues/2750) subcommand for interacting with processes in real time
	* [custom group sockets directory](https://github.com/Xpra-org/xpra/issues/2907) permissions and name
* Testing:
	* better [test coverage](https://github.com/Xpra-org/xpra/issues/2598)
	* [cleanup output](https://github.com/Xpra-org/xpra/issues/2938)

## [4.0] 2020-05-10
* Drop support for:
    * Python 2, GTK2
    * legacy versions (pre 1.0)
    * weak authentication
* Network, per socket options:
    * authentication and encryption
    * ssl
    * ssh
    * bind options for client
* make it easier to send files from the server
* xpra toolbox subcommand
* xpra help subcommand
* xpra top new features
* faster startup
* signal handling fixes
* smoother window resizing
* refactoring and testing
    * unit tests coverage and fixes
    * completely skip loading unused features at runtime
    * get rid of capabilities data after parsing it
    * better module dependency separation
    * don't convert to a string before we need it
* more useful window and tray title
* make it easier to source environment
* disable desktop animations in desktop mode
* automatic start-or-upgrade, automatic X11 display rescue
* support MS Windows OpenSSH server to start shadow
* more selective use of OpenGL acceleration in client
* expose server OpenGL capabilities
* cleaner HTML5 syntax


## [3.0] 2019-09-21
* Python 3 port complete, now the default: [#1571](https://github.com/Xpra-org/xpra/issues/1571), [#2195](https://github.com/Xpra-org/xpra/issues/2195)
* much nicer HTML5 client user interface: [#2269](https://github.com/Xpra-org/xpra/issues/2269)
* Window handling:
    * smoother window resizing: [#478](https://github.com/Xpra-org/xpra/issues/478) (OpenGL)
    * honouring gravity: [#2217](https://github.com/Xpra-org/xpra/issues/2217)
    * lock them in readonly mode: [#2137](https://github.com/Xpra-org/xpra/issues/2137)
* xpra top subcommand: [#2348](https://github.com/Xpra-org/xpra/issues/2348)
* faster startup:
    * [#2347](https://github.com/Xpra-org/xpra/issues/2347) faster client startup
    * [#2341](https://github.com/Xpra-org/xpra/issues/2341) faster server startup
* OpenGL:
    * more reliable driver probing: [#2204](https://github.com/Xpra-org/xpra/issues/2204)
    * cursor paint support: [#1497](https://github.com/Xpra-org/xpra/issues/1497)
    * transparency on MacOS: [#1794](https://github.com/Xpra-org/xpra/issues/1794)
* Encoding:
    * lossless window scrolling: [#1320](https://github.com/Xpra-org/xpra/issues/1320)
    * scrolling acceleration for non-OpenGL backends: [#2295](https://github.com/Xpra-org/xpra/issues/2295)
    * harden image parsing: [#2279](https://github.com/Xpra-org/xpra/issues/2279)
    * workaround slow video encoder initialization (ie: NVENC) using replacement frames: [#2048](https://github.com/Xpra-org/xpra/issues/2048)
    * avoid loading codecs we don't need: [#2344](https://github.com/Xpra-org/xpra/issues/2344)
    * skip some CUDA devices, speedup enumeration: [#2415](https://github.com/Xpra-org/xpra/issues/2415)
* Clipboard:
    * new native clipboard implementations for all platforms: [#812](https://github.com/Xpra-org/xpra/issues/812)
    * HTML5 asynchronous clipboard: [#1844](https://github.com/Xpra-org/xpra/issues/1844)
    * HTML5 support for copying images: [#2312](https://github.com/Xpra-org/xpra/issues/2312) (with watermarking)
    * brotli compression for text data: [#2289](https://github.com/Xpra-org/xpra/issues/2289)
* Authentication:
    * modular client authentication handlers: [#1796](https://github.com/Xpra-org/xpra/issues/1796)
    * mysql authentication module: [#2287](https://github.com/Xpra-org/xpra/issues/2287)
    * generic SQL authentication module: [#2288](https://github.com/Xpra-org/xpra/issues/2288)
* Network:
    * client listen mode: [#1022](https://github.com/Xpra-org/xpra/issues/1022)
    * retry to connect until it succeeds or times out: [#2346](https://github.com/Xpra-org/xpra/issues/2346)
    * mdns TXT attributes updated at runtime: [#2187](https://github.com/Xpra-org/xpra/issues/2187)
    * zeroconf fixes: [#2317](https://github.com/Xpra-org/xpra/issues/2317)
    * drop pybonjour: [#2297](https://github.com/Xpra-org/xpra/issues/2297)
    * paramiko honours IdentityFile: [#2282](https://github.com/Xpra-org/xpra/issues/2282), handles SIGINT better: [#2378](https://github.com/Xpra-org/xpra/issues/2378)
    * proxy server fixes for ssl and ssh sockets: [#2399](https://github.com/Xpra-org/xpra/issues/2399), remove spurious options: [#2193](https://github.com/Xpra-org/xpra/issues/2193)
    * proxy ping and timeouts: [#2408](https://github.com/Xpra-org/xpra/issues/2408)
    * proxy dynamic authentication: [#2261](https://github.com/Xpra-org/xpra/issues/2261)
* Automated Testing:
    * test HTML5 client: [#2231](https://github.com/Xpra-org/xpra/issues/2231)
    * many new mixin tests: [#1773](https://github.com/Xpra-org/xpra/issues/1773) (and bugs found)
* start-new-commands is now enabled by default: [#2278](https://github.com/Xpra-org/xpra/issues/2278), and the UI allows free text: [#2221](https://github.com/Xpra-org/xpra/issues/2221)
* basic support for native GTK wayland client: [#2243](https://github.com/Xpra-org/xpra/issues/2243)
* forward custom X11 properties: [#2311](https://github.com/Xpra-org/xpra/issues/2311)
* xpra launcher visual feedback during connection: [#1421](https://github.com/Xpra-org/xpra/issues/1421), sharing option: [#2115](https://github.com/Xpra-org/xpra/issues/2115)
* "Window" menu on MacOS: [#1808](https://github.com/Xpra-org/xpra/issues/1808)


## [2.5] 2019-03-19
* Python 3 port mostly complete, including packaging for Debian
* pixel compression and bandwidth management:
    * better recovery from network congestion
    * distinguish refresh from normal updates
    * better tuning for mmap connections
    * heuristics improvements
    * use video encoders more aggressively
    * prevent too many delayed frames with x264
    * better video region detection with opengl content
* better automatic tuning for client applications
    * based on application categories
    * application supplied hints
    * application window encoding hints
    * using environment variables and disabling video
* HTML5 client improvements
* Client improvements:
    * make it easier to start new commands, provide start menu
    * probe OpenGL in a subprocess to detect and workaround driver crashes
    * use appindicator if available
* Packaging:
    * merge xpra and its dependencies into the ​MSYS2 repository
    * ship fewer files in MS Windows installers
    * partial support for parallel installation of 32-bit and 64-bit version on MS Windows
    * MacOS library updates
    * CentOS 7: libyu## [] and turbojpeg
    * Windows Services for Linux (WSL) support
    * Fedora 30 and Ubuntu Disco support
    * Ubuntu HWE compatibility (manual steps required due to upstream bug)
* Server improvements:
    * start command on last client exit
    * honour minimum window size
    * Python 3
    * upgrade-desktop subcommand
* Network layer:
    * less copying
    * use our own websocket layer
    * make it easier to install mdns on MS Windows
    * make mmap group configurable
    * TCP CORK support on Linux
* SSH transport:
    * support .ssh/config with paramiko backend
    * connecting via ssh proxy hosts
* SSHFP with paramiko:
    * clipboard: restrict clipboard data transfers size
    * audio: support wasapi on MS Windows
* code cleanups, etc


## [2.4] 2018-10-13
* SSH client integration (paramiko)
* builtin server support for TCP socket upgrades to SSH (paramiko)
* automatic TCP port allocation
* expose desktop-sessions as VNC via mdns
* add zeroconf backend
* register more URL schemes
* window content type heuristics configuration
* use content type it to better tune automatic encoding selection
* automatic video scaling
* bandwidth-limit management in video encoders
* HTML5 client mpeg1 and h264 decoding
* HTML5 client support for forwarding of URL open requests
* HTML5 client Internet Explorer 11 compatibility
* HTML5 client toolbar improvements
* HTML5 fullscreen mode support
* limit video dimensions to cap CPU and bandwidth usage
* keyboard layout handling fixes
* better memory management and resource usage
* new default GUI welcome screen
* desktop file for starting shadow servers more easily
* clipboard synchronization with multiple clients
* use notifications bubbles for more important events
* workarounds for running under Wayland with GTK3
* modal windows enabled by default
* support xdg base directory specification and socket file time
* improved python3 support (still client only)
* multi-window shadow servers on MacOS and MS Windows
* buildbot upgrade
* more reliable unit tests
* fixes and workarounds for Java client applications
* locally authenticated users can shut down proxy servers
* restrict potential privileged information leakage
* enhanced per-client window filtering
* remove extra pixel copy in opengl enabled client
* clip pointer events to the actual window content size
* new platforms: Ubuntu Cosmic, Fedora 29


## [2.3] 2018-05-08
* stackable authentication modules
* tcp wrappers authentication module
* gss, kerberos, ldap and u2f authentication modules
* request access to the session
* pulseaudio server per session to prevent audio leaking
* better network bandwidth utilization and congestion management
* faster encoding and decoding: YUV for webp and jpeg, encoder hints, better vsync
* notifications actions forwarding, custom icons, expose warnings
* upload notification and management
* shadow servers multi window mode
* tighter client OS integratioin
* client window positioning and multiscreen support
* unique application icon used as tray icon
* multi stop or attach
* control start commands
* forward signals sent to windows client side
* forward requests to open URLs or files on the server side
* html5 client improvements: top bar, debugging, etc
* custom http headers, support content security policy
* python3 port improvements
* bug fixes: settings synchronization, macos keyboard mapping, etc
* packaging: switch back to ffmpeg system libraries, support GTK3 on macos
* structural improvements: refactoring, fewer synchronized X11 calls, etc


## [2.2] 2017-12-11
* support RFB clients (ie: VNC) with bind-rfb or rfb-upgrade options
* UDP transport (experimental) with bind-udp and udp://host:port URLs
* TCP sockets can be upgrade to Websockets and / or SSL, RFB
* multiple bind options for all socket types supported: tcp, ssl, ws, wss, udp, rfb
* bandwidth-limit option, support for very low bandwidth connections
* detect network performance characteristics
* "xpra sessions" browser tool for both mDNS and local sessions
* support arbitrary resolutions with Xvfb (not with Xdummy yet)
* new OpenGL backends, with support for GTK3 on most platforms
	   and window transparency on MS Windows
* optimized webp encoding, supported in HTML5 client
* uinput virtual pointer device for supporting fine-grained scrolling
* connection strings now support the standard URI format protocol://host:port/
* rencode is now used by default for the initial packet
* skip sending audio packets when inactive
* improved support for non-us keyboard layouts with non-X11 clients
* better modifier key support on Mac OS
* clipboard support with GTK3
* displayfd command line option
* cosmetic system tray menu layout changes
* dbus service for the system-wide proxy server (stub)
* move mmap file to $XDG_RUNTIME_DIR (where applicable)
* password prompt dialog in client
* fixed memory leaks


## [2.1] 2017-07-24
* improve system-wide proxy server, logind support on, socket activation
* new authentication modules:
    * new posix peercred authentication module (used by system-wide proxy)
    * new sqlite authentication module
* split packages for RPM, MS Windows and Mac OS
* digitally signed MS Windows installers
* HTML5 client improvements:
    * file upload support
    * better non-us keyboard and language support
    * safe HMAC authentication over HTTP, re-connection etc
    * more complete window management, (pre-)compression (zlib, brotli)
    * mobile on-screen keyboard
    * audio forwarding for IE
    * remote drag and drop support
* better Multicast DNS support, with a GUI launcher
* improved image depth / deep color handling
* desktop mode can now be resized easily
* any window can be made fullscreen (Shift+F11 to trigger)
* Python3 GTK3 client is now usable
* shutdown the server from the tray menu
* terminate child commands on server shutdown
* macos library updates: [#1501](https://github.com/Xpra-org/xpra/issues/1501), support for virtual desktops
* NVENC SDK version 8 and HEVC support
* Nvidia capture SDK support for fast shadow servers
* shadow servers improvements: show shadow pointer in opengl client
* structural improvements and important bug fixes


## [2.0] 2017-03-17
* dropped support for outdated OS and libraries (long list)
* 64-bit builds for MS Windows and MacOSX
* MS Windows MSYS2 based build system with fully up-to-date libraries
* MS Windows full support for named-pipe connections
* MS Windows and MacOSX support for mmap transfers
* more configurable mmap options to support KVM's ivshmem
* faster HTML5 client, now packaged separately (RPM only)
* clipboard synchronization support for the HTML5 client
* faster window scrolling detection, bandwidth savings
* support more screen bit depths: 8, 16, 24, 30 and 32
* support 10-bit per pixel rendering with the OpenGL client backend
* improved keyboard mapping support when sharing sessions
* faster native turbojpeg codec
* OpenGL enabled by default on more chipsets, with better driver sanity checks
* better handling of tablet input devices (multiple platforms and HTML5 client)
* synchronize Xkb layout group
* support stronger HMAC authentication digest modes
* unit tests are now executed automatically on more platforms
* fix python-lz4 0.9.0 API breakage
* fix html5 visual corruption with scroll paint packets


## [1.0] 2016-12-06
* SSL socket support
* IANA assigned default port 14500 (so specifying the TCP port is now optional)
* include a system-wide proxy server service on our default port, using system authentication
* MS Windows users can start a shadow server from the start menu, which is also accessible via http
* list all local network sessions exposed via mdns using xpra list-mdns
* the proxy servers can start new sessions on demand
* much faster websocket / http server for the HTML5 client, with SSL support
* much improved HTML client, including support for native video decoding
* VNC-like desktop support: "xpra start-desktop"
* pointer grabs using Shift+Menu, keyboard grabs using Control+Menu
* window scrolling detection for much faster compression
* server-side support for 10-bit colours
* better automatic encoding selection and video tuning, support H264 b-frames
* file transfer improvements
* SSH password input support on all platforms in launcher
* client applications can trigger window move and resize with MS Windows and Mac OS X clients
* geometry handling improvements, multi-monitor, fullscreen
* drag and drop support between application windows
* colour management synchronisation (and DPI, workspace, etc)
* the configuration file is now split into multiple logical parts, see /etc/xpra/conf.d
* more configuration options for printers
* clipboard direction restrictions
* webcam improvements: better framerate, device selection menu
* audio codec improvements, new codecs, mpeg audio
* reliable video support for all Debian and Ubuntu versions via private ffmpeg libraries
* use XDG_RUNTIME_DIR if possible, move more files to /run (sockets, log file)
* build and packaging improvements: minify during build: rpm "python2", netbsd v4l
* selinux policy for printing
* Mac OS X PKG installer now sets up ".xpra" file and "xpra:" URL associations
* Mac OS X remote shadow start support (though not all versions are supported)


## [0.17.5] 2016-07-13
* fix webcam skewed picture
* fix size calculations for the 1 pixel bottom edge of video areas
* fix heavy import with side effects for shadow servers
* fix MS Windows shadow servers picture corruption
* fix jpeg wrongly included in auto-refresh encodings
* fix compatibility with ffmpeg 3.1+, warn but don't fail
* fix socket-dir option not being honoured
* fix log dir in commented out Xvfb example
* fix build on some non US locales


## [0.17.4] 2016-06-27
* fix severe regression in damage handling
* fix lossless refresh causing endless loops
* fix path stripping during packaging
* fix password leak in server log file
* fix keyboard layout change handling
* fix openSUSE RPM packaging dependencies
* fix video region API stickiness
* fix application iconification support
* fix XShape performance when scaling
* fix file transfer packet handling and checksum validation
* fix webcam forwarding
* fix spurious pulseaudio exit message on shutdown
* CUDA 8 and Pascal GPU optimization support
* disable webp (black rectangles with some versions)


## [0.17.3] 2016-06-03
* fix logging errors with libyu## [] module (hiding real errors)
* fix memory handling in error cases with x264 encoder
* fix video encoder and colourspace converter leak
* fix rare delta encoding errors
* fix dbus x11 dependency in RPM packaging
* fix dependencies for RHEL 7.0
* fix DPI option miscalculation when used from the client
* fix window aspect ratio hints handling
* fix stripping of temporary build paths
* fix sound subprocess stuck in paused state after an early error
* fix H264 decoding in HTML5 client (disabled for now)
* fix AES padding errors with HTML5 client
* fix spurious import statements in NVENC codecs
* fix crashes in X11 keyboard handling
* fix compatibility with newer GCC versions
* fix OSX and win32 shadow server key mappings
* fix OSX shadow server disconnections with invalid RGB packet data
* fix OSX shadow server crashes with webp
* fix OSX shadow server errors with opus sound codec (disable it)
* fix RGB compression algorithm reported in logging


## [0.17.2] 2016-05-14
* fix suse leap builds (no python3 because os missing dependencies)
* fix aspect-ratio hint handling
* fix sound queue state not getting updated
* fix socket protocol and family information reported
* fix scratchy sound with GStreamer 0.10 (ie: CentOS 6.x)
* fix handling of DPI command line switch client side
* fix printer requests wrongly honoured when printing is disabled
* fix error in websockify error handler
* fix missing matroska container on OSX
* fix Webcam and GTK info scripts on OSX


## [0.17.1] 2016-05-02
* fix SSH error handler
* fix SSH connections with tcsh
* fix launcher GUI with SSH mode
* fix RPM packaging for automatic system installation
* fix / workaround bug in Xorg server 1.18.1 and later
* fix unhelpful systray GDK warning with some desktop environments
* fix duplicate socket paths listed
* fix clipboard issues: timeouts and re-enabling from systray
* fix frame extents warning message to blame the culprit
* fix installation alert message format on Windows XP


## [0.17.0] 2016-04-18
* GStreamer 1.6.x on MS Windows and OSX
* opus is now the default sound codec
* microphone and speaker forwarding no longer cause sound loops
* new sound container formats: matroska, gdp
* much improved shadow servers, especially for OSX and MS Windows
* use newer Plink SSH with Windows Vista onwards
* OSX PKG installer, with file association
* libyu## [] codec for faster colourspace conversion
* NVENC v6, HEVC hardware encoding
* xvid mpeg4 codec
* shadow servers now expose a tray icon and menu
* improved tablet input device support on MS Windows
* improved window geometry handling
* OSX dock clicks now restore existing windows
* OSX clipboard synchronization menu
* new encryption backend: python-cryptography, hardware accelerated AES
* the dbus server can now be started automatically
* support for using /var/run on Linux and multiple sockets
* support for AF_VSOCK virtual networking
* broadcast sessions via mDNS on MS Windows and OSX
* window geometry fixes
* window close event is now configurable, automatically disconnects
* webcam forwarding (limited scope)
* SELinux policy improvements (still incomplete)
* new event based start commands: after connection / on connection
* split file authentication module
* debug logging and message improvements


## [0.16.0] 2015-11-13
* remove more legacy code, cleanups, etc
* switch to GStreamer 1.x on most platforms
* mostly gapless audio playback
* audio-video synchronization
* zero copy memoryview buffers (Python 2.7 and later), safer read-only buffers
* improved vp9 support
* handling of very high client resolutions (8k and above)
* more reliable window positioning and geometry
* add more sanity checks to codecs and csc modules
* network and protocol improvements: safety checks, threading
* encryption improvements: support TCP only encryption, `PKCS#7` padding
* improved printer forwarding
* improved DPI and anti-alias synchronization and handling (incomplete)
* better multi-monitor support
* support for screen capture tools (disabled by default)
* automatic desktop scaling to save bandwidth and CPU (upscale on client)
* support remote SSH start without specifying a display
* support multiple socket directories
* lz4 faster modes with automatic speed tuning
* server file upload from system tray
* new subcommand: "xpra showconfig"
* option to select a specific clipboard to synchronize with (MS Windows only)
* faster OpenGL screen updates: group screen updates
* dbus server for easier runtime control
* replace calls to setxkbmap with native X11 API
* XShm for override-redirect windows and shadow servers
* faster X11 shadow servers
* XShape forwarding for X11 clients
* improved logging and debugging tools, fault injection
* more robust error handling and recovery from client errors
* NVENC support for MS Windows shadow servers


## [0.15.8] 2015-11-10
* fix missing files from build clean target
* fix unnecessary auto-refresh events
* fix x265 encoder
* fix libvpx bitrate calculations, reduce logging spam
* fix validation of mmap security token
* fix handling of file transfers before authentication (disallowed)
* fix handling of requests to open files (honour command line / config flag)
* fix MS Windows multiple monitor bug (when primary monitor is re-added)
* fix video encoding automatic selection for encoders that accept RGB directly
* fix the session info sound graphs when sound stops
* fix RPM packaging of the cups backend
* fix the speed and quality values reported to the clients for x264 encoder
* fix OSX El Capitan sound compatibility issue
* fix codec import error handler
* fix compatibility with Python Pillow 3.0.0 (logging issue)
* fix support for Ubuntu Vivid (Xorg still unusable)
* fix batch delay heuristics during resizing and queue overload
* fix "always batch" mode
* fix missing network-send-speed accounting
* fix error in override redirect window geometry handling
* fix invalid error logging call
* fix error in XSettings handling causing connection failures
* fix race condition causing corrupted video streams
* fix unnecessary double refresh on client decoding error
* fix encoding bug triggered when dependencies are missing
* fix window size hints handling
* support Xorg location and arguments required by Arch Linux
* improved lz4 version detection workaround code
* support Xft/DPI
* safer OSX power event handling code
* workaround clients supplying a password when none is required
* log OpenGL driver information
* clamp desktop size to the maximum screen size
* avoid potential errors with bytes-per-pixel confusion with rgb modes
* disable workspace support by default (compatibility issues with some WM)
* always watch for property changes, even without workspace support
* workaround clients supplying a password when none is required
* export shadow servers flag
* run the window opengl cleanup code


## [0.15.7] 2015-10-13
* fix inband info requests
* fix monitor hotplugging workaround code
* fix OSX menus which should not be shown
* fix cursor lookup by name in local theme
* fix max-size support on MS Windows
* fix max-size handling for windows without any constraints (all platforms)
* fix repaint when using the magic key to toggle window borders
* fix iconification handling
* fix connection error when there are XSettings already present
* fix parsing of invalid display structures
* fix video region detection after resize
* fix vpx quality setting
* fix cursor crashes on Ubuntu
* don't show opengl toggle menu if opengl is not supported
* add new common X11 modes (4k, 5k, etc)
* add missing logging category for x265 (fixes warnings on start)


## [0.15.6] 2015-09-13
* fix missing auth argument with Xdummy
* fix oversize print jobs causing disconnections
* fix server-side copy of the client's desktop dimensions
* fix X11 client errors when window managers clear the window state
* fix spurious warnings if X11 desktop properties are not present
* fix server failing to report sound failures (dangling process)
* fix paint errors with cairo backing
* fix window positioning issues when monitors are added (osx and win32)


## [0.15.5] 2015-08-19
* fix encryption not enabled when pycrypto is missing: error out
* fix encryption information leak, free network packets after use
* fix authentication plugins
* fix latency with many sound codecs: vorbis, flac, opus, speex
* fix the desktop naming code (worked by accident)
* fix OpenGL errors with windows too big for the driver
* fix some subcommands when encryption is enabled
* fix spurious errors on closed connections
* fix incorrect colours using CSC Cython fallback module
* fix size limits on Cython fallback module
* fix some invalid Xorg dummy modelines
* fix aspect ratio not honoured and associated warnings
* fix printing file compression
* fix errors in packet layer accounting
* fix regression in python-lz4 version guessing code
* fix RPM packaging: prefer our private libraries to the system ones
* fix pactl output parsing
* fix error on Posix desktop environments without virtual desktops
* fix unlikely connection closing errors
* fix value overflows when unpremultiplying alpha channel
* ship a default configuration file on OSX
* try not to downscale windows from shadow servers
* add vpx-xpra to the RPM dependency list so we get VPX 1.9 support
* make it possible to generate the EXE installer without running it
* allow the user to remove some atoms from _NET_SUPPORTED
* show maximum OpenGL texture size in diagnostics and bug reports
* minor python3 fixes


## [0.15.4] 2015-08-02
* fix delta compression errors
* fix VP8 and VP9 performance when speed command line option is used
* fix application deadlocks on exit
* fix NVENC on cards with over 4GB of RAM
* fix csc Cython red and blue colours swapped on little endian systems
* fix byteswapping fallback code
* fix cleanup error on MS Windows, preventing process termination
* fix pulseaudio device count reported
* fix timer warnings in GTK2 notifier (mostly used on OSX)
* fix sound communication errors not causing subprocess termination
* fix Xorg path detection for Fedora 22 onwards
* fix invalid list of output colorspaces with x264
* fix bug report tool window, so it can be used more than once
* fix bug report tool log file error with Vista onwards
* fix bug report screenshots on MS Windows with multiple screens
* fix shadow mode on MS Windows with multiple screens
* fix OpenCL csc module with Python3
* fix OpenCL platform selection override
* fix Python3 Pillow encoding level (must be an integer)
* fix capture of subprocesses return code
* fix Xvfb dependencies for Ubuntu
* fix ldconfig warning on Debian and Ubuntu
* fix warnings with X11 desktop environments without virtual desktops
* fix use of deprecated ffmpeg enum names
* fix client error if built without webp support
* include the CUDA pre-compiled kernels on Debian / Ubuntu (NVENC)
* packaging fixes for printing on Debian / Ubuntu
* updated dependency list for Debian and Ubuntu distros
* don't require a nonsensical display name on OSX and win32
* safer x264 API initialization call
* safer OpenGL platform checks (prevents crashes with wine)
* safer NVENC API call
* safer lz4 version checking code
* workaround invalid "help" options in config files
* ensure any client decoding errors cause a window refresh
* MS Windows build environment cleanup
* Fedora: update PyOpenGL package dependency


## [0.15.3] 2015-07-07
* fix invalid X11 atom
* fix unhandled failure code from libav
* fix default socket permissions when config file is missing
* fix error handling for missing cuda kernels
* fix OpenGL paint early errors
* fix "print" control command with multiple clients
* skip sending invalid packet to client for the "name" control command
* more helpful dpi warning
* support connecting to named unix domain sockets
* OpenGL option can force enable despite platform checks
* replace unsafe deprecated API call in HTML5 client
* more reliable and clean shutdown of connections and threads
* log internal system failures as errors


## [0.15.2] 2015-06-28
* fix rgb encodings can use speed setting
* fix propagation of dynamic attributes for OR windows
* fix invalid warnings in parsing client connection options
* fix handling of the window decorations flag
* fix missing lock around Python logger callback
* fix size-hints with shadow servers
* fix max-size switch
* fix sound process communication errors during failures
* fix invalid options shown in default config file
* add missing file to clean list
* skip unnecessary workarounds with GTK3 client
* cleaner thread cleanup on server exit
* use the safer and slower code with non-OpenGL clients


## [0.15.1] 2015-06-18
* fix window transparency
* fix displayfd Xorg version check: require version 1.13
* fix GUI debug script on OSX
* fix typo in list of supported X11 atoms
* fix exit-with-children: support sharing mode
* fix html option for client only builds
* fix pulseaudio not killed on exit on Ubuntu
* fix signal leak when client disconnects
* include shared mime info file mapping
* blacklist Ubuntu Vivid, which broke Xdummy, again
* don't reject clients providing a password when none is expected
* raise maximum clipboard requests per second to 20
* remove old VP9 performance warnings


## [0.15.0] 2015-04-28
* printer forwarding
* functional HTML5 client
* add session idle timeout switch
* add html command line switch for easily setting up an HTML5 xpra server
* dropped support for Python 2.5 and older, allowing many code cleanups and improvements
* include manual in html format with MS Windows and OSX builds
* add option to control socket permissions (easier setup of containers)
* client log output forwarding to the server
* fixed workarea coordinates detection for MS Windows clients
* improved video region detection and handling
* more complete support for window states (keep above, below, sticky, etc..) and general window manager responsibilities
* allow environment variables passed to children to be specified in the config files
* faster reformatting of window pixels before compression stage
* support multiple delta regions and expire them (better compression)
* allow new child commands to be started on the fly, also from the client's system tray (disabled by default)
* detect mismatch between some codecs and their shared library dependencies
* NVENC SDK support for versions 4 and 5, YUV444 and lossless mode
* libvpx support for vp9 lossless mode, much improved performance tuning
* add support for child commands that do not interfere with "exit-with-children"
* add scaling command line and config file switch for controlling automatic scaling aggressiveness
* sound processing is now done in a separate process (lower latency, and more reliable)
* add more control over sound command line options, so sound can start disabled and still be turned on manually later
* add command line option for selecting the sound source (pulseaudio, alsa, etc)
* show sound bandwidth usage
* better window icon forwarding, especially for non X11 clients
* optimized OpenGL rendering for X11 clients
* handle screen update storms better
* window group-leader support on MS Windows (correct window grouping in the task bar)
* GTK3 port improvements (still work in progress)
* added unit tests which are run automatically during packaging
* more detailed information in xpra info (cursor, CPU, connection, etc)
* more detailed bug report information
* more minimal MS Windows and OSX builds


## [0.14.0] 2014-08-14
* support for lzo compression
* support for choosing the compressors enabled (lz4, lzo, zlib)
* support for choosing the packet encoders enabled (bencode, rencode, yaml)
* support for choosing the video decoders enabled
* built in bug report tool, capable of collecting debug information
* automatic display selection using Xorg "-displayfd"
* better video region support, increased quality for non-video regions
* more reliable exit and cleanup code, hooks and notifications
* prevent SSH timeouts on login password or passphrase input
* automatic launch the correct tool on MS Windows
* OSX: may use the Application Services folder for a global configuration
* removed python-webm, we now use the native cython codec only
* OpenCL: warn when AMD icd is present (causes problems with signals)
* better avahi mDNS error reporting
* better clipboard compression support
* better packet level network tuning
* support for input methods
* xpra info cleanups and improvements (show children, more versions, etc)
* integrated keyboard layout detection on *nix
* upgrade and shadow now ignore start child
* improved automatic encoding selection, also faster
* keyboard layout selection via system tray on *nix
* more Cython compile time optimizations
* some focus issues fixed


## [0.13.9] 2014-08-13
* fix clipboard on OSX
* fix remote ssh start with start-child issues
* use secure "compare_digest" if available
* fix crashes in codec cleanup
* fix video encoding fallback code
* fix fakeXinerama setup wrongly skipped in some cases
* fix connection failures with large screens and uncompressed RGB
* fix Ubuntu trustyi Xvfb configuration
* fix clipboard errors with no data
* fix opencl platform initialization errors


## [0.13.8] 2014-08-06
* fix server early exit when pulseaudio terminates
* fix SELinux static codec library label (make it persistent)
* fix missed auto-refresh when batching
* fix disabled clipboard packets coming through
* fix cleaner client connection shutdown sequence and exit code
* fix resource leak on connection error
* fix potential bug in fallback encoding selection
* fix deadlock on worker race it was meant to prevent
* fix remote ssh server start timeout
* fix avahi double free on exit
* fix png and jpeg painting via gdk pixbuf (when PIL is missing)
* fix webp refresh loops
* honour lz4-off environment variable
* fix proxy handling of raw RGB data for large screen sizes
* fix potential error from missing data in client packets


## [0.13.7] 2014-07-10
* fix x11 server pixmap memory leak
* fix speed and quality values range (1 to 100)
* fix nvenc device allocation errors
* fix unnecessary refreshes with nvenc
* fix "initenv" compatibility with older servers
* don't start child when upgrading or shadowing


## [0.13.6] 2014-06-14
* fix compatibility older versions of pygtk (centos5)
* fix compatibility with python 2.4 (centos5)
* fix AltGr workaround with win32 clients
* fix some missing keys with `fr` keyboard layout (win32)
* fix installation on systems without python-glib (centos5)
* fix Xorg version detection for Fedora rawhide


v0.13.5-3 2014-06-14
* re-fix opengl compatibility


## [0.13.5] 2014-06-13
* fix use correct dimensions when evaluating video
* fix invalid latency statistics recording
* fix auto-refresh wrongly cancelled
* fix connection via nested ssh commands
* fix statically linked builds of swscale codec
* fix system tray icons when upgrading server
* fix opengl compatibility with older libraries
* fix ssh connection with shells not starting in home directory
* fix keyboard layout change forwarding


## [0.13.4] 2014-06-10
* fix numeric keypad period key mapping on some non-us keyboards
* fix client launcher GUI on OSX
* fix remote ssh start with clean user account
* fix remote shadow start with automatic display selection
* fix avoid scaling during resize
* fix changes of speed and quality via xpra control (make it stick)
* fix xpra info global batch statistics
* fix focus issue with some applications
* fix batch delay use


## [0.13.3] 2014-06-05
* fix xpra upgrade
* fix xpra control error handling
* fix window refresh on inactive workspace
* fix slow cursor updates
* fix error in rgb strict mode
* add missing x11 server type information


## [0.13.2] 2014-06-01
* fix painting of forwarded tray
* fix initial window workspace
* fix launcher with debug option in config file
* fix compilation of x265 encoder
* fix infinite recursion in cython csc module
* don't include sound utilities when building without sound


## [0.13.1] 2014-05-28
* honour lossless encodings
* fix avcodec2 build for Debian jessie and sid
* fix pam authentication module
* fix proxy server launched without a display
* fix xpra info data format (wrong prefix)
* fix transparency with png/L mode
* fix loss of transparency when toggling OpenGL
* fix re-stride code for compatibility with ancient clients
* fix timer reference leak causing some warnings


## [0.13.0] 2014-05-22
* Python3 / GTK3 client support
* NVENC module included in binary builds
* support for enhanced dummy driver with DPI option
* better build system with features auto-detection
* removed unsupported CUDA csc module
* improved buffer support
* faster webp encoder
* improved automatic encoding selection
* support running MS Windows installer under wine
* support for window opacity forwarding
* fix password mode in launcher
* edge resistance for automatic image downscaling
* increased default memory allocation of the dummy driver
* more detailed version information and tools
* stricter handling of server supplied values


## [0.12.6] 2014-05-16
* fix invalid pixel buffer size causing encoding failures
* fix auto-refresh infinite loop, and honour refresh quality
* fix sound sink with older versions of GStreamer plugins
* fix Qt applications crashes caused by a newline in xsettings..
* fix error with graphics drivers only supporting OpenGL 2.x only
* fix OpenGL crash on OSX with the Intel driver (now blacklisted)
* fix global menu entry text on OSX
* fix error in cairo backing cleanup
* fix RGB pixel data buffer size (re-stride as needed)
* avoid buggy swscale 2.1.0 on Ubuntu


## [0.12.5] 2014-05-03
* fix error when clients supply invalid screen dimensions
* fix MS Windows build without ffmpeg
* fix cairo backing alternative
* fix keyboard and sound test tools initialization and cleanup
* fix gcc version test used for enabling sanitizer build options
* fix exception handling in client when called from the launcher
* fix liba## [] dependencies for Debian and Ubuntu builds


## [0.12.4] 2014-04-23
* fix xpra shadow subcommand
* fix xpra shadow keyboard mapping support for non-posix clients
* avoid Xorg dummy warning in log


## [0.12.3] 2014-04-09
* fix mispostioned windows
* fix quickly disappearing windows (often menus)
* fix server errors when closing windows
* fix NVENC server initialization crash with driver version mismatch
* fix rare invalid memory read with XShm
* fix webp decoder leak
* fix memory leak on client disconnection
* fix focus errors if windows disappear
* fix mmap errors on window close
* fix incorrect x264 encoder speed reported via "xpra info"
* fix potential use of mmap as an invalid fallback for video encoding
* fix logging errors in debug mode
* fix timer expired warning


## [0.12.2] 2014-03-30
* fix switching to RGB encoding via client tray
* fix remote server start via SSH
* fix workspace change detection causing slow screen updates


## [0.12.1] 2014-03-27
* fix 32-bit server timestamps
* fix client PNG handling on installations without PIL / Pillow


## [0.12.0] 2014-03-23
* NVENC support for YUV444 mode, support for automatic bitrate tuning
* NVENC and CUDA load balancing for multiple cards
* proxy encoding: ability to encode on proxy server
* fix fullscreen on multiple monitors via fakeXinerama
* OpenGL rendering improvements (for transparent windows, etc)
* support window grabs (drop down menus, etc)
* support specifying the SSH port number more easily
* enabled TCP_NODELAY socket option by default (lower latency)
* add ability to easily select video encoders and csc modules
* add local unix domain socket support to proxy server instances
* add "xpra control" commands to control encoding speed and quality
* improved handling of window resizing
* improved compatibility with command line tools (xdotool, wmctrl)
* ensure windows on other workspaces do not waste bandwidth
* ensure iconified windows do not waste bandwidth
* ensure maximized and fullscreen windows are prioritised
* ensure we reset xsettings when client disconnects
* better bandwidth utilization of jittery connections
* faster network code (larger receive buffers)
* better automatic encoding selection for smaller regions
* improved command line options (add ability to enable options which are disabled in the config file)
* trimmed all the ugly PyOpenGL warnings on startup
* much improved logging and debugging tools
* make it easier to distinguish xpra windows from local windows (border command line option)
* improved build system: smaller and more correct build output (much smaller OSX images)
* improved MS Windows command wrappers
* improved MS Windows (un)installer checks
* automatically stop remote shadow servers when client disconnects
* MS Windows and OSX build updates: updated Pillow, lz4, etc


## [0.11.6] 2014-03-18
* correct fix for system tray forwarding


## [0.11.5] 2014-03-18
* fix "xpra info" with bencoder
* ensure we re-sanitize window size hints when they change
* workaround applications with nonsensical size hints (ie: handbrake)
* fix 32-bit painting with GTK pixbuf loader (when PIL is not installed or disabled)
* fix system tray forwarding geometry issues
* fix workspace restore
* fix compilation warning
* remove spurious cursor warnings


## [0.11.4] 2014-02-29
* fix NVENC GPU memory leak
* fix video compatibility with ancient clients
* fix vpx decoding in ffmpeg decoders
* fix transparent system tray image with RGB encoding
* fix client crashes with system tray forwarding
* fix webp codec loader error handler


## [0.11.3] 2014-02-14
* fix compatibility with ancient versions of GTK
* fix crashes with malformed socket names
* fix server builds without client modules
* honour mdns flag set in config file
* blacklist VMware OpenGL driver which causes client crashes
* ensure all "control" subcommands run in UI thread


## [0.11.2] 2014-01-29
* fix Cython 0.20 compatibility
* fix OpenGL pixel upload alignment code
* fix xpra command line help page tokens
* fix compatibility with old versions of the python glib library


## [0.11.1] 2014-01-24
* fix compatibility with old/unsupported servers
* fix shadow mode
* fix paint issue with transparent tooltips on OSX and MS Windows
* fix pixel format typo in OpenGL logging


## [0.11.0] 2014-01-20
* NVENC hardware h264 encoding acceleration
* OpenCL and CUDA colourspace conversion acceleration
* proxy server mode for serving multiple sessions through one port
* support for sharing a TCP port with a web server
* server control command for modifying settings at runtime
* server exit command, which leaves Xvfb running
* publish session via mDNS
* faster OSX shadow server
* OSX client two-way clipboard support
* OSX keyboard improvements, swap command and control keys
* support for transparency with OpenGL window rendering
* support for transparency with 8-bit PNG modes
* support for more authentication mechanisms
* support remote shadow start via ssh
* support faster lz4 compression
* faster bencoder, rewritten in Cython
* builtin fallback colourspace conversion module
* real time frame latency graphs
* improved system tray forwarding support and native integration
* removed most of the Cython/C code duplication
* stricter and safer value parsing
* more detailed status information via UI and "xpra info"
* experimental HTML5 client
* drop non xpra clients with a more friendly response
* handle non-ASCII characters in output on MS Windows
* libvpx 1.3 and ffmpeg 2.1.3 for OSX, MS Windows and static builds


## [0.10.12] 2014-01-14
* fix missing auto-refresh with lossy colourspace conversion
* fix spurious warning from Nvidia OpenGL driver
* fix OpenGL client crash with some drivers (ie: VirtualBox)
* fix crash in bencoder caused by empty data to encode
* fix OSX popup focus issue
* fix ffmpeg2 h264 decoding (ie: Fedora 20+)
* big warnings about webp leaking memory
* generated debuginfo RPMs


## [0.10.11] 2014-01-07
* fix popup windows focus issue
* fix "xpra upgrade" subcommand
* fix server backtrace in error handler
* restore server target information in tray tooltip
* fix bencoder error with no-windows switch (missing encoding)
* add support for RGBX pixel format required by some clients
* avoid ffmpeg "data is not aligned" warning on client
* ensure x264 encoding is supported on MS Windows shadow servers


## [0.10.10] 2013-12-04
* fix focus regression
* fix MS Windows clipboard copy including null byte
* fix h264 decoding with old versions of avcodec
* fix potential invalid read past the end of the buffer
* fix static vpx build arguments
* fix RGB modes exposed for transparent windows
* fix crash on clipboard loops: detect and disable clipboard
* support for ffmpeg version 2.x
* support for video encoding of windows bigger than 4k
* support video encoders that re-start the stream
* fix crash in decoding error path
* forward compatibility with namespace changes
* forward compatibility with the new generic encoding names


## [0.10.9] 2013-11-05
* fix h264 decoding of padded images
* fix plain RGB encoding with very old clients
* fix "xpra info" error when old clients are connected
* remove warning when "help" is specified as encoding


## [0.10.8] 2013-10-22
* fix misapplied patch breaking all windows with transparency


## [0.10.7] 2013-10-22
* fix client crash on Linux with AMD cards and fglrx driver
* fix MS Windows tray forwarding (was broken by fix from 0.10.6)
* fix missing WM_CLASS on X11 clients
* fix Mac OSX shadow server
* fix "xpra info" on shadow servers
* add usable 1366x768 dummy resolution


## [0.10.6] 2013-10-15
* fix window titles reverting to "unknown host"
* fix tray forwarding bug causing client disconnections
* replace previous rencode fix with warning


## [0.10.5] 2013-10-10
* fix client time out when the initial connection fails
* fix shadow mode
* fix connection failures when some system information is missing
* fix client disconnection requests
* fix encryption cipher error messages
* fix client errors when some features are disabled
* fix potential rencode bug with unhandled data types
* error out if the client requests authentication and none is available


## [0.10.4] 2013-09-10
* fix modifier key handling (was more noticeable with MS Windows clients)
* fix auto-refresh


## [0.10.3] 2013-09-06
* fix transient windows with no parent
* fix metadata updates handling (maximize, etc)


## [0.10.2] 2013-08-29
* fix connection error with unicode user name
* fix vpx compilation warning
* fix python 2.4 compatibility
* fix handling of scaling attribute via environment override
* build fix: ensure all builds include source information


## [0.10.1] 2013-08-20
* fix avcodec buffer pointer errors on some 32-bit Linux
* fix invalid time conversion
* fix OpenGL scaling with fractions
* compilation fix for some newer versions of libav
* disable OpenGL on Ubuntu 12.04 and earlier (non functional)
* honour scaling at high quality settings
* add ability to disable transparency via environment variable
* silence PyOpenGL warnings we can do nothing about
* fix CentOS 6.3 packaging dependencies


## [0.10.0] 2013-08-13
* performance: X11 shared memory (XShm) pixels transfers
* performance: zero-copy window pixels to picture encoders
* performance: zero copy decoded pixels to window (but not with OpenGL..)
* performance: multithreaded x264 encoding and decoding
* support for speed tuning (latency vs bandwidth) with more encodings (png, jpeg, rgb)
* support for grayscale and palette based png encoding
* support for window and tray transparency
* support webp lossless
* support x264's "ultrafast" preset
* support forwarding of group-leader application window information
* prevent slow encoding from creating backlogs
* OpenGL accelerated client rendering enabled by default wherever supported
* register as a generic URL handler
* fullscreen toggle support
* stricter Cython code
* better handling of sound buffering and overruns
* better OSX support, handle UI stalls more gracefully, system trays
* experimental support for a Qt based client
* support for different window layouts with custom widgets
* basic support of OSX shadow servers
* don't try to synchronize with clipboards that do not exist (for shadow servers mostly)
* refactoring: move features and components to submodules
* refactoring: split X11 bindings from pure gtk code
* refactoring: codecs split encoding and decoding side
* refactoring: move more common code to utility classes
* refactoring: remove direct dependency on gobject in many places
* refactoring: platform code better separated
* refactoring: move wimpiggy inside xpra, delete parti
* export and expose more version information (x264/vpx/webp/PIL, OpenGL..)
* export compiler information with build (Cython, C compiler, etc)
* export much more debugging information about system state and statistics
* simplify non-UI subcommands and their packets, also use rencode ("xpra info", "xpra version", etc)


## [0.9.8] 2013-07-29
* fix client workarea size change detection (again)
* fix crashes handling info requests
* fix Ubuntu raring clients: must use Xvfb
* fix server hangs due to sound cleanup deadlock
* use lockless window video decoder cleanup (much faster)
* speedup server startup when no XAUTHORITY file exists yet


## [0.9.7] 2013-07-16
* fix error in sound cleanup code
* fix network threads accounting
* fix missing window icons
* fix client availability of remote session start feature


## [0.9.6] 2013-06-30
* fix client exit lockups on MS Windows
* fix lost clicks on some popup menus (mostly with MS Windows clients)
* fix client workarea size change detection
* fix reading of unique "machine-id" on posix
* fix window reference leak for windows we fail to manage
* fix compatibility with pillow (PIL fork)
* fix session-info window graphs jumping (smoother motion)
* fix webp loading code for non-Linux posix systems
* fix window group-leader attribute setting
* fix man page indentation
* fix variable test vs use (correctness only)
* static binary builds updates: Python 2.7.5, flac 1.3, PyOpenGL 3.1, numpy 1.7.1, webp 0.3.1, liba## [] 9.7
* static binary builds switched to using pillow instead of PIL
* forward compatibility with future "xpra info" namespace changes


## [0.9.5] 2013-06-06
* fix auto-refresh: don't refresh unnecessarily
* fix wrong initial timeout when ssh takes a long time to connect
* fix client monitor/resolution size change detection
* fix attributes reported to clients when encoding overrides are used
* Gentoo ebuild uses virtual to allow one to choose pillow or PIL


## [0.9.4] 2013-05-27
* revert cursor scaling fix which broke other applications
* fix auto refresh mis-firing
* fix type (atom) of the X11 visual property we expose


## [0.9.3] 2013-05-20
* fix clipboard for *nix clients
* fix selection timestamp parsing
* fix crash due to logging code location
* fix pixel area request dimensions for lossless edges
* fix advertised tray visual property
* fix cursors are too small with some applications
* fix crash when low level debug code is enabled
* reset cursors when disabling cursor forwarding
* workaround invalid window size hints


## [0.9.2] 2013-05-13
* fix double error when loading build information (missing about dialog)
* fix and simplify build "clean" subcommand
* fix OpenGL rendering alignment for padded rowstrides case
* fix potential double error when tray initialization fails
* fix window static properties usage


## [0.9.1] 2013-05-08
* honour initial client window's requested position
* fix for hidden appindicator
* fix string formatting error in non-cython fallback math code
* fix error if ping packets fail from the start
* fix for windows without a valid window-type (ie: shadows)
* fix OpenGL missing required feature detection (and add debug)
* add required CentOS RPM libXfont dependency
* tag our /etc configuration files in RPM spec file


## [0.9.0] 2013-04-25
* fix focus problems with old Xvfb display servers
* fix RPM SELinux labelling of static codec builds (CentOS)
* fix CentOS 5.x compatibility
* fix Python 2.4 and 2.5 compatibility (many)
* fix clipboard with MS Windows clients
* fix failed server upgrades killing the virtual display
* fix screenshot command with "OR" windows
* fix support for "OR" windows that move and resize
* IP## [6] server support
* support for many more audio codecs: flac, opus, wavpack, wav, speex
* support starting remote sessions with "xpra start"
* support for Xdummy with CentOS 6.4 onwards
* add --log-file command line option
* add clipboard regex string filtering
* add clipboard transfer in progress animation via system tray
* detect broken/slow connections and temporarily grey out windows
* reduce regular packet header sizes using numeric lookup tables
* allow more options in xpra config and launcher files
* MS Windows fixes for Caps Lock and Num Lock synchronization
* MS Windows and OSX builds trim the amount of GStreamer plugins shipped
* MS Windows, OSX and static codec builds (Ubuntu Lucid, Debian Squeeze) updated to liba## [] 9.4
* MS Windows and OSX builds updated to use Python 2.7.4
* MS Windows library updates (pyasn1, numpy, webp)
* OSX library updates (mpfr, x264, pyasn1, numpy, webp), fixed sound packaging
* safer test for windows to ignore (window IDs starts at 1 again)
* expose more version and statistical data via xpra info
* improved OpenGL client rendering (still disabled by default)
* upgrade to rencode 1.0.2


## [0.8.8] 2013-03-07
* fix server deadlock on dead connections
* fix compatibility with older versions of Python
* fix sound capture script usage via command line
* fix screen number preserve code
* fix error in logs in shadow mode


## [0.8.7] 2013-02-27
* fix x264 crash with older versions of libav
* fix 32-bit builds breakage introduce by python2.4 fix in 0.8.6
* fix missing sound forwarding when using the GUI launcher
* fix microphone forwarding errors
* fix client window properties store
* fix first workspace not preserved and other workspace issues
* fix GStreamer-Info.exe output
* avoid creating unused hidden "group" windows on MS Windows clients


## [0.8.6] 2013-02-22
* fix launcher on MS Windows, better SSH support
* fix python2.4 compatibility in icon grabbing code
* fix liba## [] compatibility on MS Windows with VisualStudio
* fix exit message location
* prevent invalid Python bindings version from being included in the MS Windows installer


## [0.8.5] 2013-02-17
* fix server crash with transient windows


## [0.8.4] 2013-02-13
* fix hello packet encoding bug
* fix colours in launcher and session-info windows


## [0.8.3] 2013-02-12
* Python 2.4 compatibility fixes (CentOS 5.x)
* fix static builds of vpx and x264


## [0.8.2] 2013-02-10
* fix liba## [] uninitialized structure crash
* fix warning on installations without sound libraries
* fix warning when pulseaudio utils are not installed
* fix delta compression race
* fix the return of some ghost windows
* stop pulseaudio on exit, warn if it fails to start
* re-enable system tray forwarding, fix location conflicts
* osx fixes: encodings wrongly grayed out
* osx features: add sound and speed menus
* remove spurious "too many receivers" warnings


## [0.8.1] 2013-02-04
* fix server daemonize on some platforms
* fix server SSH support on platforms with old versions of glib
* fix "xpra upgrade" closing applications
* fix detection of almost-lossless frames with x264
* fix starting of a duplicate pulseaudio server on upgrade
* fix debian packaging: lint warnings, add missing sound dependencies
* fix compatibility with older versions of pulseaudio (pactl)
* fix session-info window when a tray is being forwarded
* remove warning on builds with limited encoding support
* disable tray forwarding by default as it causes problems with some apps
* rename "Quality" to "Min Quality" in tray menu
* update to Cython 0.18 for binary builds
* fix rpm packaging: remove unusable modules


## [0.8.0] 2013-01-31
* fix modal windows support
* fix default mouse cursor: now uses the client's default cursor
* fix "double-apple" in menu on OSX
* fix short-lived windows: avoid doing unnecessary work, avoid re-registering handlers
* fix limit the number of raw packets per client to prevent DoS via memory exhaustion
* fix authentication: ensure salt is per connection
* fix for ubuntu global application menus
* fix proxy handling of deadly signals
* fix pixel queue size calculations used for performance tuning decisions
* fix ^C exit on MS Windows: ensure we do cleanup the system tray on exit
* edge resistance for colourspace conversion level changes to prevent yoyo effect
* more aggressive picture quality tuning
* better CPU utilization
* new command line options and tray menu to trade latency for bandwidth
* x264 disable unnecessary I-frames and avoid IDR frames
* performance and latency optimizations in critical sections
* avoid server loops: prevent the client from connecting to itself
* group windows according to the remote application they belong to
* sound forwarding (initial code, high latency)
* faster and more reliable client and server exit (from signal or otherwise)
* SSH support on MS Windows
* "xpra shadow" mode to clone an existing X11 display (compositors not supported yet)
* support for delta pixels mode (most useful for shadow mode)
* avoid warnings and X11 errors with the screenshot command
* better mouse cursor support: send cursors by name so their size matches the client's settings
* mitigate bandwidth eating cursor change storms: introduce simple cursor update batching
* support system tray icon forwarding (limited)
* preserve window workspace
* AES packet encryption for TCP mode (without key secure exchange for now)
* launcher entry box for username in SSH mode
* launcher improvements: highlight the password field if needed, prevent warnings, etc
* better window manager specification compatibility (for broken applications or toolkits)
* use lossless encoders more aggressively when possible
* new x264 tuning options: profiles to use and thresholds
* better detection of dead server sockets: retry and remove them if needed
* improved session information dialog and graphs
* more detailed hierarchical per-window details via "xpra info"
* send window icons in dedicated compressed packet (smaller new-window packets, faster)
* detect overly large main packets
* partial/initial Java/AWT keyboard support
* `py2exe`, `ebuild` and `distutils` improvements: faster and cleaner builds, discarding unwanted modules
* OSX and MS Windows build updates: newer `py2app`, `gtk-mac-bundler`, `pywin32` and support libraries
* OSX command line path fix
* updated libx264 and liba## [] on OSX
* updated Cython to 0.17.4 for all binary builds


## [0.7.8] 2013-01-15
* fix xsettings integer parsing
* fix 'quality' command line option availability check
* workaround Ubuntu's global menus
* better compatibility with old servers: don't send new xsettings format
* avoid logging for normal "clipboard is disabled" case


## [0.7.7] 2013-01-03
* fix quality menu
* fix for clients not using rencoder (ie: Java, Android..)
* fix pixel queue size accounting


## [0.7.6] 2013-01-01
* fix tray options meant to be unusable until connected
* fix auto refresh delay
* fix missing first bell in error case
* fix potential DoS in client disconnection accounting
* fix network calls coming from wrong thread in error case
* fix unlikely locking issue and reduce lock hold time
* fix disconnect all connected clients cleanly
* fix clipboard flag handling
* fix Mac OSX path with spaces handling
* fix server minimum window dimensions with video encoders
* don't bother trying to auto-refresh in lossless modes


## [0.7.5] 2012-12-06
* fix crash on empty keysym
* fix potential division by zero
* fix network queue access from invalid thread
* fix cleanup code on upgrade corner cases
* fix keyboard layout change detection
* try harder to apply keymaps when the number of free keycodes are limited


## [0.7.4] 2012-11-16
* avoid crash with configure events on windows being destroyed
* fix 100% cpu usage with python2.6 server started with no child


## [0.7.3] 2012-11-08
* fix crash with unknown X11 keysyms
* avoid error with focus being given to a destroyed window
* honour window aspect ratio


## [0.7.2] 2012-11-07
* fix version string hiding ssh password prompt
* fix focus handling for applications setting `XWMHints.input` to False (ie: Java)
* fix ssh shared connection mode: do not kill it on Ctrl-C
* fix sanitization of aspect ratio hints
* fix undefined variable exception in window setup/cleanup code
* fix undefined variable exception in window damage code
* fix dimensions used for calculating the optimal picture encoding
* reduce Xdummy memory usage by limiting to lower maximum resolutions


## [0.7.1] 2012-10-21
* fix division by zero in graphs causing displayed information to stall
* fix multiple tray shown when using the launcher and password authentication fails
* fix override redirect windows cleanup code
* fix keyboard mapping for AltGr with old versions of X11 server
* fix for Mac OSX zero keycode (letter 'a')
* fix for invalid modifiers: try harder to apply valid mappings
* fix gtk import warning with text clients (xpra version, xpra info)


## [0.7.0] 2012-10-08
* Mac DMG client download
* Android APK download
* fix "AltGr" key handling with MS Windows clients (and others)
* fix crash with x264 encoding
* fix crash with fast disappearing tooltip windows
* avoid storing password in a file when using the launcher (except on MS Windows)
* many latency fixes and improvements: lower latency, better line congestion handling, etc
* lower client latency: decompress pictures in a dedicated thread (including rgb24+zlib)
* better launcher command feedback
* better automatic compression heuristics
* support for Xdummy on platforms with only a suid binary installed
* support for 'webp' lossy picture encoding (better and faster than jpeg)
* support fixed picture quality with x264, webp and jpeg (via command line and tray menu)
* support for multiple "start-child" options in config files or command line
* more reliable auto-refresh
* performance optimizations: caching results, avoid unnecessary video encoder re-initialization
* faster re-connection (skip keyboard re-configuration)
* better isolation of the virtual display process and child processes
* show performance statistics graphs on session info dialog (click to save)
* start with compression enabled, even for initial packet
* show more version and client information in logs and via "xpra info"
* client launcher improvements: prevent logging conflict, add version info
* large source layout cleanup, compilation warnings fixed


## [0.6.4] 2012-10-05
* fix bencoder to properly handle dicts with non-string keys
* fix swscale bug with windows that are too small by switch encoding
* fix locking of video encoder resizing leading to missing video frames
* fix crash with compression turned off: fix unicode encoding
* fix lack of locking sometimes causing errors with "xpra info"
* fix password file handling: exceptions and ignore carriage returns
* prevent races during setup and cleanup of network connections
* take shortcut if there is nothing to send


## [0.6.3] 2012-09-27
* fix memory leak in server after client disconnection
* fix launcher: clear socket timeout once connected and add missing options
* fix potential bug in network code (prevent disconnection)
* enable auto-refresh by default since we now use a lossy encoder by default


## [0.6.2] 2012-09-25
* fix missing key frames with x264/vpx: always reset the video encoder when we skip some frames (forces a new key frame)
* fix server crash on invalid keycodes (zero or negative)
* fix latency: isolate per-window latency statistics from each other
* fix latency: ensure we never record zero or even negative decode time
* fix refresh: server error was causing refresh requests to be ignored
* fix window options handling: using it for more than one value would fail
* fix video encoder/windows dimensions mismatch causing missing key frames
* fix damage options merge code (options were being squashed)
* ensure that small lossless regions do not cancel the auto-refresh timer
* restore protocol main packet compression and single chunk sending
* drop unnecessary OpenGL dependencies from some deb/rpm packages


## [0.6.1] 2012-09-14
* fix compress clipboard data (previous fix was ineffectual)
* fix missing damage data queue statistics (was causing latency issues)
* use memory aligned allocations for colourspace conversion


## [0.6.0] 2012-09-08
* fix launcher: don't block the UI whilst connecting, and use a lower timeout, fix icon lookup on *nix
* fix clipboard contents too big (was causing connection drops): try to compress them and just drop them if they are still too big
* x264 or vpx are now the default encodings (if available)
* compress rgb24 pixel data with zlib from the damage thread (rather than later in the network layer)
* better build environment detection
* experimental multi-user support (see --enable-sharing)
* better, more accurate "xpra info" statistics (per encoding, etc)
* tidy up main source directory
* simplify video encoders/decoders setup and cleanup code
* many debian build files updates
* remove 'nogil' switch (as 'nogil' is much faster)
* test all socket types with automated tests


## [0.5.4] 2012-09-08
* fix man page typo
* fix non bash login shell compatibility
* fix xpra screenshot argument parsing error handling
* fix video encoding mismatch when switching encoding
* fix ssh mode on OpenBSD


## [0.5.3] 2012-09-05
* zlib compatibility fix: use chunked decompression when supported (newer versions)


## [0.5.2] 2012-08-29
* fix xpra launcher icon lookup on *nix
* fix big clipboard packets causing disconnection: just drop them instead
* fix zlib compression in raw packet mode: ensure we always flush the buffer for each chunk
* force disconnection after irrecoverable network parsing error
* fix window refresh: do not skip all windows after a hidden one!
* Fedora 16 freshrpms spec file fix: build against rpmfusion despite more limited csc features


## [0.5.1] 2012-08-25
* fix xpra_launcher
* fix DPI issue with Xdummy: set virtual screen to 96dpi by default
* avoid looping forever doing maths on 'infinity' value
* fix incomplete cloning of attributes causing default values to be used for batch configuration
* damage data queue batch factor was being calculated but not used
* ensure we update the data we use for calculations (was always using zero value)
* ensure "send_bell" is initialized before use
* add missing path string in warning message
* fix test code compatibility with older xpra versions
* statistics shown for 'damage_packet_queue_pixels' were incorrect


## [0.5.0] 2012-08-20
* new packet encoder written in C (much faster and data is now smaller too)
* read provided /etc/xpra/xpra.conf and user's own ~/.xpra/xpra.conf
* support Xdummy out of the box on platforms with recent enough versions of Xorg (and not installed suid)
* pass dpi to server and allow clients to specify dpi on the command line
* fix xsettings endianness problems
* fix clipboard tokens sent twice on start
* new command line options and UI to disable notifications forwarding, cursors and bell
* MS Windows clients can now choose the remote clipboard they sync with ('clipboard', 'primary' or 'secondary')
* x264: adapt colourspace conversion, encoding speed and picture quality according to link and encoding/decoding performance
* automatically change video encoding: handle small region updates (ie: blinking cursor or spinner) without doing a full video frame refresh
* fairer window batching calculations, better performance over low latency links and bandwidth constrained links
* lower tcp socket connection timeout (10 seconds)
* better compression of cursor data
* log date and time with messages, better log messages (ie: "Ignoring ClientMessage..")
* send more client and server version information (python, gtk, etc)
* build cleanups: let distutils clean take care of removing all generated .c files
* code cleanups: move all win32 specific headers to win32 tree, fix vpx compilation warnings, whitespace, etc
* more reliable MS Windows build: detect missing/wrong DLLs and abort
* removed old "--no-randr" option
* drop compatibility with versions older than 0.3: we now assume the "raw_packets" feature is supported


## [0.4.2] 2012-08-16

* fix clipboard atom packing (was more noticeable with qt and Java applications)
* fix clipboard selection for non X11 clients: only 'multiple' codepath requires X11 bindings
* fix python3 build
* fix potential double free in x264 error path
* fix logging format error on "window dimensions have changed.." (parameter grouping was wrong)
* fix colour bleeding with x264 (ie: green on black text)
* remove incorrect and unnecessary callback to `setup_xprops` which may have caused the pulseaudio flag to use the wrong value
* delay 'check packet size' to allow the limit to be raised - important over slower links where it triggers more easily


## [0.4.1] 2012-07-31
* fix clipboard bugs
* fix batch delay calculations with multiple windows
* fix tests (update import statements)
* robustify cython version string parsing
* fix source files changed detection during build


## [0.4.0] 2012-07-23
* fix client application resizing its own window
* fix window dimensions hints not applied
* fix memleak in x264 cleanup code
* fix xpra command exit code (more complete fix)
* fix latency bottleneck in processing of damage requests
* fix free uninitialized pointers in video decoder initialization error codepath
* fix x264 related crash when resizing windows to one pixel width or height
* fix accounting of client decode time: ignore figure in case of decoding error
* fix subversion build information detection on MS Windows
* fix some binary packages which were missing some menu icons
* restore keyboard compatibility code for MS Windows and OSX clients
* use padded buffers to prevent colourspace conversion from reading random memory
* release Python's GIL during vpx and x264 compression and colourspace conversion
* better UI launcher: UI improvements, detect encodings, fix standalone/win32 usage, minimize window once the client has started
* "xpra stop" disconnects all potential clients cleanly before exiting
* x264 uses memory aligned buffer for better performance
* avoid vpx/x264 overhead for very small damage regions
* detect dead connection with ping packets: disconnect if echo not received
* force a full refresh when the encoding is changed
* more dynamic framerate performance adjustments, based on more metrics
* new menu option to toggle keyboard sync at runtime
* vpx/x264 runtime imports: detect broken installations and warn, but ignore when the codec is simply not installed
* enable environment debugging for damage batching via "XPRA_DEBUG_LATENCY" en## [] variable
* simplify build by using setup file to generate all constants
* text clients now ignore packets they are not meant to handle
* removed compression menu since the default is good enough
* "xpra info" reports all build version information
* report server pygtk/gtk versions and show them on session info dialog and "xpra info"
* ignore dependency issues during sdist/clean phase of build
* record more statistics (mostly latency) in test reports
* documentation and logging added to code, moved test code out of main packages
* better MS Windows installer graphics
* include distribution name in RPM version/filename
* CentOS 6 RPMs now depends on libvpx rather than a statically linked library
* CentOS static ffmpeg build with memalign for better performance
* debian: build with hardening features
* debian: don't record as modified the files we know we modify during debian build
* MS Windows build: allow user to set --without-vpx / --without-x264 in the batch file
* MS Windows build fix: simpler/cleaner build for vpx/x264's codec.pyd
* no longer bundle parti window manager


## [0.3.3] 2012-07-10
* do not try to free the empty x264/vpx buffers after a decompression failure
* fix xpra command exit code (zero) when no error occurred
* fix Xvfb deadlock on shutdown
* fix wrongly removing unix domain socket on startup failure
* fix wrongly killing Xvfb on startup failure
* fix race in network code and metadata packets
* ensure clients use raw_packets if the server supports it (fixes 'gibberish' compressed packet errors)
* fix screen resolution reported by the server
* fix maximum packet size check wrongly dropping valid connections
* honour the --no-tray command line argument
* detect Xvfb startup failures and avoid taking over other displays
* don't record invalid placeholder value for "server latency"
* fix missing "damage-sequence" packet for sequence zero
* fix window focus with some Tk based application (ie: git gui)
* prevent large clipboard packets from causing the connection to drop
* fix for connection with older clients and server without raw packet support and rgb24 encoding
* high latency fix: reduce batch delay when screen updates slow down
* non-US keyboard layout fix
* correctly calculate min_batch_delay shown in statistics via "xpra info"
* require x264-libs for x264 support on Fedora


## [0.3.2] 2012-06-04
* fix missing 'a' key using OS X clients
* fix debian packaging for xpra_launcher
* fix unicode decoding problems in window title
* fix latency issue


## [0.3.1] 2012-05-29
* fix DoS in network connections setup code
* fix for non-ascii characters in source file
* log remote IP or socket address
* more graceful disconnection of invalid clients
* updates to the man page and xpra command help page
* support running the automated tests against older versions
* "xpra info" to report the number of clients connected
* use xpra's own icon for its own windows (about and info dialogs)


## [0.3.0] 2012-05-20
* zero-copy network code, per packet compression
* fix race causing DoS in threaded network protocol setup
* fix vpx encoder memory leak
* fix vpx/x264 decoding: recover from frame failures
* fix small per-window memory leak in server
* per-window update batching auto-tuning, which is fairer
* windows update batching now takes into account the number of pixels rather than just the number of regions to update
* support --socket-dir option over ssh
* IP## [6] support using the syntax: ssh/::ffff:192.168.1.100/10 or tcp/::ffff:192.168.1.100/10000
* all commands now return a non-zero exit code in case of failure
* new "xpra info" command to report server statistics
* prettify some of the logging and error messages
* avoid doing most of the keyboard setup code when clients are in read-only mode
* Solaris build files
* automated regression and performance tests
* remove compatibility code for versions older than 0.1


## [0.2.0] 2012-04-20
* x264 and vpx video encoding support
* gtk3 and python 3 partial support (client only - no keyboard support)
* detect missing X11 server extensions and exit with error
* X11 server no longer listens on a TCP port
* clipboard fixes for Qt/KDE applications
* option for clients not to supply any keyboard mapping data (the server will no longer complain)
* show more system version information in session information dialog
* hide window decorations for openoffice splash screen (workaround)


## [0.1.0] 2012-03-21
* security: strict filtering of packet handlers until connection authenticated
* prevent DoS: limit number of concurrent connections attempting login 20
* prevent DoS: limit initial packet size (memory exhaustion: 32KB)
* mmap: options to place sockets in /tmp and share mmap area across users via unix groups
* remove large amount of compatibility code for older versions
* fix for Mac OS X clients sending hexadecimal keysyms
* fix for clipboard sharing and some applications (ie: Qt)
* notifications systems with dbus: re-connect if needed
* notifications: try not to interfere with existing notification services
* mmap: check for protected file access and ignore rather than error out (oops)
* clipboard: handle empty data rather than timing out
* spurious warnings: remove many harmless stacktraces/error messages
* detect and discard broken windows with invalid atoms, avoids vfb + xpra crash
* unpress keys all keys on start (if any)
* fix screen size check: also check vertical size is sufficient
* fix for invisible 0 by 0 windows: restore a minimum size
* fix for window dimensions causing enless resizing or missing window contents
* toggle cursors, bell and notifications by telling the server not to bother sending them, saves bandwidth
* build/deploy: don't modify file in source tree, generate it at build time only
* add missing GPL2 license file to show in about dialog
* Python 2.5: workarounds to restore support
* turn off compression over local connections (when mmap is enabled)
* Android fixes: locking, maximize, focus, window placement, handle rotation, partial non-soft keyboard support
* clients can specify maximum refresh rate and screen update batching options


## [0.0.7.36] 2012-02-09
* fix clipboard bug which was causing Java applications to crash
* ensure we always properly disconnect previous client when new connection is accepted
* avoid warnings with Java applications, focus errors, etc


## [0.0.7.35] 2012-02-01
* ssh password input fix
* osx dock_menu fixed
* ability to take screenshots ("xpra screenshot")
* report server version ("xpra version")
* slave windows (drop down menus, etc) now move with their parent window
* show more session statistics: damage regions per second
* posix clients no longer interfere with the GTK/X11 main loop
* ignore missing properties when they are changed, and report correct source of the problem
* code style cleanups and improvements


## [0.0.7.34] 2012-01-19
* security: restrict access to run-xpra script (chmod)
* security: cursor data sent to the client was too big (exposing server memory)
* fix thread leak - properly this time, SIGUSR1 now dumps all threads
* off-by-one keyboard mapping error could cause modifiers to be lost
* pure python/cython method for finding modifier mappings (faster and more reliable)
* retry socket read/write after temporary error EINTR
* avoid warnings when asked to refresh windows which are now hidden
* auto-refresh was using an incorrect window size
* logging formatting fixes (only shown with logging on)
* hide picture encoding menu when mmap in use (since it is then ignored)


## [0.0.7.33] 2012-01-13
* readonly command line option
* correctly stop all network related threads on disconnection
* faster pixel data transfers for large areas via mmap
* fix auto-refresh jpeg quality
* fix on-the-fly change of pixel encoding
* fix potential exhaustion of mmap area
* fix potential race in packet compression setup code
* keyboard: better modifiers detection, synchronization of capslock and numlock
* keyboard: support all modifiers correctly with and without keyboard-sync option


## [0.0.7.32] 2011-12-08
* bug fix: disconnection could leave the server (and X11 server) in a broken state due to threaded UI calls
* bug fix: don't remove window focus when just any connection is lost, only when the real client goes away
* bug fix: initial windows should get focus (partial fix)
* bug fix: correctly clear focus when a window goes away
* support key repeat latency workaround without needing raw keycodes (OS X and MS Windows)
* command line switch to enable client side key repeat: "--no-keyboard-sync" (for high latency/jitter links)
* session info dialog: shows realtime connection and server details
* menu entry in system tray to raise all managed windows
* key mappings: try harder to unpress all keys before setting the new keymap
* key mappings: try to reset modifier keys as well as regular keys
* key mappings: apply keymap using Cython code rather than execing xmodmap
* key mappings: fire change callbacks only once when all the work is done
* use dbus for tray notifications if available, preferred to pynotify
* show full version information in about dialog


## [0.0.7.31] 2011-11-28
* threaded server for much lower latency
* fast memory mapped transfers for local connections
* adaptive damage batching, fixes window refresh
* xpra "detach" command
* fixed system tray for Ubuntu clients
* fixed maximized windows on Ubuntu clients


## [0.0.7.30] 2011-11-01
* fix for update batching causing screen corruption
* fix AttributeError jpegquality: make PIL (aka python-imaging) truly optional
* fix for jitter compensation code being a little bit too trigger-happy


## [0.0.7.29] 2011-10-25
* fix partial packets on boundary causing connection to drop
* clipboard support on MS Windows
* support ubuntu's appindicator (yet another system tray implementation)
* improve disconnection diagnostic messages
* scale cursor down to the client's default size
* better handling of right click on system tray icon
* posix: detect when there is no DISPLAY and error out
* remove harmless warnings about missing properties on startup


## [0.0.7.28] 2011-10-18
* much more efficient and backwards compatible network code, prevents a CPU bottleneck on the client
* forwarding of system notifications, system bell and custom cursors
* system tray menu to make it easier to change settings and disconnect
* automatically resize Xdummy to match the client's screen size whenever it changes
* PNG image compression support
* JPEG and PNG compression are now optional, only available if the Python Imaging Library is installed
* scale window icons before sending if they are too big
* fixed keyboard mapping for OSX and MS Windows clients
* compensate for line jitter causing keys to repeat
* fixed cython warnings, unused variables, etc


## [0.0.7.27] 2011-09-20
* compatibility fix for python 2.4 (remove "with" statement)
* slow down updates from windows that refresh continuously


## [0.0.7.26] 2011-09-20
* minor changes to support the Android client (work in progress)
* allow keyboard shortcuts to be specified, default is meta+shift+F4 to quit (disconnects client)
* clear modifiers when applying new keymaps to prevent timeouts
* reduce context switching in the network read loop code
* try harder to close connections cleanly
* removed some unused code, fixed some old test code


## [0.0.7.25] 2011-08-31
* Proper keymap and modifiers support


## [0.0.7.24] 2011-08-15
* Use raw keycodes whenever possible, should fix keymapping issues for all Unix-like clients
* Keyboard fixes for AltGr and special keys for non Unix-like clients


v0.0.7.23-2 2011-07-27
* More keymap fixes..


## [0.0.7.23] 2011-07-20
* Try to use setxkbmap before xkbcomp to setup the matching keyboard layout
* Handle keyval level (shifted keys) explicitly, should fix missing key mappings
* More generic option for setting window titles
* Exit if the server dies


## [0.0.7.22] 2011-06-02
* minor fixes: jpeg, man page, etc


## [0.0.7.21] 2011-05-24
  New features:
* Adaptive JPEG mode (bandwidth constrained)
* Use an existing display
* Disable randr


## [0.0.7.20] 2011-05-04
* more reliable fix for keyboard mapping issues


## [0.0.7.19] 2011-04-25
* xrandr support when running against Xdummy, screen resizes on demand
* fixes for keyboard mapping issues: multiple keycodes for the same key


v0.0.7.18-2 2011-04-04
* Fix for older distros (like CentOS) with old versions of pycairo


## [0.0.7.18] 2011-03-28
* Fix jpeg compression on MS Windows
* Add ability to disable clipboard code
* Updated man page


## [0.0.7.17] 2011-04-04
* Honour the pulseaudio flag on client


## [0.0.7.16] 2010-08-25
* Merged upstream changes


## [0.0.7.15] 2010-07-01
* Add option to disable Pulseaudio forwarding as this can be a real network hog
* Use logging rather than print statements


## [0.0.7.13] 2010-05-04
* Ignore minor version differences in the future (must bump to 0.0.8 to cause incompatibility error)


## [0.0.7.12] 2010-03-13
* bump screen resolution


## [0.0.7.11] 2010-01-11
* first rpm spec file


## [v0.0.7.x] 2009
* Start of this fork
* Password file support
* Better OSX/win32 support
* JPEG compression
* Lots of small fixes


## [0.0.6] 2009-03-22
### Xpra New features:
* Clipboard sharing (with full X semantics).
* Icon support.
* Support for raw TCP sockets. Insecure if you don't know what
you are doing.

### Xpra Bug fixes:
* Xvfb doesn't support mouse wheels, so they still don't work in
xpra. But now xpra doesn't crash if you try.
* Running FSF Emacs under xpra no longer creates an infinite loop.
* The directory that xpra was launched from is now correctly
saved in ~/.xpra/run-xpra.
* Work around PyGtk weirdness that caused the server and client
to sometimes ignore control-C.
* The client correctly notices keyboard layout changes.
* The client no longer crashes on keymaps in which unnamed keys
are bound to modifiers.
* Workarounds are included for several buggy versions of Pyrex.

### Wimpiggy:
* Assume that EWMH-style icons have non-premultiplied alpha.

### Other:
* Add copyright comments to all source files.


## [0.0.5] 2008-11-02
This release primarily contains cleanups and bugfixes for xpra.

### General:
* Logging cleanup -- all logging now goes through the Python
logging framework instead of using raw 'prints'.  By default,
debug logging is suppressed, but can be enabled in a fine- or
coarse-grained way.

### Xpra:
* Protocol changes; ## [0.0.5] clients can only be used with v0.0.5
servers, and vice-versa.  Use 'xpra upgrade' to upgrade old
servers without losing your session state.
* Man page now included.
### Important bug fixes:
* Qt apps formerly could not receive keyboard input due to a focus
handling bug; now fixed.
* Fedora's pygtk2 has mysterious local hacks that broke xpra;
a workaround is now included.
### UI improvements:
* 'xpra attach ssh:machine' now works out-of-the-box even if xpra
is not present in the remote machine's PATH, or requires
PYTHONPATH tweaks, or whatever.  (The server does still need to
be running on the remote machine, though, of course.)
* Commands that connect to a running xpra server ('attach', 'stop',
etc.) now can generally be used without specifying the name of
the server, assuming only one server is running.  (E.g., instead
of 'xpra attach :10', you can use 'xpra attach'; ditto for remote
hosts, you can now use plain 'xpra attach ssh:remote'.)
* Mouse scroll wheels now supported.
* 'xpra start' can now spawn child programs directly (--with-child)
and exit automatically when these children have exited
(--exit-with-children).
### Other:
* More robust strategy for handling window stacking order.
(Side-effect: the xpra client no longer requires you to be using
an EWMH-compliant window manager.)
* The xpra client no longer crashes when receiving an unknown key
event (e.g. a multimedia key).
* Very brief transient windows (e.g., tooltips) no longer create
persistent "litter" on the screen.
* Windows with non-empty X borders (e.g., xterm popup menus) are
now handled properly.
* Withdrawn windows no longer reappear after 'xpra upgrade'.

### Wimpiggy:
* Do not segfault when querying the tree structure of destroyed
windows.
* Other bugfixes.

### Parti:
* No changes.

## [0.0.4] 2008-04-04
### Xpra:
* Protocol changes break compatibility with 0.0.3, but:
* New command 'xpra upgrade', to restart/upgrade an xpra server
without losing any client state.  (Won't work when upgrading from
0.0.3, unfortunately, but you're covered going forward.)
* Fix bug that left stray busy-looping processes behind on server
when using ssh connections.
* Export window class/instance hints (patch from Ethan Blanton).
* Hack to make backspace key work (full support for keyboard maps
still TBD).
* Added discussion of xmove to README.xpra.

### Wimpiggy:
* Make compatible with current Pyrex releases (thanks to many
 people for reporting this).
* Work around X server bug #14648 (thanks to Ethan Blanton for help
 tracking this down).  This improves speed dramatically.
* Reverse-engineer X server lifetime rules for NameWindowPixmap,
 and handle it properly.  Also handle it lazily.  This fixes the
 bug where window contents stop updating.
* Avoid crashing when acknowledging damage against an
 already-closed window.
* Improve server extension checking (thanks to 'moreilcon' for the
 report).
* Remove spurious (and harmless) assertion messages when a window
 closes.
* Make manager selection handling fully ICCCM-compliant (in
 particular, we now pause properly while waiting for a previous
 window manager to exit).
* Make algorithm for classifying unmapped client windows fully
 correct.
* Reduce required version of Composite extension to 0.2.

### Parti:
* Remove a stale import that caused a crash at runtime (thanks to
 'astronouth7303' for the report).

### General:
* Error out build with useful error message if required packages
 are missing.

## Parti 0.0.3 2008-02-20
Massive refactoring occurred for this release.

### wimpiggy:
The WM backend parts of Parti have been split off into a
separate package known as wimpiggy.  As compared to the corresponding
code in 0.0.2, wimpiggy 0.0.3 adds:
* Compositing support
* Model/view separation for client windows (based on compositing
 support)
* Improved client hint support, including icon handling, strut
 handling, and more correct geometry handling.
* Keybinding support
* Event dispatching that doesn't leak memory
* Better interaction with already running window managers (i.e., a
 --replace switch as seen in metacity etc.)

### parti:
This package will eventually become the real window manager,
but for now is essentially a testbed for wimpiggy.

### xpra:
This is a new, independent program dependent on wimpiggy (which
is why wimpiggy had to be split out).  It implements 'screen for X' --
letting one run applications remotely that can be detached and then
re-attached without losing state.  This is the first release, but
while not perfect, it is substantially usable.

### general:
The test runner was hacked to share a single X/D-Bus session
across multiple tests.  This speeds up the test suite by a factor of
~3, but seems to be buggy and fragile and may be reverted in the
future.


## Parti 0.0.2 2007-10-26
This release adds a mostly comprehensive test suite, plus fixes a lot
of bugs.  Still only useful for experimentation and hacking.

'python setup.py sdist' sort of works now.


## Parti 0.0.1 2007-08-10
Initial release.

Contains basic window manager functionality, including a fair amount
of compliance to ICCCM/EWMH, focus handling, etc., and doesn't seem to
crash in basic testing.

Doesn't do much useful with this; only a simple placeholder layout
manager is included, and only skeleton of virtual desktop support is
yet written.
