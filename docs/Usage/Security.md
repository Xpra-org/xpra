# Security considerations

A significant proportion of Xpra's development was sponsored by the security industry to provide a shield for users running applications with network access - the xpra clients are only exposed to a tightly controlled and secure network flux,
completely removed from the underlying protocols that those applications normally use to interact with the user.  
As a result, the architecture, features and options are often directly related to the mechanisms allowing this fine grained control.  
Equally, a server should be quite well protected from a hostile client.

A default installation should be quite secure by default, but the are trade-offs to be made.
Some specific subsystems also deserve their own details.
One common theme is that it is impossible to take advantage of a feature or subsystem that isn't available.

## Architecture
The way xpra is structured into independent python sub-modules allows it to partition off each subsystem.  
When features are disabled, they are not just unused, they are [not even loaded into memory](https://github.com/Xpra-org/xpra/issues/1861#issuecomment-76549942500) in the first place. Those subsystem interfaces cannot be abused since they don't even exist in that process space - very much like when features are not installed on the system at all.  
For details, see [dynamic client connection class](https://github.com/Xpra-org/xpra/issues/2351) and [completely skip server base classes](https://github.com/Xpra-org/xpra/issues/1838)
The same principle applies to [codecs and all swappable components](https://github.com/Xpra-org/xpra/issues/614).  
Moreover, the use of pure Python code for the vast majority of the data handling completely prevents whole classes of vulnerabilities. The parts of the code that do require high performance (data mangling, (de)compression, etc) use heavily optimized libraries (see _audio_ and _encodings_ below).  

## Subsystems
Most of the features below have explicit command line switches which can be used to completely disable the subsystem, to start with the feature turned off so as to require an explicit user action to turn it on, or to restrict the feature.  
If a client or server turns off a subsystem then the remote end cannot enable the feature. Some switches only affect the on / off state of the feature instead, which does allow for the feature to be enabled through a user action once the connection is established.  
These toggles may also be accessible through the server's control channel and dbus interface.

### [Clipboard](../Features/Clipboard.md)
Obviously, from a security perspective, the safest clipboard is one that is disabled (`--clipboard=no`)
but that is not always an acceptable compromise for end users, in which case limiting the `--clipboard-direction` may be enough.
Beyond this, there are many other tunables in the [clipboard subsystem](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard)
and its various OS specific implementations. This can be used to restrict the rate and size of the data transferred, filter out certain types of contents,
select which clipboards can be accessed (for platforms that support more than one clipboard type), the type of data exchanged, etc..

### [Audio](../Features/Audio.md)
Very much like the clipboard, the safest way to handle audio is to not forward it at all.  
If audio forwarding has to be enabled, not all codecs are equal from a security point of view.  
Using a codec without a container reduces the complexity somewhat, but using a raw audio format like `wav` is the safest option since there is no parsing involved. The downside is that this is an uncompressed format, though xpra does offer the option to compress `wav` using `lz4`.
That said, `mp3` is now over 30 years old and the libraries parsing it are very mature. Other codecs have had a few issues in more recent times (ie: [faac and faad2 security issues](https://github.com/Xpra-org/xpra/issues/2474)  
xpra runs the audio processing in a separate process which does not have access to the display.

### [Encodings](./Encodings.md)
Xpra supports a large number of picture and video codecs as well as raw uncompressed pixel data.  
Each option has different strengths and weaknesses. The raw options `rgb` and `mmap` are obviously the safest since they do not require any parsing, but they can require humongous amounts of bandwidth (ie: tens of Gbps for a 4K window).  
Older picture encodings like `png` and `jpeg` are probably the safests due to their maturity.
Video encodings as well as newer picture encodings derived from the same technologies (like `webp` and `avif`) are probably less safe due to their complexity.

### [Printing](../Features/Printing.md)
Printer forwarding presents security challenges for both the server and the client:
* the server parses printer data from the client and then uses privileged commands to create an equivallent virtual printer. The client can also update the list of printers at any time, causing the whole setup process to be repeated.
* the client receives Postscript or PDF files which are sent to the real printer, this is compartively quite safe 

### [File Transfers](../Features/File-Transfers.md)
This feature has potential for abuse in both directions which is why there are many options to restrict what can be done with it.  
File transfers can be disabled completely which is obviously the safest option.
The default settings allow file transfers but a user confirmation is requested first before accepting a file or opening it.
The file size and number of concurrent file transfers can also be configured.

### [System Tray](../Features/System-Tray.md) and [Notifications](../Features/Notifications.md) forwarding
These features provide tighter desktop integration which can be seen as a security risk and can be turned off completely.  
However, the improved usability usually makes this an acceptable trade off.

### [Webcam](../Features/Webcam.md)
Although this feature is never turned on by default, it is available.  
There are obvious privacy concerns here and it may be desirable to turn off the feature completely.

### `DBus`
"_D-Bus is a message bus system, a simple way for applications to talk to one another_.
_In addition to interprocess communication, D-Bus helps coordinate process lifecycle_."
This makes `dbus` both a very useful desktop environment component and a wide attack target.  
The limited `--dbus-proxy` calls can safely be turned off and the `--dbus-control` channel should be turned off if unused.

---

## Platforms

## Binaries - MS Windows and MacOS
The distribution of binary bundles applies to MS Windows, MacOS builds and also on Linux when using formats like `appimage`, `flatpak`, `snap` (these formats are not currently supported, in part because of this particular problem) or - to a lesser extent - with container builds.  
The issue here is that by bundling all these libraries into one container format (ie: `EXE` or `DMG`), it becomes impossible to propagate library updates in a timely manner.  
This means that it may take weeks or months before the patch for a zero-day exploit is deployed.  
Sadly, this is not a theoretical issue: [pdfium 0-day](https://github.com/Xpra-org/xpra/issues/2470), [putty vulnerability](https://github.com/Xpra-org/xpra/issues/2222), [tortoisesvn unpatched security fix](https://github.com/Xpra-org/xpra/commit/ac9b2f86b19bdad8194f494ecf57877eaa577b81) and many many more.
The MS Windows libraries are maintained by [MSYS2](https://www.msys2.org/), the MacOS libraries are maintained using our fork of [gtk-osx-build](https://github.com/Xpra-org/gtk-osx-build)

## Anti-viruses
Because of the way xpra intercepts and injects pointer and keyboard events - and the API it uses to perform those tasks, it is regularly misidentified as malware:
[f-secure and bitdefender false-positive](https://github.com/Xpra-org/xpra/issues/2088#issuecomment-765511350), [Microsoft AI](https://github.com/Xpra-org/xpra/issues/2781#issuecomment-765546100)

## [HTML5](https://github.com/Xpra-org/xpra-html5)
The builtin web server ships with fairly restrictive [http headers and content security policy](https://github.com/Xpra-org/xpra/issues/1741), even [blocking some valid use cases by default](https://github.com/Xpra-org/xpra/issues/3442).

## SELinux
On Linux systems that support it, xpra includes an SELinux policy to properly confine
its server process whilst still giving it access to the paths and sockets it needs to function: https://github.com/Xpra-org/xpra/tree/master/fs/share/selinux


---


## [Network](../Network) and [Authentication](./Authentication.md)
Xpra supports natively many different types of connections (`tcp`, `ssl`, `ws`, `wss`, `vnc`, `ssh`, `vsock`, etc) and most of these can be [encrypted](../Network/Encryption.md) and multiplexed through a single port. https://github.com/Xpra-org/xpra/blob/master/docs/
The safest options will depend on the type of xpra client connecting - but generally speaking, `ssl` and `ssh` are considered the safest
as they provide host verification and encryption in one protocol.  
Each connection can also combine any number of [authentication modules](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md#authentication-modules).

## Modes
Some features are harder to implement correctly in [seamless mode](./Seamless.md) because of the inherent complexity of handling windows client side and synchronizing their state. (ie: [window resizing vs readonly mode](https://github.com/Xpra-org/xpra/issues/2137))  
For that reason, it may be worth considering [desktop mode](./Start-Desktop.md)

## Diagnostics
Debugging tools and diagnostics can sometimes be at odds with good security practices.  
When that happens, we usually [err on the side of caution](https://github.com/Xpra-org/xpra/issues/1939) but not always when it affects usability: [http scripts information disclosure](https://github.com/Xpra-org/xpra/pull/3156)

## Tests
Although the test coverage is not as high as we would like, there are comprehensive unit tests that test individual narrow code paths and other tests that will exercise the client and server code end-to-end, including the network layer.
More details in [client-server mixin tests](https://github.com/Xpra-org/xpra/issues/2357), [better unit tests](https://github.com/Xpra-org/xpra/issues/2362)

## Vulnerabilities
It is difficult to keep track of all the security related issues that have affected the project over the years.
Some have been assigned CVEs, most have not.  
Likewise, it is quite hard to keep track of all the bugs affecting the libraries xpra is built on. But here are some examples: [Rencode Denial Of Service](https://packetstormsecurity.com/files/164084/) - [rencode segfault](https://github.com/Xpra-org/xpra/issues/1217), [brotli integer overflow](https://github.com/Xpra-org/xpra/commit/781fb67827f891f427c66d9988b8423049954b64).  (see also the "binaries" paragraph above which has more platform specific examples) 
By and large, the biggest concern is the complete lack of security updates from [downstream distributions](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages) - even when faced with [serious system crashes](https://github.com/Xpra-org/xpra/issues/2834).
