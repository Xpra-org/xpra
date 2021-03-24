# ![SSH](https://xpra.org/icons/ssh.png) SSH Transport

See also [network](./README.md)

***

## OpenSSH
With Posix servers already running an SSH server, xpra sessions can be accessed without any extra configuration. ie:
```
xpra attach ssh://USERNAME@HOST/DISPLAY
```
(the `DISPLAY` value may be omitted if the user only has a single active session)

Similarly, it is possible to start new sessions and connect to them in one command:
```
xpra start ssh://USERNAME@HOST/ --start=xterm
```

The sessions do not require any specific `bind` command line options: the default xpra configuration will already create unix domain sockets which are forwarded to the client by the SSH transport. Those sockets can be seen with `xpra list` on the server.

***

## Builtin SSH
This mode can be used to enable SSH connections on servers that do not include an SSH server by default (ie: MS Windows servers), or to use SSH authentication and encryption but without allowing full shell logins via SSH on the server system. (as the connection can only be used to connect to the xpra server)

This mode can be used with plain TCP sockets which end up being upgraded to SSH. The server also supports the `bind-ssh` option: these sockets will only allow SSH connections. ie:
```
xpra start --bind-ssh=0.0.0.0:10000 --start=xterm
```
The client can then connect to this port using ssh:
```
xpra attach ssh://HOST:10000/
```
The SSH server's private key must be accessible to the user running the xpra server. The filenames can be configured using the OpenSSH `IdentityFile` option or the `XPRA_SSH_DEFAULT_KEYFILES` environment variable. Otherwise, the server will try to open key files found in `~/.ssh/`)

Regular TCP sockets can also be upgraded to SSH.

For details, see [#1920](https://github.com/Xpra-org/xpra/issues/1920), use the `-d ssh` [debug logging flag](../Usage/Logging.md).

***

## Client

The client can either use the builtin ssh client (based on [paramiko](http://www.paramiko.org/)), or an external tool. \
This can be configured using the `ssh` command line option. The default setting is `auto` which will use `paramiko` if it is present and fallback to the platform's default external tool when it is not.

On most platforms the default external tool is the `ssh` command, but on MS Windows it is putty `plink`.

### `ssh`
This mechanism relies on [openssh](https://www.openssh.com/) on Posix systems, optionally using [sshpass](https://sourceforge.net/projects/sshpass/) to supply passwords via the command line or connection files.

### `plink`
On MS Windows, the installer will bundle the [tortoisesvn](https://tortoisesvn.net/) version of [PuTTY plink](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html) which includes a more user friendly GUI for host key confirmation and password input.

Since this mechanism relies on executing the ssh client program, you can use the same command line options as you normally would and / or use the openssh configuration files for using tunnels, restricting ciphers, etc.
ie: `--ssh="ssh -x -c blowfish-cbc"`

The `--exit-ssh` switch controls whether the SSH transport is killed when the client terminates, this can be useful if openssh is setup to use connection sharing. (see [#203](../https://github.com/Xpra-org/xpra/issues/203) for details)

### [paramiko](http://www.paramiko.org/)

This backend is built into the client connection code and provides better diagnostics (using the `--debug=ssh` switch), and it provides a GUI for confirming host keys, entering key passphrases or passwords.\
The downside is that since it does not use OpenSSH at all, it does not have the same flexibility, it may require re-confirmation of known hosts and it may not support all the configuration options normally used with OpenSSH.
