# Security considerations

A significant proportion of Xpra's development was sponsored by the security industry to provide a shield for users running applications with network access - the xpra clients are only exposed to a tightly controlled and secure network flux,
completely removed from the underlying protocols that those applications normally use to interact with the user.  
As a result, the architecture, features and options are often directly related to the mechanisms allowing this fine grained control.  
Equally, a server should be quite well protected from a hostile client.

A default installation should be quite secure by default, but the are trade-offs to be made.
Some specific subsystems also deserve their own details.

## Clipboard
Obviously, from a security perspective, the safest clipboard is one that is disabled (`--clipboard=no`)
but that is not always an acceptable compromise for end users, in which case limiting the `--clipboard-direction` may be enough.
Beyond this, there are many other tunables in the [clipboard subsystem](https://github.com/Xpra-org/xpra/tree/master/xpra/clipboard)
and its various OS specific implementations. This can be used to restrict the rate and size of the data transferred, filter out certain types of contents,
select which clipboards can be accessed (for platforms that support more than one clipboard type), the type of data exchanged, etc..

TBC
