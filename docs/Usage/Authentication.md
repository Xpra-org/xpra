# ![Authentication](../images/icons/authentication.png) Authentication

Xpra's authentication modules can be useful for:
* securing socket connections
* making the unix domain socket accessible to other users safely
* using the [proxy server](Proxy-Server.md)

For more information on the different types of connections, see [network](../Network/README.md). For more generic security information, please see [security considerations](Security.md)

SSL mode can also be used for authentication using certificates (see #1252)

When using [SSH](../Network/SSH.md) to connect to a server, [encryption](../Network/Encryption.md) and authentication can be skipped: by default the unix domain sockets used by ssh do not use authentication.

***

## Server Syntax
Starting with version 4.0, the preferred way of specifying authentication is within the socket option itself. \
ie for starting a [seamless](Seamless.md) server with a `TCP` socket protected by a password stored in a `file`:
```shell
xpra start --start=xterm -d auth
     --bind-tcp=0.0.0.0:10000,auth=file,filename=password.txt
```
So that multiple sockets can use different authentication modules, and those modules can more easily be chained:
```shell
xpra start --start=xterm -d auth \
     --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file,filename=password.txt \
     --bind-tcp=0.0.0.0:10001,auth=sys
```

### Server Authentication Modules
Xpra supports many authentication modules.
Some of these modules require extra [dependencies](../Build/Dependencies.md).
<details>
  <summary>server authentication modules</summary>

| Module                                                                                           | Result                                                                                  | Purpose                                                                             |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [allow](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/allow.py)                         | always allows the user to login, the username used is the one supplied by the client    | dangerous / only for testing                                                        |
| [none](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/none.py)                           | always allows the user to login, the username used is the one the server is running as  | dangerous / only for testing                                                        |
| [fail](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/fail.py)                           | always fails authentication, no password required                                       | useful for testing                                                                  |
| [reject](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/reject.py)                       | always fails authentication, pretends to ask for a password                             | useful for testing                                                                  |
| [env](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/env.py)                             | matches against an environment variable (`XPRA_PASSWORD` by default)                    | alternative to file module                                                          |
| [password](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/password.py)                   | matches against a password given as a module option, ie: `auth=password,value=mysecret` | alternative to file module                                                          |
| [multifile](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/multifile.py)                 | matches usernames and passwords against an authentication file                          | proxy: see password-file below                                                      |
| [file](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/file.py)                           | compares the password against the contents of a password file, see password-file below  | simple password authentication                                                      |
| [pam](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/pam.py)                             | linux PAM authentication                                                                | Linux system authentication                                                         |
| [win32](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/win32.py)                         | win32security authentication                                                            | MS Windows system authentication                                                    |
| `sys`                                                                                            | system authentication                                                                   | virtual module which will choose win32 or pam authentication automatically          |
| [sqlite](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sqlite.py)                       | sqlite database authentication                                                          | [#1488](https://github.com/Xpra-org/xpra/issues/1488#issuecomment-765477498)        |
| [sql](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sqlite.py)                          | sqlalchemy database authentication                                                      | [#2288](https://github.com/Xpra-org/xpra/issues/2288)                               |
| [mysql](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sqlite.py)                        | MySQL database authentication                                                           | [#2287](https://github.com/Xpra-org/xpra/issues/2287)                               |
| [capability](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/capability.py)               | matches values in the capabilities supplied by the client                               | [#3575](https://github.com/Xpra-org/xpra/issues/3575#issuecomment-1183292333)       |
| [peercred](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/peercred.py)                   | `SO_PEERCRED` authentication                                                            | [#1524](https://github.com/Xpra-org/xpra/issues/issues/1524)                        |
| [hosts](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/hosts.py)                         | [TCP Wrapper](https://en.wikipedia.org/wiki/TCP_Wrapper)                                | [#1730](https://github.com/Xpra-org/xpra/issues/issues/1730#issuecomment-765492022) |
| [exec](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/exec.py)                           | Delegates to an external command                                                        | [#1690](https://github.com/Xpra-org/xpra/issues/1690)                               |
| [kerberos-password](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/kerberos_password.py) | Uses kerberos to authenticate a username + password                                     | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [kerberos-token](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/kerberos_token.py)       | Uses a kerberos ticket to authenticate a client                                         | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [gss](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/gss.py)                             | Uses a GSS ticket to authenticate a client                                              | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [keycloak](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/keycloak.py)                   | Uses a keycloak token to authenticate a client                                          | [#3334](https://github.com/Xpra-org/xpra/issues/3334)                               |
| [ldap](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/ldap.py)                           | Uses ldap via [python-ldap](https://www.python-ldap.org/en/latest/)                     | [#1791](https://github.com/Xpra-org/xpra/issues/1791)                               |
| [ldap3](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/ldap3.py)                         | Uses ldap via [python-ldap3](https://github.com/cannatag/ldap3)                         | [#1791](https://github.com/Xpra-org/xpra/issues/1791)                               |
| [u2f](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/u2f.py)                             | [Universal 2nd Factor](https://en.wikipedia.org/wiki/Universal_2nd_Factor)              | [#1789](https://github.com/Xpra-org/xpra/issues/1789)                               |
| [otp](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/otp.py)                             | One Time Password                                                                       | [pyotp](https://github.com/pyauth/pyotp)                                            |
| [http-header](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/http-header.py)             | validate websocket http headers                                                         | [#4438](https://github.com/Xpra-org/xpra/issues/4438)                               |
</details>

<details>
  <summary>more examples</summary>

* `XPRA_PASSWORD=mysecret xpra start --bind-tcp=0.0.0.0:10000,auth=env`
* `SOME_OTHER_ENV_VAR_NAME=mysecret xpra start --bind-tcp=0.0.0.0:10000,auth=env,name=SOME_OTHER_ENV_VAR_NAME`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=password,value=mysecret`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=file,filename=/path/to/mypasswordfile.txt`
* `xpra start --bind-tcp=0.0.0.0:10000,auth=sqlite,filename=/path/to/userlist.sdb`

Beware when mixing environment variables and password files as the latter may contain a trailing newline character whereas the former often do not.
</details>

<details>
  <summary>syntax for older versions</summary>

The syntax with older versions used a dedicated switch for each socket type:
* `--auth=MODULE` for unix domain sockets and named pipes
* `--tcp-auth=MODULE` for TCP sockets
* `--vsock-auth=MODULE` for vsock (#983)
etc

For more information on the different socket types, see [network examples](../Network)
</details>

***

## Client Syntax

By default, `challenge-handlers=all` which means that the python client will try all authentication handlers available until one succeeds.
If the server is configured with multiple authentications modules for the same socket, the client will do the same.

### Basic examples
Authenticating as username `foo` with password `bar` using the URI:
```shell
xpra attach tcp://foo:bar@host:port/
```
For a more secure option, storing the password value in a file, with debugging enabled:
```shell
echo -n "foo" > ./password.txt
xpra attach tcp://host:port/ --challenge-handlers=file:filename=./password.txt --debug auth
```

<details>
  <summary>client challenge handlers</summary>

| Module                                                                              | Behaviour and options                                                                                    |
|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [env](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/env.py)           | `name` specifies the environment variable containing the password<br/>defaults to `XPRA_PASSWORD`        |
| [file](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/file.py)         | `filename` specifies the file containing the passowrd                                                    |
| [gss](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/gss.py)           | use `gss-services` to specify the name of the security context                                           |
| [kerberos](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/kerberos.py) | `kerberos-services` specifies the valid kerberos services to connect to<br/>the wildcard `*` may be used |
| [prompt](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/prompt.py)     | GUI clients should see a dialog, console users a text prompt                                             |
| [u2f](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/u2f.py)           | `APP_ID` specifies the u2f authentication application ID                                                 |
| [uri](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/uri.py)           | Uses values parsed from the connection string, ie: `tcp://foo:bar@host`                                  |
</details>

***

### Password File

* with the `file` module, the password-file contains a single password, the whole file is the password (including any trailing newline characters). To write a password to a file without the trailing newline character, you can use `echo -n "thepassword" > password.txt`
* with `multifile`, the password-file contains a list of authentication values, see [proxy server](Proxy-Server) - this module is deprecated in favour of the `sqlite` module which is much easier to configure

### Usernames
The username can be specified:
* in the connection files you can save from the launcher
* in the client connection string
<details>
  <summary>tcp example</summary>

```shell
xpra attach tcp://username:password@host:port/
```
</details>

When an authentication module is used to secure a single session, many modules will completely ignore the username part, and it can be omitted from the connection string.
This [can be overriden for some modules](https://github.com/Xpra-org/xpra/issues/4294).
<details>
  <summary>example: specifying the password only</summary>

for connecting to the `TCP` socket and specifying the password only:
```shell
xpra attach tcp://:password@host:port/
```
Since the username is ignored, it can also be replaced with any string of your liking, ie using `foobar` here:
```shell
xpra attach tcp://foobar:password@host:port/
```
</details>

Only the following modules will make use of both the username and password to authenticate against their respective backend: `kerberos-password`, `ldap`, `ldap3`, `sys` (`pam` and `win32`), `sqlite`, `multifile` and `u2f`.
In this case, using an invalid username will cause the authentication to fail.

The username is usually more relevant when authenticating against a [proxy server](Proxy-Server.md) (see authentication details there).


***

## Development Documentation
<details>
  <summary>Authentication Process</summary>

The steps below assume that the client and server have been configured to use authentication:
* if the server is not configured for authentication, the client connection should be accepted and a warning will be printed
* if the client is not configured for authentication, a password dialog may show up, and the connection will fail with an authentication error if the correct value is not supplied
* if multiple authentication modules are specified, the client may bring up multiple authentication dialogs
* how the client handles the challenges sent by the server can be configured using the `challenge-handlers` option, by default the client will try the following handlers in the specified order: `uri` (whatever password may have been specified in the connection string), `file` (if the `password-file` option was used), `env` (if the environment variable is present), `kerberos`, `gss`, `keycloak`, `u2f` and finally `prompt`
</details>
<details>
  <summary>module and platform specific notes</summary>

* this information applies to all clients except the HTML5 client: regular GUI clients as well as command line clients like `xpra info`
* each authentication module specifies the type of password hashing it supports (usually [HMAC](https://en.wikipedia.org/wiki/Hash-based_message_authentication_code))
* some authentication modules (`pam`, `win32`, `kerberos-password`, `ldap` and `ldap3`) require the actual password to be sent across to perform the authentication on the server - they therefore use the weak `xor` hashing, which is insecure
* you must use [encryption](../Network/Encryption.md) to be able to use `xor` hashing so that the password is protected during the exchange: the system will refuse to send a `xor` hashed password unencrypted
* encryption is processed before authentication
* when used over TCP sockets, password authentication is vulnerable to man-in-the-middle attacks where an attacker could intercept the initial exchange and use the stolen authentication challenge response to access the session, [encryption](../Network/Encryption.md) prevents that
* the client does not verify the authenticity of the server, using [encryption](../Network/Encryption.md) effectively does
* enabling `auth` [debug logging](Logging.md) may leak some authentication information
* if you are concerned about security, use [SSH](../Network/SSH.md) as transport instead

For more information on packets, see [network](../Network/README.md).
</details>
<details>
  <summary>Salt handling is important</summary>

* [64-bit entropy is nowhere near enough against a serious attacker](https://crypto.stackexchange.com/a/34162/48758): _If you want to defend against rainbow tables, salts are inevitable, because you need a full rainbow table per unique salt, which is computationally and storage-wise intense_
* [SHA-512 w/ per User Salts is Not Enough](https://blog.mozilla.org/security/2011/05/10/sha-512-w-per-user-salts-is-not-enough/): _In the event the hash was disclosed or the database was compromised, the attacker will already have one of the two values (i.e. the salt), used to construct the hash_
* [about hmac](https://news.ycombinator.com/item?id=1998198): _Those people should know that HMAC is as easy to precompute as naked SHA1 is; you can "rainbow-table" `HMAC_*` and we did get it wrong before...
</details>
