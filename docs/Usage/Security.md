# Security considerations

A significant proportion of Xpra's development was sponsored by the security industry to provide a shield for users securely running applications that require network access - the xpra clients are only exposed to a tightly controlled and secure network flux,
completely removed from the underlying protocols that those applications normally use to interact with the user.

As a result, the architecture, features and options are often directly related to the mechanisms that this fine-grained control requires.
These defenses can be applied to a client protecting itself from a potentially hostile application or server and also in the opposite direction to confine users to the environment assigned to them.
A default xpra installation should be quite secure by default, but there are trade-offs to be made.

Be aware that these defenses all count for nothing when using [downstream out of date packages](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages).


## Architecture
The way xpra is structured into independent python submodules allows it to partition off each subsystem. \
When features are disabled, they are not just unused, they are [not even loaded into memory](https://github.com/Xpra-org/xpra/issues/1861#issuecomment-76549942500) in the first place. Those subsystem interfaces cannot be abused since they don't even exist in that process space - very much like when features are not installed on the system at all. \
When combined with fine-grained [sub-packages](../Build/Packaging.md), you can also do exactly that: install only what is strictly needed. \
For technical details, see [dynamic client connection class](https://github.com/Xpra-org/xpra/issues/2351) and [completely skip server base classes](https://github.com/Xpra-org/xpra/issues/1838) \
The same principle applies to [codecs](https://github.com/Xpra-org/xpra/issues/2344) and [all swappable components](https://github.com/Xpra-org/xpra/issues/614). \
Moreover, the use of pure Python code for the vast majority of the data handling completely prevents whole classes of vulnerabilities. The parts of the code that do require high performance (data mangling, (de)compression, etc) use heavily optimized libraries (see _audio_ and _encodings_ below) - which are all optional.


## Subsystems
Most of the features below have explicit command line switches which can be used to completely disable the subsystem, to start with the feature turned off or to restrict the feature in its scope or impact. \
If a client or server turns off a subsystem then the remote end cannot enable the feature. Some switches only affect the on / off state of the feature instead, which does allow for the feature to be enabled through a user action once the connection is established. \
These toggles may also be accessible through the server's control channel and dbus interface. \

<details>
  <summary>Specific Subsystems</summary>

### [Clipboard](../Features/Clipboard.md)
Obviously, from a security perspective, the safest clipboard is one that is disabled (`--clipboard=no`)
but that is not always an acceptable compromise for end users, in which case limiting the `--clipboard-direction` may be enough.
Beyond this, there are many other tunables in the [clipboard subsystem](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard)
and its various OS specific implementations. This can be used to restrict the rate and size of the data transferred, filter out certain types of contents,
select which clipboards can be accessed (for platforms that support more than one clipboard type), the type of data exchanged, etc..
Pictures transferred using the clipboard from server to client are sanitized (re-encoded) and watermarked.

### [Audio](../Features/Audio.md)
Very much like the clipboard, the safest way to handle audio is to not forward it at all.
If audio forwarding has to be enabled, not all codecs are equal from a security point of view.
Using a codec without a container reduces the complexity somewhat, but using a raw audio format like `wav` is the safest option since there is no parsing involved. The downside is that this is an uncompressed format, though xpra does offer the option to compress `wav` using `lz4`.
That said, `mp3` is now over 30 years old and the libraries parsing it are very mature.
Other codecs have had a few issues in more recent times (ie: [faac and faad2 security issues](https://github.com/Xpra-org/xpra/issues/2474))
xpra runs the audio processing in a separate process which does not have access to the display.

### [Encodings](Encodings.md)
Xpra supports a large number of picture and video codecs as well as raw uncompressed pixel data.
Each encoding option has different strengths and weaknesses. The raw options `rgb` and `mmap` are obviously the safest since they do not require any parsing, but they can require humongous amounts of bandwidth (ie: tens of Gbps for a 4K window).
Older picture encodings like `png` and `jpeg` are probably the safests due to their maturity.
Video encodings as well as newer picture encodings (often derived from the new generation of video compression techniques, like `webp` and `avif`) are probably less safe due to their level of complexity - see also _hardware access_ below.

### [Printing](../Features/Printing.md)
Printer forwarding presents security challenges for both the server and the client:
* the server parses printer data from the client and then uses privileged commands to create a matching virtual printer. The client can also update the list of printers at any time, causing the whole setup process to be repeated.
* the client receives Postscript or PDF files which are sent to the real printer, this is compartively safer - though parsing bugs for these formats have been found

### [File Transfers](../Features/File-Transfers.md)
This feature has potential for abuse in both directions which is why there are many options to restrict what can be done with it.
File transfers can be disabled completely which is obviously the safest option.
The default settings allow file transfers but a user confirmation is requested before accepting a file or opening it.
The file size and number of concurrent file transfers can also be configured.

### [System Tray](../Features/System-Tray.md) and [Notifications](../Features/Notifications.md) forwarding
These features provide tighter desktop integration which can be seen as a security risk and can be turned off completely.
However, the improved usability usually makes this an acceptable trade-off and these features are enabled by default.

### [Webcam](../Features/Webcam.md)
Although this feature is never turned on by default, it is available.
There are obvious privacy concerns here, and it may be desirable to turn off the feature completely.

### `DBus`
"_D-Bus is a message bus system, a simple way for applications to talk to one another_.
_In addition to interprocess communication, D-Bus helps coordinate process lifecycle_."
This makes `dbus` both a very useful desktop environment component and a wide attack target.
The `--dbus-control` channel should be turned off if unused.

### Hardware Access
Any subsystem that accesses hardware directly is an inherent security risk.
This includes: the [NVENC encoder](NVENC.md) (see also _proxy server system integration_), hardware OpenGL [server](OpenGL.md) and [client](Client-OpenGL.md) acceleration, printer access and some authentication modules.

</details>

---

## Operation

<details>
  <summary>Running mode, network connections and diagnostics, malicious peers, specific options</summary>

### Modes
Some features are harder to implement correctly in [seamless mode](Seamless.md) because of the inherent complexity of handling windows client side and synchronizing their state. (ie: [window resizing vs readonly mode](https://github.com/Xpra-org/xpra/issues/2137))
By definition, shadow mode gives access to the full desktop, without any kind of restriction - for better or worse.
For these reasons, it may be worth considering [desktop mode](Desktop.md) instead.

### [Network](../Network) and [Authentication](Authentication.md)
Xpra supports natively many different types of network connections (`tcp`, `ssl`, `ws`, `wss`, `vnc`, `ssh`, `vsock`, `quic`, etc) and most of these can be [encrypted](../Network/Encryption.md) and multiplexed through a single port.
The safest option will depend on the type of xpra client connecting - but generally speaking, `ssl`, `quic` and `ssh` are considered the safest as they provide host verification and encryption in one protocol.
Each connection can also combine any number of [authentication modules](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md#authentication-modules).

### [Logging](Logging.md) and diagnostics
Debugging tools and diagnostics can sometimes be at odds with good security practices. When that happens, we usually [err on the side of caution](https://github.com/Xpra-org/xpra/issues/1939) but not always when it affects usability: [http scripts information disclosure](https://github.com/Xpra-org/xpra/pull/3156)
The extensive [debug logging](Logging.md) capabilities normally obfuscate sensitive information like passwords and keys,
but it may still be possible to glean enough data to be present a real risk. A good preventative measure is to disable remote logging and turn off the server's control channel (#3573).
The xpra shell is a very powerful debugging feature which allows full access to all the data structures held in the client and server. It is disabled by default.

### Malicious clients and servers
Servers should be using authentication, so typically this means that malicious clients have had their authentication credentials compromised or perhaps the whole clients is compromised.
Clients should be using SSL certificates or SSH host keys to verify the identity of a server. A malicious server would be one that has been compromised or which is running a compromised application (ie: a browser).

As per the list above, if the specific subsystem is not disabled, a malicious actor may be able to:
* collect information about the remote peer: xpra and library versions, network connection, etc
* send malicious files to be downloaded or opened by the client, documents to be printed
* send notifications trying to impersonate local applications or to mislead the client
* monitor all application or client clipboard transfers and copy the data
* play a misleading audio stream, etc
Moreover, a malicious server would be able to easily take screen captures of all applications, record all pointer events and keystrokes - making it relatively easy to capture any credentials typed into the session.

### Options
Some specific options have a direct impact on the security of the system:
* `start-new-commands` this is precisely a remote command execution and should be disabled if the client is not trusted
* `terminate-children` should be used to prevent child commands from lingering - most commands are killed when their connection to the display is terminated, but some may survive
* `exit-with-children` to terminate servers when applications are closed
* `exit-with-client` to terminate when clients exit
* `idle-timeout` to prevent unused client sessions from consuming server resources
* `server-idle-timeout` to prevent unused servers from consuming resources
* `start-via-proxy` causes the sessions to be registered with the system's login service, which usually has the effect of moving them to their own session control group
* `systemd-run` runs the server in a transient systemd scope unit
* `proxy-start-sessions=yes|no` should be disabled if only existing sessions should be accessed via the proxy server
* `daemon`, `chdir`, `pidfile`, `log-dir` and `log-file`: the server's filesystem context
* `remote-xpra` the command executed from client SSH connections
* `source=SOURCE` and `env=ENV`: anything that modifies the server's environment variables can potentially be used to subvert the server process
* `source-start=SOURCE_START`, `start-env=START_ENV`: as above, but for commands started by the server
* `mdns` will advertise sessions on local networks
* `readonly` sessions are unable to receive any keyboard or pointer input
* `sharing` and `lock` control if and when sessions are transferred between clients
* `border`, `min-size`, `max-size`, `modal-windows`: to distinguish and constrain remote windows
* `challenge-handlers` to restrict the type of authentication mechanisms the client will use (ie: prevent password prompts)
* `uinput` virtual devices should be avoided as they can be used to inject input events into a system at a lower level
</details>


---

## Platforms

<details>
  <summary>binaries, anti-viruses, system-integration, etc</summary>

### [Build options](../Build)
By default, xpra is built using strict compilation options and any warning will cause the build to fail (`-Werror`).
Whenever needed or required (libraries missing in a specific distribution or variant thereof),
the xpra project provides up-to-date versions of key libraries on many platforms: https://github.com/Xpra-org/xpra/tree/master/packaging/ and not just xpra. That said, binaries..

### Binaries - MS Windows and MacOS
The distribution of binary bundles applies to MS Windows, MacOS builds and also on Linux when using formats like `appimage`, `flatpak`, `snap` (these formats are not currently supported, in part because of this particular problem) or - to a lesser extent - with container builds.
The issue here is that by bundling all these libraries into one container format (ie: `EXE` or `DMG`), it becomes impossible to propagate library updates in a timely manner.
This means that it may take weeks or months before the patch for a zero-day exploit is deployed.
Sadly, this is not a theoretical issue: [pdfium 0-day](https://github.com/Xpra-org/xpra/issues/2470), [putty vulnerability](https://github.com/Xpra-org/xpra/issues/2222), [tortoisesvn unpatched security fix](https://github.com/Xpra-org/xpra/commit/ac9b2f86b19bdad8194f494ecf57877eaa577b81) and many many more.
The MS Windows libraries are maintained by [MSYS2](https://www.msys2.org/), the MacOS libraries are maintained using our fork of [gtk-osx-build](https://github.com/Xpra-org/gtk-osx-build)

### Anti-viruses
Because of the way xpra intercepts and injects pointer and keyboard events - and the API it uses to perform these tasks, it is regularly misidentified as malware:
[f-secure and bitdefender false-positive](https://github.com/Xpra-org/xpra/issues/2088#issuecomment-765511350), [Microsoft AI](https://github.com/Xpra-org/xpra/issues/2781#issuecomment-765546100), [Windows Defender: Trojan](https://github.com/Xpra-org/xpra/issues/4477)

### [HTML5](https://github.com/Xpra-org/xpra-html5)
The builtin web server ships with fairly restrictive [http headers and content security policy](https://github.com/Xpra-org/xpra/issues/1741), even [blocking some valid use cases by default](https://github.com/Xpra-org/xpra/issues/3442) - though we could [go even further](https://github.com/Xpra-org/xpra/issues/3100).
For security issues related to the html5 client, please refer to [xpra-html5 project issues](https://github.com/Xpra-org/xpra-html5/issues)

### SELinux
On Linux systems that support it, xpra includes an SELinux policy to properly confine
its server process whilst still giving it access to the paths and sockets it needs to function: https://github.com/Xpra-org/xpra/tree/master/fs/share/selinux

### System Integration
The xpra server and client(s) can both be embedded with or integrated into other sotware components, this completely changes the security profile of the solution.
For example:
* By using an external websocket proxy (ie: [Apache HTTP Proxy](Apache-Proxy.md)) one can shield the xpra server from potentially hostile external traffic and add a separately configured authentication layer with only minimal latency costs (when configured properly)
* Xpra's own [proxy server](Proxy-Server.md) can be used to provide hardware acceleration within a different context than the one that is executing user applications.
* Running the [system-wide proxy server](Service.md) provides tighter integration into the system's session service, which has both pros and cons: potentially better session accounting and control, at the cost of running a privileged service
* OpenGL hardware acceleration via [WSL - Windows Subsystem for Linux](WSL.md)

### Containers - VM
Using containers or virtual machines is a very popular way of deploying xpra, both offer a strong extra security layer which can also be used to restrict access to system resources - though this limited access to the underlying hardware also restricts hardware acceleration options.

</details>


---


## Vulnerabilities
It is difficult to keep track of all the security related issues that have affected the project over the years. \
Some have been assigned CVEs, most have not. \
Likewise, it is quite hard to keep track of all the bugs affecting the libraries xpra is built on. But here are some examples:
* [Rencode Denial Of Service](https://packetstormsecurity.com/files/164084/) - [rencode segfault](https://github.com/Xpra-org/xpra/issues/1217)
* [brotli integer overflow](https://github.com/Xpra-org/xpra/commit/781fb67827f891f427c66d9988b8423049954b64).

(see also the "binaries" paragraph above which has more platform specific examples)

By and large, the biggest concern is the complete lack of security updates from [downstream distributions](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages) - even when faced with [serious system crashes](https://github.com/Xpra-org/xpra/issues/2834).
