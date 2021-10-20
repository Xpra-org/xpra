# WSL - Windows Subsystem for Linux


## OpenGL acceleration
This setup results in this output from `glxinfo -B`:
<details>
  <summary>glxinfo</summary>

```shell
name of display: :0
display: :0  screen: 0
direct rendering: Yes
Extended renderer info (GLX_MESA_query_renderer):
    Vendor: Microsoft Corporation (0xffffffff)
    Device: D3D12 (NVIDIA GeForce RTX 3070 Laptop GPU) (0xffffffff)
    Version: 21.0.3
    Accelerated: yes
    Video memory: 15138MB
    Unified memory: no
    Preferred profile: core (0x1)
    Max core profile version: 3.3
    Max compat profile version: 3.1
    Max GLES1 profile version: 1.1
    Max GLES[23] profile version: 3.0
OpenGL vendor string: Microsoft Corporation
OpenGL renderer string: D3D12 (NVIDIA GeForce RTX 3070 Laptop GPU)
OpenGL core profile version string: 3.3 (Core Profile) Mesa 21.0.3
OpenGL core profile shading language version string: 3.30
OpenGL core profile context flags: (none)
OpenGL core profile profile mask: core profile

OpenGL version string: 3.1 Mesa 21.0.3
OpenGL shading language version string: 1.40
OpenGL context flags: (none)

OpenGL ES profile version string: OpenGL ES 3.0 Mesa 21.0.3
OpenGL ES profile shading language version string: OpenGL ES GLSL ES 3.00
```
</details>

### Setup Steps

One of these steps is obviously specific to the (Lenovo laptop) hardware it was tested on.  
You will need to adapt it to your hardware.

* Create an installer USB stick with Microsoft's media creation tool. Don't use the insider's edition of Windows 11
* Start the Windows install and when shown the question _Choose what to keep_ select _Nothing_
* After installation, install all Windows updates and restart
* Windows home version doesn't include Bitlocker
* Open https://github.com/microsoft/wslg and install the NVIDIA GPU driver for WSL (get CUDA driver, download GeForce driver)
* Open https://www.lenovo.com/us/en/software/vantage and install _Lenovo Vantage_ and install available updates and reboot if needed.
* Set Windows' timezone
* Install WSL 2
   - Open Administrator CMD prompt
   - `wsl --install -d Ubuntu-20.04`
   - Restart Windows, WSL 2 setup continues automatically after restart.
   - `sudo apt update; sudo apt upgrade` 
   - Shutdown WSL 2 with `wsl --shutdown`
   - Start WSL 2 again with `bash`
   - `sudo apt install gedit mesa-utils`
   - Shutdown WSL 2 with `wsl --shutdown`
   - Start WSL 2 again with `bash`
   - Check output of `glxinfo -B`

Some extra packages are needed to show the correct output with `glxinfo`,
those look like they were installed as a dependency of gedit. (perhaps mesa packages)

### Enable systemd in WSL 2

https://github.com/damiongans/ubuntu-wsl2-systemd-script

Clone that repository on the Windows host side, then change `basic.target` to `multi-user.target` in `start-systemd-namespace` and `enter-systemd-namespace`.  
To enable `systemd` in WSL 2, run `bash ubuntu-wsl2-systemd-script.sh` on the Windows host side.  
The next time you run bash, it'll show a line about enabling systemd.  
After this run `sudo systemctl set-default multi-user.target` in WSL 2.

### Ensure there will be X0 socket in `/tmp/.X11-unix`

Create `/etc/rc.local` and put the following content in it:
```shell
#!/bin/bash

ln -s /mnt/wslg/.X11-unix/X0 /tmp/.X11-unix
```
Then make it executable with `chmod +x /etc/rc.local`.  
Now either run that `ln` command manually or restart WSL 2 as shown above.

### Enable SSH Password Authentication
Edit `/etc/ssh/sshd_config` and set `PasswordAuthentication yes`.  
Enable ssh with "sudo systemctl enable --now ssh". 

### Install xpra
Now you can install xpra server in WSL 2 and the xpra client on Windows.  
You can see the WSL 2 IP address with `ip a` in WSL 2.
