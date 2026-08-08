# SSH Transport

See also [network](README.md)

***

<div class="docs-section-heading" markdown="1">

## OpenSSH

</div>
With Posix servers already running an SSH server, xpra sessions can be accessed without any extra configuration. ie:
```
xpra attach ssh://USERNAME@HOST/DISPLAY
```
(the `DISPLAY` value may be omitted if the user only has a single active session)

Instead of a display, you can use the name of the session, as given to `--session-name`:
```
xpra attach ssh://USERNAME@HOST/mysession
```
`xpra list-sessions` on the server shows the name of each session.
The name is resolved on the server, by querying each of the live sessions belonging to
the user logging in via ssh, so it only works if exactly one of them carries that name.
If no session matches, the error message will list the names that are available.

Since this is a URI, names containing characters which are not valid in a URI path have to be
percent-encoded: use `ssh://USERNAME@HOST/my%20session` for a session named `my session`,
and `%2C` / `%3D` for `,` and `=` (which are otherwise used to separate connection options).
Values which look like a display are always used as a display: purely numeric values, and
anything starting with `:`, `@` or `wayland-`.

Similarly, it is possible to start new sessions and connect to them in one command:
```
xpra seamless ssh://USERNAME@HOST/ --start=xterm
```

The sessions do not require any specific `bind` command line options: the default xpra configuration will already create unix domain sockets which are forwarded to the client by the SSH transport. Those sockets can be seen with `xpra list` on the server.

***

<div class="docs-section-heading" markdown="1">

## Builtin SSH Server

</div>
This mode can be used to enable SSH connections on servers that do not include an SSH server by default (ie: MS Windows servers), or to use SSH authentication and encryption but without allowing full shell logins via SSH on the server system. (as the connection can only be used to connect to the xpra server)

This mode can be used with plain TCP sockets which end up being upgraded to SSH. The server also supports the `bind-ssh` option: these sockets will only allow SSH connections. ie:
```
xpra seamless --bind-ssh=0.0.0.0:10000 --start=xterm
```
The client can then connect to this port using ssh:
```
xpra attach ssh://HOST:10000/
```
The SSH server's private key must be accessible to the user running the xpra server. The filenames can be configured using the OpenSSH `IdentityFile` option or the `XPRA_SSH_DEFAULT_KEYFILES` environment variable. Otherwise, the server will try to open key files found in `~/.ssh/`)

Regular TCP sockets can also be upgraded to SSH.

For details, see [#1920](https://github.com/Xpra-org/xpra/issues/1920), use the `-d ssh` [debug logging flag](../Usage/Logging.md).

***

<div class="docs-section-heading" markdown="1">

## Client

</div>

The client can either use the builtin ssh client (based on [paramiko](http://www.paramiko.org/)), or an external tool. \
This can be configured using the `ssh` command line option. The default setting is `auto` which will use `paramiko` if it is present and fallback to the platform's default external tool when it is not.

On most platforms the default external tool is the `ssh` command, but on MS Windows it is putty `plink`.

### `ssh`
This mechanism relies on [openssh](https://www.openssh.com/) on Posix systems, optionally using [sshpass](https://sourceforge.net/projects/sshpass/) to supply passwords via the command line or connection files.

Since this mechanism relies on executing the ssh client program, you can use the same command line options as you normally would and / or use the openssh configuration files for using tunnels, restricting ciphers, etc.
ie: `--ssh="ssh -x -c aes128-gcm@openssh.com"`

The `--exit-ssh` switch controls whether the SSH transport is killed when the client terminates, this can be useful if openssh is set up to use connection sharing. (see [#203](https://github.com/Xpra-org/xpra/issues/203) for details)

### `plink`
On MS Windows, the installer will bundle the [tortoisesvn](https://tortoisesvn.net/) version of [PuTTY plink](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html) which includes a more user-friendly GUI for host key confirmation and password input.

### [paramiko](http://www.paramiko.org/)

This backend is built into the client connection code and provides better diagnostics (using the `--debug=ssh` switch), and it provides a GUI for confirming host keys, entering key passphrases or passwords.\
The downside is that since it does not use OpenSSH at all, it does not have the same flexibility, it may require re-confirmation of known hosts, and it may not support all the configuration options normally used with OpenSSH.

Paramiko can accept configuration options in the command line.
After `--ssh=paramiko`, add a double-colon `:` and then one or more of the available options:
* `auth`: Specify the authentication methods used, in the order that they will be used.
  Available values: `none`, `agent`, `publickey`, `password`
  e.g.: `--ssh=paramiko:auth=agent+publickey`
* `stricthostkeychecking`: _See `man ssh_config` --> `StrictHostKeyChecking`_
  Available values: `yes`, `no (default)`
  e.g.: `--ssh=paramiko:stricthostkeychecking=yes`

Multiple options can be given as a comma-separated string, e.g.: `--ssh=paramiko:auth=agent+publickey,stricthostkeychecking=yes`

### passwords

You can specify the password to use on the command line URI:
```
xpra attach ssh://USERNAME:PASSWORD@HOSTNAME/
```
But this exposes the password in the process list: [obfuscate passwords](https://github.com/Xpra-org/xpra/issues/3196)
