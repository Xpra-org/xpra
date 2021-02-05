![Authentication](https://xpra.org/icons/authentication.png)

Xpra's authentication modules can be useful for:
* securing socket connections
* making the unix domain socket accessible to other users safely
* using the [proxy server](./Proxy-Server.md)

For more information on the different types of connections, see [network](../Network/README.md)

SSL mode can also be used for authentication using certificates (see #1252)

When using [SSH](../Network/SSH.md) to connect to a server, [encryption](../Network/Encryption.md) and authentication can be skipped: by default the unix domain sockets used by ssh do not use authentication.

# Modules
Here are the modules that can be used:
|Module|Result|Purpose|Version requirements|
|------|------|-------|--------------------|
|[allow](../../blob/master/xpra/server/auth/allow_auth.py)|always allows the user to login, the username used is the one supplied by the client|dangerous / only for testing|
|[none](../../blob/master/xpra/server/auth/none_auth.py)|always allows the user to login, the username used is the one the server is running as||dangerous / only for testing|
|[fail](../../blob/master/xpra/trunk/src/xpra/server/auth/fail_auth.py)|always fails authentication, no password required|useful for testing|
|[reject](../../blob/master/xpra/trunk/src/xpra/server/auth/reject_auth.py)|always fails authentication, pretends to ask for a password|useful for testing|
|[env](../../blob/master/xpra/trunk/src/xpra/server/auth/env_auth.py)|matches against an environment variable (`XPRA_PASSWORD` by default)|alternative to file module|
|[password](../../blob/master/xpra/trunk/src/xpra/server/auth/password_auth.py)|matches against a password given as a module option, ie: `auth=password:value=mysecret`|alternative to file module|
|[multifile](../../blob/master/xpra/trunk/src/xpra/server/auth/multifile_auth.py)|matches usernames and passwords against an authentication file|proxy: see password-file below|
|[file](../../blob/master/xpra/server/auth/file_auth.py)|compares the password against the contents of a password file, see password-file below|simple password authentication|
|[pam](../../blob/master/xpra/trunk/src/xpra/server/auth/pam.py)|linux PAM authentication|Linux system authentication|
|[win32](../../blob/master/xpra/trunk/src/xpra/server/auth/win32_auth.py)|win32security authentication|MS Windows system authentication|
|`sys`|system authentication|virtual module which will choose win32 or pam authentication automatically|
|[sqlite](../../blob/master/xpra/trunk/src/xpra/server/auth/sqlite_auth.py)|sqlite database authentication|[#1488](../https://github.com/Xpra-org/xpra/issues/1488#issuecomment-765477498)|
|[peercred](../../blob/master/xpra/trunk/src/xpra/server/auth/peercred_auth.py)|`SO_PEERCRED` authentication|
|[tcp hosts](../../blob/master/xpra/trunk/src/xpra/server/auth/hosts_auth.py)|[TCP Wrapper](https://en.wikipedia.org/wiki/TCP_Wrapper)|[#1730](../https://github.com/Xpra-org/xpra/issues/issues/1730#issuecomment-765492022)|
|[exec](../../blob/master/xpra/server/auth/exec_auth.py)|Delegates to an external command|[#1690](../https://github.com/Xpra-org/xpra/issues/1690)|
|[kerberos-password](../../blob/master/xpra/server/auth/kerberos_password_auth.py)|Uses kerberos to authenticate a username + password|[#1691](../https://github.com/Xpra-org/xpra/issues/1691)|
|[kerberos-ticket](../../blob/master/xpra/server/auth/kerberos_ticket_auth.py)|Uses a kerberos ticket to authenticate a client|[#1691](../https://github.com/Xpra-org/xpra/issues/1691)|
|[gss_auth](../../blob/master/xpra/trunk/src/xpra/server/auth/gss_auth.py)|Uses a GSS ticket to authenticate a client|[#1691](../https://github.com/Xpra-org/xpra/issues/1691)|
|[ldap](../../blob/master/xpra/server/auth/ldap_auth.py)|Uses ldap via [python-ldap](https://www.python-ldap.org/en/latest/)|[#1791](../https://github.com/Xpra-org/xpra/issues/1791)|
|[ldap3](../../blob/master/xpra/server/auth/ldap3_auth.py)|Uses ldap via [python-ldap3](https://github.com/cannatag/ldap3)|[#1791](../https://github.com/Xpra-org/xpra/issues/1791)|
|[u2f](../../blob/master/xpra/trunk/src/xpra/server/auth/u2f_auth.py)|[Universal 2nd Factor](https://en.wikipedia.org/wiki/Universal_2nd_Factor)|[#1789](../https://github.com/Xpra-org/xpra/issues/1789)|


## Syntax
Starting with version 4.0, the preferred way of specifying authentication is within the socket option itself. \
ie for starting a [seamless](./Seamless.md) server with a `TCP` socket protected by a password stored in a file:

    xpra start --start=xterm -d auth
         --bind-tcp=0.0.0.0:10000,auth=file:filename=password.txt

So that multiple sockets can use different authentication modules, and those modules can more easily be chained:

    xpra start --start=xterm -d auth \
         --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file:filename=password.txt --bind 
         --bind-tcp=0.0.0.0:10001,auth=sys

More examples:
* `XPRA_PASSWORD=mysecret xpra start --bind-tcp=0.0.0.0:10000,auth=env`
* `SOME_OTHER_ENV_VAR_NAME=mysecret xpra start --bind-tcp=0.0.0.0:10000,auth=env:name=SOME_OTHER_ENV_VAR_NAME`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=password:value=mysecret`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=file:filename=/path/to/mypasswordfile.txt`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=sqlite:filename=/path/to/userlist.sdb`

Beware when mixing environment variables and password files as the latter may contain a trailing newline character whereas the former often do not.

***
### Older versions
The syntax with older versions uses a dedicated switch for each socket type:
* `--auth=MODULE` for unix domain sockets and named pipes
* `--tcp-auth=MODULE` for TCP sockets
* `--vsock-auth=MODULE` for vsock (#983)
etc

For more information on the different socket types, see [network examples](./Network)


## Password File

* with the `file` module, the password-file contains a single password, the whole file is the password (including any trailing newline characters)
* with `multifile`, the password-file contains a list of authentication values, see [proxy server](./ProxyServer) - this module is deprecated in favour of the `sqlite` module which is much easier to configure

## Usernames
The username can be specified in the connection files you can save from the launcher, or in the client connection string, ie for tcp:

    xpra attach tcp://username:password@host:port/

When an authentication module is used to secure a single session, many modules will completely ignore the username part and it can be omitted from the connection string. ie for connecting to the `TCP` socket of a session secured using `password-file`:

    xpra attach tcp://:password@host:port/

Or even replaced with any string of your liking, ie 'foobar':

    xpra attach tcp://foobar:password@host:port/


Only the following modules will make use of both the username and password to authenticate against their respective backend: `kerberos-password`, `ldap`, `ldap3`, `sys` (`pam` and `win32`), `sqlite`, `multifile` and `u2f`.
In this case, using an invalid username will cause the authentication to fail.

The username is usually more relevant when authenticating against a [proxy server](./ProxyServer) (see authentication details there).


***

# Authentication Process

The steps below assume that the client and server have been configured to use authentication:
* if the server is not configured for authentication, the client connection should be accepted and a warning will be printed
* if the client is not configured for authentication, a password dialog may show up, and the connection will fail with an authentication error if the correct value is not supplied
* if multiple authentication modules are specified, the client may bring up multiple authentication dialogs
* how the client handles the challenges sent by the server can be configured using the `challenge-handlers` option, by default the client will try the following handlers in the specified order: `uri` (whatever password may have been specified in the connection string), `file` (if the `password-file` option was used), `env` (if the environment variable is present), `kerberos`, `gss`, `u2f` and finally `prompt`

## Notes
* this information applies to all clients except the HTML5 client: regular GUI clients as well as command line clients like `xpra info`
* each authentication module specifies the type of password hashing it supports (usually [HMAC](https://en.wikipedia.org/wiki/Hash-based_message_authentication_code))
* some authentication modules (`pam`, `win32`, `kerberos-password`, `ldap` and `ldap3`) require the actual password to be sent across to perform the authentication on the server - they therefore use the weak `xor` hashing, which is insecure
* you must use [encryption](../Network/Encryption.md) to be able to use `xor` hashing so that the password is protected during the exchange: the system will refuse to send a `xor` hashed password unencrypted
* encryption is processed before authentication
* when used over TCP sockets, password authentication is vulnerable to man-in-the-middle attacks where an attacker could intercept the initial exchange and use the stolen authentication challenge response to access the session, [encryption](../Network/Encryption.md) prevents that
* the client does not verify the authenticity of the server, using [encryption](../Network/Encryption.md) effectively does
* enabling `auth` [debug logging](./Logging.md) may leak some authentication information
* if you are concerned about security, use [SSH](../Network/SSH.md) as transport instead

For more information on packets, see [network](../Network/README.md).

## Salt handling is important
* [64-bit entropy is nowhere near enough against a serious attacker](https://crypto.stackexchange.com/a/34162/48758): _If you want to defend against rainbow tables, salts are inevitable, because you need a full rainbow table per unique salt, which is computationally and storage-wise intense_
* [SHA-512 w/ per User Salts is Not Enough](https://blog.mozilla.org/security/2011/05/10/sha-512-w-per-user-salts-is-not-enough/): _In the event the hash was disclosed or the database was compromised, the attacker will already have one of the two values (i.e. the salt), used to construct the hash_
* [about hmac](https://news.ycombinator.com/item?id=1998198): _Those people should know that HMAC is as easy to precompute as naked SHA1 is; you can "rainbow-table" HMAC_* and we did get it wrong before...
