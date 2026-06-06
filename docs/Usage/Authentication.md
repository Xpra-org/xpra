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
Starting with version 6.5, options for individual authentication modules can be specified using brackets. \
ie for starting a [seamless](Seamless.md) server with a `TCP` socket protected by a password stored in a `file`:
```shell
xpra seamless --start=xterm -d auth
     --bind-tcp=0.0.0.0:10000,auth=file(filename=password.txt)
```
Multiple sockets can use different authentication modules, and those modules can more easily be chained:
```shell
xpra seamless --start=xterm -d auth \
     --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file(filename=password.txt) \
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
| [sql](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sql.py)                             | sqlalchemy database authentication                                                      | [#2288](https://github.com/Xpra-org/xpra/issues/2288)                               |
| [mysql](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/mysql.py)                         | MySQL database authentication                                                           | [#2287](https://github.com/Xpra-org/xpra/issues/2287)                               |
| [capability](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/capability.py)               | matches values in the capabilities supplied by the client                               | [#3575](https://github.com/Xpra-org/xpra/issues/3575#issuecomment-1183292333)       |
| [peercred](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/peercred.py)                   | `SO_PEERCRED` authentication                                                            | [#1524](https://github.com/Xpra-org/xpra/issues/issues/1524)                        |
| [hosts](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/hosts.py)                         | [TCP Wrapper](https://en.wikipedia.org/wiki/TCP_Wrapper)                                | [#1730](https://github.com/Xpra-org/xpra/issues/issues/1730#issuecomment-765492022) |
| [exec](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/exec.py)                           | Delegates to an external command                                                        | [#1690](https://github.com/Xpra-org/xpra/issues/1690)                               |
| [kerberos-password](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/kerberos_password.py) | Uses kerberos to authenticate a username + password                                     | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [kerberos-token](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/kerberos_token.py)       | Uses a kerberos ticket to authenticate a client                                         | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [gss](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/gss.py)                             | Uses a GSS ticket to authenticate a client                                              | [#1691](https://github.com/Xpra-org/xpra/issues/1691)                               |
| [oauth](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/oauth.py)                         | Uses an OAuth2 Bearer token from websocket HTTP headers or client capabilities          | validates a static token or token introspection endpoint                            |
| [keycloak](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/keycloak.py)                   | Uses a keycloak token to authenticate a client                                          | [#3334](https://github.com/Xpra-org/xpra/issues/3334)                               |
| [ldap](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/ldap.py)                           | Uses ldap via [python-ldap](https://www.python-ldap.org/en/latest/)                     | [#1791](https://github.com/Xpra-org/xpra/issues/1791)                               |
| [ldap3](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/ldap3.py)                         | Uses ldap via [python-ldap3](https://github.com/cannatag/ldap3)                         | [#1791](https://github.com/Xpra-org/xpra/issues/1791)                               |
| [u2f](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/u2f.py)                             | [Universal 2nd Factor](https://en.wikipedia.org/wiki/Universal_2nd_Factor)              | [#1789](https://github.com/Xpra-org/xpra/issues/1789)                               |
| [fido2](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/fido2.py)                         | [FIDO Alliance](https://en.wikipedia.org/wiki/FIDO_Alliance)                            | [#1789](https://github.com/Xpra-org/xpra/issues/4516)                               |
| [otp](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/otp.py)                             | One Time Password                                                                       | [pyotp](https://github.com/pyauth/pyotp)                                            |
| [otpscreen](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/otpscreen.py)                 | Generates a one-time secret and shows it in a local GUI dialog for the user to type     | local secondary-channel confirmation (distinct from `otp`)                          |
| [http-header](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/http_header.py)             | validate websocket http headers                                                         | [#4438](https://github.com/Xpra-org/xpra/issues/4438)                               |
</details>

<details>
  <summary>more examples</summary>

* `XPRA_PASSWORD=mysecret xpra seamless --bind-tcp=0.0.0.0:10000,auth=env`
* `SOME_OTHER_ENV_VAR_NAME=mysecret xpra seamless --bind-tcp=0.0.0.0:10000,auth=env,name=SOME_OTHER_ENV_VAR_NAME`
* `xpra seamless --bind-tcp=0.0.0.0:10000,auth=password,value=mysecret`
* `xpra seamless --bind-tcp=0.0.0.0:10000,auth=file,filename=/path/to/mypasswordfile.txt`
* `xpra seamless --bind-tcp=0.0.0.0:10000,auth=sqlite,filename=/path/to/userlist.sdb`
* `xpra seamless --bind-tcp=0.0.0.0:10000,auth=otpscreen,mode=alphanumeric,count=8,timeout=60`

Beware when mixing environment variables and password files as the latter may contain a trailing newline character whereas the former often do not.

The `otpscreen` module accepts the following options: `mode` (`digits`, `alpha` or `alphanumeric`, default `digits`), `count` (number of characters in the generated secret, default `6`), `timeout` (how long the dialog stays up, in seconds, default `120`), and `display` (which display to open the dialog on, default `auto` which reuses the server's saved `DISPLAY` / `WAYLAND_DISPLAY`).
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
| [fido2](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/fido2.py)       | `APP_ID` specifies the FIDO2 authentication application ID                                               |
| [uri](https://github.com/Xpra-org/xpra/blob/master/xpra/challenge/uri.py)           | Uses values parsed from the connection string, ie: `tcp://foo:bar@host`                                  |
</details>

***

### Password File

* with the `file` module, the password-file contains a single password, the whole file is the password (including any trailing newline characters). To write a password to a file without the trailing newline character, you can use `echo -n "thepassword" > password.txt`
* with `multifile`, the password-file contains a list of authentication values, see [proxy server](Proxy-Server.md) - this module is deprecated in favour of the `sqlite` module which is much easier to configure

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

Only the following modules will make use of both the username and password to authenticate against their respective backend: `kerberos-password`, `ldap`, `ldap3`, `sys` (`pam` and `win32`), `sqlite`, `sql`, `mysql`, `multifile` and `u2f`.
In this case, using an invalid username will cause the authentication to fail.

The username is usually more relevant when authenticating against a [proxy server](Proxy-Server.md) (see authentication details there).


***

## Session lookup and the proxy server

The [proxy server](Proxy-Server.md) needs more than a yes/no answer from authentication: it also needs to know **which xpra sessions** the authenticated client may reach, and **as which uid/gid** to spawn (or connect to) the proxy instance.

Today, that lookup is bundled into the authentication module via the `get_sessions()` method on `SysAuthenticatorBase`, which returns a 5-tuple:

```
(uid, gid, displays, env_options, session_options)
```

* `uid`, `gid`: the system identity the proxy instance runs as
* `displays`: the list of display names the user may attach to (e.g. `[":10", ":11"]`)
* `env_options`: extra environment variables applied to the proxy instance process
* `session_options`: extra session-level options passed to the proxy instance

The proxy server iterates over the protocol's authenticator chain after the challenge passes and uses the first non-empty result (see [`xpra/server/proxy/server.py`](https://github.com/Xpra-org/xpra/blob/master/xpra/server/proxy/server.py)).

The default implementation in `SysAuthenticatorBase.get_sessions()` performs a `DotXpra` socket-directory scan for the authenticated `uid`, listing every live xpra socket owned by the user. **Most modules use this default** (`pam`, `ldap`, `ldap3`, `password`, `peercred`, `keycloak`, `kerberos-*`, `gss`, `u2f`, `fido2`, `otp`, `otpscreen`, `capability`, `env`, `exec`, `hosts`, `http-header`, `allow`, `none`, `win32`, `file`).

Three families override it to return data they already store per user:

| Module      | Source of session data                                                                                                  |
|-------------|-------------------------------------------------------------------------------------------------------------------------|
| `multifile` | Extra columns in the password file (see the `multifile` format in [Proxy-Server.md](Proxy-Server.md))                   |
| `sqlite`    | Columns `uid, gid, displays, env_options, session_options` of the `users` table (see `xpra/auth/sqlauthbase.py` schema) |
| `sql`       | Same schema, via SQLAlchemy                                                                                             |
| `mysql`     | Same schema, against MySQL                                                                                              |

The `fail` and `reject` modules deny authentication outright and therefore never reach session lookup.

### The `--session-registry` proxy option

The proxy server lets you pick the session registry independently of the authenticator with `--session-registry=NAME[(opt=val,...)]` (default `auth`):

| Registry    | Behaviour                                                                                                            |
|-------------|----------------------------------------------------------------------------------------------------------------------|
| `auth`      | Delegates to `authenticator.get_sessions()` — the historical behaviour. `multifile`/`sql*` setups need no changes.   |
| `socket`    | Performs a `DotXpra` socket-directory scan for the authenticated uid — pairs any authenticator with socket discovery. |
| `multifile` | Reads `username\|password\|uid\|gid\|displays\|env\|session_options` from a file (`filename` option). Lookup is by username. |
| `sqlite`    | Looks up `(uid, gid, displays, env_options, session_options)` from the `users` table of an sqlite database (`filename` option). |
| `sql`       | Same schema, via SQLAlchemy (`uri` option).                                                                           |
| `mysql`     | Same schema, against MySQL (`uri` option).                                                                            |
| `live`      | Runtime map of sessions populated by xpra servers that dial out to the proxy at startup with `--register=URI`. See below. |

Example: use `pam` to authenticate but read the per-user session mapping from an sqlite file:

```shell
xpra proxy --bind-tcp=0.0.0.0:14500,auth=pam --session-registry=sqlite(filename=/etc/xpra/users.sdb)
```

Registry modules live under [`xpra/server/session_registry/`](https://github.com/Xpra-org/xpra/tree/master/xpra/server/session_registry).

### The `live` backend and `--register`

A server can announce itself to a proxy at startup with the `--register=URI` option (repeatable). For each URI the server dials the proxy, authenticates as a client, and sends a hello packet carrying `request=register` along with its `uuid`, `session-name` and `display`.

```shell
# proxy side:
xpra proxy --bind-tcp=0.0.0.0:14500 --session-registry=live --auth=password,value=secret

# server side (--session-name names the registered session):
xpra seamless --start=xterm --session-name=demo --register=tcp://:secret@proxy.example.com:14500/
```

The proxy exposes the registered sessions under the `registered` key in `xpra info`.

#### Picking a session from the client

To address a specific registered session, pass `--display=NAME` to `xpra attach`:

```shell
xpra attach tcp://proxy.example.com:14500/ --display=demo
```

When exactly one session is registered, `xpra attach tcp://proxy.example.com:14500/` is enough — the proxy auto-selects it.

By default the name supplied by `--display` is matched against each registered session's `session-name` (and then its registered displays). The match policy can be changed on the proxy with the `lookup-by` option (`session-name`, `uuid` or `display`).

The proxy never dials out — it only ever accepts inbound connections, which makes it usable in front of NAT-ed servers. After each client is brokered, the server re-registers automatically so the slot stays warm for the next one.


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
  <summary>Writing a new authentication module</summary>

A new server-side authentication module is a Python file in [`xpra/auth/`](https://github.com/Xpra-org/xpra/tree/master/xpra/auth) that defines a class named `Authenticator`. Two base classes are provided:

* [`SysAuthenticatorBase`](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sys_auth_base.py) — the minimal base. Use this when the username does not need to map to a local system account (e.g. token-based or capability-based authenticators).
* `SysAuthenticator` (in the same file) — extends the base by loading the local `pwd` entry for `self.username` on POSIX. Use this when the module is tied to system users (`pam`, `peercred`, `exec`, etc.).

The methods most commonly overridden:

| Method                                  | Default                                                                                                  | When to override                                                                                                       |
|-----------------------------------------|----------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `requires_challenge()`                  | returns `True`                                                                                           | Return `False` for modules that authenticate out of band (e.g. `peercred`, `hosts`, `http-header`).                    |
| `get_passwords()` / `get_password()`    | `get_passwords` returns `(get_password(),)`; `get_password` returns `""`                                 | Override one of them to provide the expected password(s) — used by HMAC challenge verification.                        |
| `do_authenticate(caps)`                 | Validates the challenge response and calls `authenticate_check`                                          | Override for non-HMAC flows (e.g. challenge/response over a different transport, third-party token verification).      |
| `authenticate_hmac(caps)`               | Verifies the HMAC challenge against `get_passwords()` results                                            | Override if you need to perform extra checks after a successful HMAC match.                                            |
| `get_uid()` / `get_gid()`               | `NotImplementedError`                                                                                    | Always override. Return the uid/gid the proxy instance should run as. Use `parse_uid` / `parse_gid` from `common.py`.  |
| `get_sessions()`                        | Performs a `DotXpra` socket scan for the authenticated uid                                               | Leave alone unless your backend stores per-user session metadata (see [`multifile`](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/multifile.py) and [`sqlauthbase.py`](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/sqlauthbase.py) for examples). |

Helpers in [`xpra/auth/common.py`](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/common.py):

* `SessionData` — the `(uid, gid, displays, env_options, session_options)` 5-tuple returned by `get_sessions()`
* `parse_uid(v)` / `parse_gid(v)` — accept either a numeric string or a username/group name, with safe defaults
* `get_auth_exec_env(display="auto")` — environment dictionary suitable for spawning helper processes (used by `exec` and `otpscreen`)

Authenticator instances are constructed by [`auth_helper.get_auth_module()`](https://github.com/Xpra-org/xpra/blob/master/xpra/auth/auth_helper.py), which parses the `auth=NAME(opt=value,...)` syntax and imports `xpra.auth.<name>`. Each socket can chain multiple authenticators; the first one to require a challenge issues it and subsequent ones either verify additional caps or contribute to `get_sessions()`.

</details>
<details>
  <summary>Salt handling is important</summary>

* [64-bit entropy is nowhere near enough against a serious attacker](https://crypto.stackexchange.com/a/34162/48758): _If you want to defend against rainbow tables, salts are inevitable, because you need a full rainbow table per unique salt, which is computationally and storage-wise intense_
* [SHA-512 w/ per User Salts is Not Enough](https://blog.mozilla.org/security/2011/05/10/sha-512-w-per-user-salts-is-not-enough/): _In the event the hash was disclosed or the database was compromised, the attacker will already have one of the two values (i.e. the salt), used to construct the hash_
* [about hmac](https://news.ycombinator.com/item?id=1998198): _Those people should know that HMAC is as easy to precompute as naked SHA1 is; you can "rainbow-table" `HMAC_*` and we did get it wrong before...
</details>
