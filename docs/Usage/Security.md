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
When features are disabled, they are not just unused, they are [not even loaded in memory](https://github.com/Xpra-org/xpra/issues/1861#issuecomment-76549942500) in the first place. Those subsystem interfaces cannot be abused since they don't even exist in that process space - very much like when features are not installed on the system.  
For details, see [dynamic client connection class](https://github.com/Xpra-org/xpra/issues/2351) and [completely skip server base classes](https://github.com/Xpra-org/xpra/issues/1838)
The same applies to codecs and other swappable components - more on that below.

## [Clipboard](../Features/Clipboard.md)
Obviously, from a security perspective, the safest clipboard is one that is disabled (`--clipboard=no`)
but that is not always an acceptable compromise for end users, in which case limiting the `--clipboard-direction` may be enough.
Beyond this, there are many other tunables in the [clipboard subsystem](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard)
and its various OS specific implementations. This can be used to restrict the rate and size of the data transferred, filter out certain types of contents,
select which clipboards can be accessed (for platforms that support more than one clipboard type), the type of data exchanged, etc..

## [Audio](../Features/Audio.md)
Very much like the clipboard, the safest way to handle audio is to not forward it at all.  
If audio forwarding has to be enabled, not all codecs are equal from a security point of view.  
Using a codec without a container reduces the complexity somewhat, but using a raw audio format like `wav` is the safest option since there is no parsing involved. The downside is that this is an uncompressed format, though xpra does offer the option to compress `wav` using `lz4`.
That said, `mp3` is now over 30 years old and the libraries parsing it are very mature. Other codecs have had a few issues in more recent times (ie: [faac and faad2 security issues](https://github.com/Xpra-org/xpra/issues/2474)  
xpra runs the audio processing in a separate process which does not have access to the display.

## Modes
Some features are harder to implement correctly in [seamless mode](./Seamless.md) because of the inherent complexity when handling windows client side. (ie: [window resizing vs readonly mode](https://github.com/Xpra-org/xpra/issues/2137))  
For that reason, it may be worth considering [desktop mode](./Start-Desktop.md)

## Diagnostics
Debugging tools and diagnostics can sometimes be at odds with good security practices.  
When that happens, we [err on the side of caution](https://github.com/Xpra-org/xpra/issues/1939)

## Tests
Although the test coverage is not as high as we would like, there are comprehensive unit tests that test individual narrow code paths and other tests that will exercise the client and server code end-to-end, including the network layer.
More details in [client-server mixin tests](https://github.com/Xpra-org/xpra/issues/2357), [better unit tests](https://github.com/Xpra-org/xpra/issues/2362)

## Binaries - MS Windows and MacOS
The distribution of binary bundles applies to MS Windows, MacOS builds and also on Linux when using formats like `appimage`, `flatpak`, `snap` (these formats are not currently supported, in part because of this problem) or - to a lesser extent - with container builds.  
The issue here is that by bundling all these libraries into one container format (ie: `EXE` or `DMG`), it becomes impossible to propagate library updates in a timely manner.
This means that it may take weeks or months before the patch for a zero-day exploit is deployed.  
This is not a theoretical issue, ie: [pdfium 0-day](https://github.com/Xpra-org/xpra/issues/2470), [putty vulnerability](https://github.com/Xpra-org/xpra/issues/2222) and many many more.

## Anti-viruses
Because of the way xpra intercepts and injects pointer and keyboard events to do its job, it is regularly misidentified as malware:
[f-secure and bitdefender false-positive](https://github.com/Xpra-org/xpra/issues/2088#issuecomment-765511350), [Microsoft AI](https://github.com/Xpra-org/xpra/issues/2781#issuecomment-765546100)

## Vulnerabilities
It is difficult to keep track of all the security related issues that have affected the project over the years.
Some have been assigned CVEs, most have not.  
Likewise, it is quite hard to keep track of all the bugs affecting the libraries xpra is built on (ie: [Rencode Denial Of Service](https://packetstormsecurity.com/files/164084/) - [rencode segfault](https://github.com/Xpra-org/xpra/issues/1217)).  
