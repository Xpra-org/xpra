# Security Policy

## Supported Versions

Please ensure that you are using a [supported version](https://github.com/Xpra-org/xpra/wiki/Versions).

Distribution packages are usually [outdated and full of vulnerabilities](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages).

For a general overview, please first read [security considerations](./docs/Usage/Security.md) as it pervades the architecture of the software.

To isolate applications which may be hostile, see the [secure pod](https://github.com/Xpra-org/xpra/tree/master/packaging/containers/podman/secure):
the application runs in its own container, which only shares the X11 display with the X server and the xpra server.


## Reporting a Vulnerability

We understand and accept that some researchers prefer full-disclosure, but we would prefer to have a heads up prior to the release of the vulnerability details.

Critical bugs are usually fixed (if reproducible) within hours, rather than days or weeks. Though making a new release does take a little bit longer.
Even more so for vulnerabilities.

Please contact [security@xpra.org](mailto:security@xpra.org).

You can encrypt all communications with the following GPG key: `66EA1EA1A1323924` for `xpra@xpra.org`, the primary key fingerprint: `B499 3B57 3231 48E3 7977  E5D8 7325 4CAD 1797 8FAF` is the same as the one used for [signing packages](https://github.com/Xpra-org/xpra/wiki/Download#-signatures).


## Notifications

To receive email notifications of pending security issues in any of the xpra projects,
please send a request to [security@xpra.org](mailto:security@xpra.org)


## Known issues
* [CVE-2021-40839](https://nvd.nist.gov/vuln/detail/CVE-2021-40839) [`rencode` issue](https://www.mail-archive.com/shifter-users@lists.devloop.org.uk/msg02754.html) affected all MS Windows and MacOS binary packages produced before the fix
* [RCE via xpra URLs](https://github.com/Xpra-org/xpra/issues/4951)
* [file-transfer vulnerabilities](https://github.com/Xpra-org/xpra/issues/4952)
* [encodings are not validated](https://github.com/Xpra-org/xpra/issues/4950)
* [2026-07-09: Multiple vulnerabilities in the Xpra client](https://www.synacktiv.com/en/advisories/multiple-vulnerabilities-in-the-xpra-client)
* [unsafe `yaml.load` packet decoder](https://github.com/Xpra-org/xpra/commit/908421a388edcc3990621d0daa58350de900622d): all versions from 0.14 up to and including 4.0.x (and the 1.0.x, 3.1.x LTS branches) decode `yaml` packets with the unsafe loader, allowing remote code execution with PyYAML older than 5.4 - fixed in 4.1
* [CVE-2020-8927](https://nvd.nist.gov/vuln/detail/CVE-2020-8927) [`brotli` decoder integer overflow](https://github.com/Xpra-org/xpra/commit/781fb67827f891f427c66d9988b8423049954b64): `brotli` packet and clipboard compression was added in 3.0, so all MS Windows and MacOS binary packages from 3.0 (September 2019) up to the builds made with brotli 1.0.9 (around September 2020) bundle a vulnerable decoder
* [`jpeg` decoder heap overflow](https://github.com/Xpra-org/xpra/commit/9c910cdfdec05e8088de79d652ea67f27f3c70fe): the size of the RGB output buffer was computed with a 32-bit multiplication, so a crafted `jpeg` / `jpega` image declaring very large dimensions under-allocates it and the decoder writes past its end - from 4.3 onwards, fixed in 6.5.6
* [`vpx` decoder heap over-read](https://github.com/Xpra-org/xpra/commit/9c910cdfdec05e8088de79d652ea67f27f3c70fe): a `vp9` stream declaring a smaller frame than the one the decoder was initialized with makes it copy past the end of the planes, leaking heap memory into the decoded image - all versions, fixed in 6.5.6
* [`YUV444P` to `BGRX` / `RGBX` heap overflow](https://github.com/Xpra-org/xpra/commit/b11c671e6120601a78eabb6ebfd603008eb4b3ca): the `csc_cython` converter allocated 3 bytes per pixel for a 4 bytes per pixel output, so painting `YUV444P` video frames without OpenGL overflows the heap - 6.0 to 6.5.0, fixed in 6.5.1
* [mmap file confused deputy](https://github.com/Xpra-org/xpra/commit/eb1c885c2dd3abeca7c06aed050271f1a2dfb212): the server opened whatever path an authenticated client named as its mmap file and wrote its own token back into it, so a client naming a file with known contents could corrupt any file owned by the server user, even over TCP, websocket or SSL - from 0.10 up to 6.5.2, fixed in 6.5.3
* [unvalidated mmap chunks](https://github.com/Xpra-org/xpra/commit/6d4bc44abf38586aa408131093eaca07681ef89f) and [OpenGL draw buffers](https://github.com/Xpra-org/xpra/commit/e60277ead8c511d4794bf0d5f0cb36558300e174): the chunk offsets and lengths, the mmap control header pointers and the `rgb` draw geometry all come from the peer and were not checked against the buffers, allowing reads outside of them - fixed in 6.5.3
* [`peercred` authentication bypass](https://github.com/Xpra-org/xpra/issues/4686): when no `uid` or `gid` was specified, `peercred` accepted any local user instead of only the socket owner, so any local user could connect to another user's session through the abstract socket every Linux server creates automatically - 6.3.0 to 6.3.4, fixed in 6.3.5
* [`libpng` CVE-2025-64720 and CVE-2025-66293](https://github.com/Xpra-org/xpra/issues/4722): screen updates use `libspng`, but window icons and clipboard images are still parsed by Pillow using `libpng`, so a malicious server could send crafted icons, and any application could copy a crafted image to the clipboard while image sanitizing is enabled (the default) - MS Windows and MacOS binary packages built before December 2025, re-issued with libpng 1.6.52 for 6.4 and 5.1.4
* [cross-site websocket hijacking](https://github.com/Xpra-org/xpra/issues/4957): the `Origin` header of websocket connections was not validated, so any web page visited by the user could connect to a `bind-ws` socket (or a websocket upgradable one) and take over a session that does not require authentication - all versions, only fixed in 7.0 with the new `http-origin` option
* [notifications from the server are not validated](https://github.com/Xpra-org/xpra/issues/5085): a malicious server could make the client's notification daemon load local files (`app_icon` URIs, `img` tags in the body), show links, impersonate local applications, bypass "do not disturb" or flood the desktop with notifications - all versions, fixed in 7.0
* [strings and data from the peer are not validated](https://github.com/Xpra-org/xpra/issues/5084): window titles, file names, client names, log messages and other strings could contain control characters, terminal escape sequences or bidi overrides, used to spoof window titles and file extensions or to inject into log files, and some lists (clipboard targets, printers, monitors, start menu) had no size limit - all versions, fixed in 7.0


## False positives
Some vulnerabilities are reported, sometimes automatically,
but cannot be exploited because the code is not actually used:
* [`braces` v3.0.2 / `micromatch` v4.0.5 vulnerabilities](https://github.com/Xpra-org/xpra-html5/issues/306)
* [xpra 4.0 wrongly detected as `Trojan:Win32/Sprisky.D!cl`](https://github.com/Xpra-org/xpra/issues/2781)
* [_bitdefender endpoint security tools_ malware false positive]([https://github.com/Xpra-org/xpra/issues/2088](https://github.com/Xpra-org/xpra/issues/2088#issuecomment-765511350))
* [norton antivirus wrongly detected as `Suspicious.Cloud.7.F`](https://github.com/Xpra-org/xpra/issues/527)


## Hardening
* [process level protections: prevent ptrace / core dumps](https://github.com/Xpra-org/xpra/issues/4958)
* [rate limit authentication requests](https://github.com/Xpra-org/xpra/issues/4959)
* [landlock the client](https://github.com/Xpra-org/xpra/issues/4960)
* [hardening](https://github.com/Xpra-org/xpra/issues/4962)
* [seccomp security support](https://github.com/Xpra-org/xpra/issues/622)
* [stricter validation of user supplied data](https://github.com/Xpra-org/xpra/issues/3618)
* [immutable types](https://github.com/Xpra-org/xpra/issues/3576)
* [features enforcing mode: block import of modules](https://github.com/Xpra-org/xpra/issues/4307)

## Features and policy
* [add authentication for web server scripts](https://github.com/Xpra-org/xpra/issues/3100)
* [disable control channel](https://github.com/Xpra-org/xpra/issues/3573)
* [fine grained control channel access](https://github.com/Xpra-org/xpra/issues/3574)
* [allow to disable sending unneeded user data to the server](https://github.com/Xpra-org/xpra/issues/3582)
* [new subcommand to generate SSL certificates easily](https://github.com/Xpra-org/xpra/issues/4288)
* [trust some connections with unencrypted data](https://github.com/Xpra-org/xpra/issues/4436)
* [option to control server shutdown permission per bind option](https://github.com/Xpra-org/xpra/issues/4682)
* [override the username provided by the client without using `--username` or URI](https://github.com/Xpra-org/xpra/issues/4756)
* [new gpg project key](https://github.com/Xpra-org/xpra/issues/3863)
* [security issues handling](https://github.com/Xpra-org/xpra/issues/4565)
* [AES v2](https://github.com/Xpra-org/xpra/issues/4375)
* [throttle rude repository users](https://github.com/Xpra-org/xpra/issues/5045)
* [SMS 2FA](https://github.com/Xpra-org/xpra/issues/5078)
