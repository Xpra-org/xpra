# Windows Subsystem for Linux (WSL)

This page covers running an Xpra server in a Linux distribution hosted by WSL
and connecting to it from Windows. This is useful when applications should keep
running after their client disconnects, or when the Linux session is to be used
from another Xpra client.

It is not necessary to use Xpra just to show a Linux graphical application on
Windows. On supported Windows 11 systems, WSLg can display Linux GUI
applications directly in Windows. Xpra adds its usual persistent sessions,
seamless windows, and remote-access features on top of that.

## Prerequisites

Use a current WSL 2 installation and a supported Linux distribution. From an
elevated PowerShell prompt, a new installation can normally be created with:

```powershell
wsl --install
```

Use `wsl --update` to update an existing installation and `wsl -l -v` to check
that the distribution uses version 2. Microsoft's [WSL installation
guide](https://learn.microsoft.com/windows/wsl/install) has the current
requirements and installation alternatives.

WSLg is included with current WSL on Windows 11. It provides the Wayland and
X11 display services used by Linux GUI applications, as well as audio and
clipboard integration. The [WSLg architecture
overview](https://devblogs.microsoft.com/commandline/wslg-architecture/)
explains how those pieces fit together.

## Install Xpra

Install Xpra in the WSL distribution using the packages appropriate for that
distribution; see [Download Xpra](https://github.com/Xpra-org/xpra/wiki/Download).
For example, after configuring the Xpra package repository on a Debian or
Ubuntu system:

```shell
sudo apt update
sudo apt install xpra
```

Install the native Windows Xpra client as well. The packaged `EXE` or `MSI`
installer is required for Windows integration; see the [client
documentation](Client.md#platform-quirks).

## Start and connect to a session

For a local Windows client, bind Xpra only to WSL's loopback interface. This
uses WSL's localhost forwarding and avoids exposing an unencrypted Xpra TCP
listener to the network.

In WSL, start a session and an application (replace `xterm` with an installed
application if necessary):

```shell
XPRA_PASSWORD='choose-a-secret' xpra start :100 --bind-tcp=127.0.0.1:14500,auth=env --start=xterm
```

From PowerShell, set the same password for the client and attach to the
session:

```powershell
$env:XPRA_PASSWORD = 'choose-a-secret'
Xpra_cmd.exe attach tcp://127.0.0.1:14500
```

`Xpra_cmd.exe` is the Windows command-line client and is preferable while
testing because it prints diagnostics. The graphical launcher can also connect
to `tcp://127.0.0.1:14500`.

Do not bind to `0.0.0.0` or a LAN address without configuring suitable
authentication and transport security. For access from another computer,
prefer an SSH connection or TLS and follow the [authentication](Authentication.md)
and [security](Security.md) guidance.

## systemd (optional)

systemd is only needed when Xpra or a related service should be managed as a
system service. Current WSL distributions may already enable it. To enable it
for a WSL 2 distribution, add the following to `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Then run `wsl --shutdown` from PowerShell and start the distribution again.
Microsoft's [systemd in WSL documentation](https://learn.microsoft.com/windows/wsl/systemd)
has the version requirements and troubleshooting details. Do not use the old
third-party scripts that replaced WSL's init process.

## OpenGL and WSLg

WSLg can provide GPU-accelerated OpenGL to applications running on its display.
This is distinct from [client-side OpenGL rendering](Client-OpenGL.md). Driver
availability and supported APIs depend on the Windows GPU driver, WSL version,
and hardware. To inspect the renderer in the distribution, install its
`mesa-utils` (or equivalent) package and run:

```shell
glxinfo -B
```

See [server OpenGL acceleration](OpenGL.md) for Xpra display choices and their
limitations. In particular, a normal virtual Xpra display generally uses
software rendering; using an existing WSLg display is a separate setup with
different lifecycle and isolation trade-offs.

<details markdown="1">
<summary>Historical Lenovo laptop setup</summary>

The following notes record the specific machine on which this was originally
tested. They are not general WSL or Xpra installation instructions.

The machine was a Lenovo laptop with an NVIDIA GeForce RTX 3070 Laptop GPU.
After a clean Windows 11 installation, Windows Update, the NVIDIA WSL-capable
driver, and Lenovo Vantage updates were installed. WSL was then installed with
an Ubuntu 20.04 distribution, followed by `mesa-utils` and `gedit`; the latter
appeared to pull in additional Mesa packages needed by this particular test.

The resulting `glxinfo -B` reported direct rendering through D3D12 and the
NVIDIA GPU:

```text
OpenGL vendor string: Microsoft Corporation
OpenGL renderer string: D3D12 (NVIDIA GeForce RTX 3070 Laptop GPU)
OpenGL core profile version string: 3.3 (Core Profile) Mesa 21.0.3
OpenGL version string: 3.1 Mesa 21.0.3
OpenGL ES profile version string: OpenGL ES 3.0 Mesa 21.0.3
```

</details>
