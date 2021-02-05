The proxy server is used for starting or accessing multiple xpra sessions through a single entry point, without requiring SSH for transport or authentication.

This can be useful for hosts that have a limited number of publicly accessible ports or for clients accessing servers through firewalls with outbound port filtering. (ie: you can put the server on port 80 or 443 and access many sessions from this single port)

When started as `root`, which is the case when the proxy server runs as a [system service](./Service.md), this can also help to ensure that the sessions outlive the environment they were started from.


# Configuration
Depending on the [authentication](./Authentication.md) module configured, the proxy server can:
* expose all the local sessions and start new ones (this is the default behaviour)
* provide access to a custom list of sessions (ie: using the `sqlite` authentication module)


# GPU Accelerated Transcoding
If the proxy server has access to a hardware accelerated encoding device (ie: [NVENC](./NVENC.md)) and the servers it proxies do not, then it can automatically be used for speeding up screen update compression. (details in [#504](../issues/504))


# Diagram
Here is an example architecture using the proxy server to provide access to a number of servers through a single port, also showing where NVENC hardware encoders and TCP proxying (apache, nginx, thttp,..) can all hook into:

![Xpra Proxy Diagram](https://xpra.org/images/Xpra-Proxy.png)


# Example
*Beware*: to simplify these instructions, we use the `allow` authentication module, which does *no* checking whatsoever!

start a session on display `:100` with an `xterm`, this session is not exposed via TCP as there is no `bind-tcp` option:
```
xpra start :100 --start=xterm
```
start a proxy server available on tcp port 14501:
```
xpra proxy :20 --tcp-auth=allow --bind-tcp=0.0.0.0:14501
```
if only one session exists for this user, you can connect via the proxy with:
```
xpra attach tcp://foo:bar@PROXYHOST:14501/
```

If there is more than one existing session accessible for this user account, the client also needs to specify which display it wishes to connect to using the extended attach syntax: `tcp/USERNAME:PASSWORD@SERVER:PORT/DISPLAY`:
```
xpra attach tcp://foo:bar@PROXYHOST:14501/100
```

Notes:
* this example uses TCP, but the proxy works equally well with all other transports (`SSL`, etc)
* the username "foo" and password "bar" can be replaced with anything since the `allow` authentication module does not check the credentials
* if you run this command as root, all the user sessions will be exposed!
* if you run it a normal user, only this user's session will be exposed
* when running the proxy server as root, once authenticated, the proxy server spawns a new process and no longer runs as root
* the display number chosen for the proxy server is only used for identifying the proxy server and interacting with it using the regular tools (`xpra info`, etc)
* to use ports lower than 1024 either use `--min-port` and run as root or see [allow non-root process to bind to port 80 and 443](https://superuser.com/questions/710253/)


# Info and Control
When the client requests information from the server (ie: for the session info dialog or for internal use), the requests are passed through the proxy instance to the real server just like other packets, but the response is augmented with some extra information from the proxy server. (it is prefixed to prevent any interference)

Just like any other xpra server instance, a proxy instance can be also be queried directly. Since proxy instances do not have their own display number, each proxy instance will create a socket using the process ID instead (ie: `:proxy-15452`), you ca
n find their names using `xpra list`.
}}}


# Stopping
You can stop the proxy server just like any other servers with `xpra stop :$PROXYDISPLAY`.

If you want to stop an individual proxy connection instead, you must identify the proxy instance that you want to stop then use `xpra stop :proxy-$PROXYPID`.

You can identify proxy instances in a number of ways:
* using system network tools that list processes and the hosts they are connected to (ie: `lsof`, `netstat`)
* using `xpra info` on a specific proxy instance
* from the proxy server log file
* from the proxy instance log file
etc..


# Remote Hosts Example
This example uses a `sqlite` database to expose two remote server instances accessible from the proxy server via `TCP`.

Start the two sessions we wish to access via the `PROXYHOST` (we call this `TARGETHOST` - for testing, this can be the same host as `PROXYHOST`). On `TARGETHOST`:
```
xpra start :200 --bind-tcp=0.0.0.0:10100 --start=xterm
xpra start :201 --bind-tcp=0.0.0.0:10101 --start=xterm
```
Start a proxy server on port 14501 using the "`sqlite`" authentication module (we will call this server `PROXYHOST`):
```
xpra proxy :100 --bind-tcp=0.0.0.0:14501,auth=sqlite:filename=./xpra-auth.sdb --socket-dir=/tmp
```
and add user entries (ie: `foo` with password `bar`), pointing to the `TARGETHOST` sessions (ie: `192.168.1.200` is the `TARGETHOST`'s IP in this example):
```
SQLITE_AUTH_PY=/usr/lib64/python3.9/site-packages/xpra/server/auth/sqlite_auth.py
python $SQLITE_AUTH_PY ./xpra-auth.sdb create
python $SQLITE_AUTH_PY ./xpra-auth.sdb add foo bar nobody nobody tcp://192.168.1.200:10100/
python $SQLITE_AUTH_PY ./xpra-auth.sdb add moo cow nobody nobody tcp://192.168.1.200:10101/ "" "compression=0"
```
connect the client through the proxy server to the first session:
```
xpra attach tcp://foo:bar@$PROXYHOST:14501/
```
or for the second session:
```
xpra attach tcp://moo:cow@$PROXYHOST:14501/
```

To hide the password from the command line history and process list, you can use a password file:
```
echo -n "bar" > ./password.txt
xpra attach --password-file=./password.txt tcp://foo@$PROXYHOST:14501/
```

What happens:
* the client connects to the proxy server
* the proxy server asks the client to authenticate and sends it a challenge
* the client responds to the challenge
* the proxy server verifies the challenge (and disconnects the user if needed)
* the proxy server identifies the session desired (ie: the one on `TARGETHOST`)
* the proxy server creates a new connection to the real server (`TARGETHOST`), applying any options specified (ie: "`compression=0`" will disable compression between the proxy and server)
* the proxy server spawns a new process
* the new proxy process changes its uid and gid to 'nobody' / 'nobody' (if the proxy server runs as root only, otherwise unchanged)
* the packets should now flow through between the client and the real server

Further notes:
* for authentication between the proxy and the real server, just specify the username and password in the connection string
* you can omit the uid and gid and the special user / group "nobody" will be used (Posix servers only)
* this example uses `socket-dir=/tmp` to ensure that the proxy instances can create their sockets, no matter what user they runs as (nobody) - this is not always necessary (ie: not usually needed when running as non-root)
* you can specify the uid and gid using their names (ie: uid="joe", gid="users", Posix servers only) or numerical values (ie: 1000)
* you can specify more than one remote session string for each username and password pair using CSV format - but the client will then have to specify which one it wants on the connection URL


# Username Matters
The proxy server can also be used to expose all local sessions dynamically.\
This is what the [system service](./Service.md) (aka "system wide proxy server") does.

In this case, the username, uid and gid are used to locate all the sessions for the user once it has authenticated, in the same way that a user can list sessions by running `xpra list`.
This type of proxy server usually runs as root to be able to access the sessions for multiple users.

This mode of operation cannot be used with the `sqlite` or `multifile` authentication modules since those modules specify the list of sessions explicitly.

For some authentication modules the uid and gid can be derived from the username automatically using the password database (ie: `pam`, others allow for it to be specified as a module option (ie: `--tcp-auth=ldap,uid=xpraproxy,gid=xpraproxy`) which makes it possible for non-local accounts to execute the proxy process instance as a non-root user.
The default value of `nobody` uid and `nobody` gid may or may not have sufficient privileges for executing a proxy process instance.

You should not use the `file`, `env` or `exec` authentication modules, as those would allow access to all usernames with the same password value.
