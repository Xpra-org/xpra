# virtio-shmem
Xpra can make use of shared memory for cases where the client and server run on the same operating system instance. Furthermore it is possible to use shared memory between a VM host and VM guest, as well as two VM guests.

The following howto describes how to use shared memory between a VM host and VM guest with Xpra. For an additional performance improvement `virtio-vsock` is used.

1. Obtain an Alpine Linux installation medium:
```  
wget https://dl-cdn.alpinelinux.org/alpine/v3.18/releases/x86_64/alpine-virt-3.18.3-x86_64.iso \
-O ~/Downloads/alpine-virt-3.18.3-x86_64.iso
```
2. Setup the VM:
```  
virt-install \
--osinfo alpinelinux3.17 \
--disk none \
--vcpus 2 \
--memory 2048 \
--name "alpine-linux-v3.17.2-xpra" \
--disk path=~/Downloads/alpine-virt-3.18.3-x86_64.iso,bus=virtio \
--network user,model=virtio \
--vsock cid.auto=yes \
--import \
--transient \
--shmem name="alpine-linux-v3.17.2-xpra",model.type=ivshmem-plain,size.unit=M,size=512
```
3. Setup networking and enable "community" repository and install xpra-server:
```  
setup-alpine  
echo "http://dl-cdn.alpinelinux.org/alpine/v3.18/community" >> /etc/apk/repositories  
apk update
apk add xpra
```
4. Enable shared memory device:  
```  
echo 1 > $(find /sys/devices/ -type f -name "resource2_wc" -exec dirname "{}" \;)/enable
```
5. Run xpra-server:
```  
export VIRTUAL_DISPLAY=:14500
export PORT=14500
export LOGFILE=xpra.log
export PIDFILE=/root/.xpra/proxy.pid
export LOGDIR=/root/.xpra
export MMAP_PATH=$(find /sys/devices/ -type f -name "resource2_wc")  
mkdir $LOGDIR
xpra start $VIRTUAL_DISPLAY --bind-vsock=auto:$PORT --daemon=yes --log-file=$LOGFILE --log-dir=$LOGDIR --pidfile=$PIDFILE --mmap=$MMAP_PATH
```

Once the VM guest is setup, Xpra can be called on the VM host as follows:  
```  
export VM_CID=$(virsh dumpxml "alpine-linux-v3.17.2-xpra" | grep cid | sed 's/[^0-9]*//g')
xpra attach vsock://"${VM_CID}":14500/ --border=red --opengl=force -d mmap --mmap="/dev/shm/alpine-linux-v3.17.2-xpra"  
```
Congratulation! Your logs should now show `mmap_enabled` as `True`:  
```  
[...]  
2023-09-25 14:19:44,425 init_mmap(/dev/shm/alpine-linux-v3.17.2-xpra, auto, host)
2023-09-25 14:19:44,425 init_mmap('auto', 'host', 536870912, '/dev/shm/alpine-linux-v3.17.2-xpra')
2023-09-25 14:19:44,425 Using existing mmap file '/dev/shm/alpine-linux-v3.17.2-xpra': 512MB
2023-09-25 14:19:44,425 xpra_group() group(xpra)=972, groups=[10, 974, 975, 1000]
2023-09-25 14:19:44,425 Warning: missing valid socket filename 'host' to set mmap group
2023-09-25 14:19:44,425 using mmap file /dev/shm/alpine-linux-v3.17.2-xpra, fd=26, size=536870912
2023-09-25 14:19:44,426 write_mmap_token(<mmap.mmap closed=False, access=ACCESS_DEFAULT, length=536870912, pos=0, offset=0>, 0x57d7e16816bf4380b3f1ff2d5da8a9ba, 0x19ae44e6, 0x80)
2023-09-25 14:19:44,427  keyboard settings: rules=evdev, model=pc104, layout=de
2023-09-25 14:19:44,441  desktop size is 2160x1440:
2023-09-25 14:19:44,442   :0.0 (571x381 mm - DPI: 96x96) workarea: 2160x1396
2023-09-25 14:19:44,442     CMN eDP          (296x197 mm - DPI: 185x186)
2023-09-25 14:19:44,448 mmap caps={'mmap': {'file': '/dev/shm/alpine-linux-v3.17.2-xpra', 'size': 536870912, 'token': 116763751246802285812421773573134789050, 'token_index': 430851302, 'token_bytes': 128}, 'mmap_file': '/dev/shm/alpine-linux-v3.17.2-xpra', 'mmap_size': 536870912, 'mmap_token': 116763751246802285812421773573134789050, 'mmap_token_index': 430851302, 'mmap_token_bytes': 128, 'mmap.namespace': True}
2023-09-25 14:19:44,603 self.supports_mmap: True
2023-09-25 14:19:44,603 self.mmap_enabled: True
2023-09-25 14:19:44,603 iget-enabled: 0
2023-09-25 14:19:44,603 parse_server_capabilities(..) mmap_enabled=True
2023-09-25 14:19:44,604 read_mmap_token(<mmap.mmap closed=False, access=ACCESS_DEFAULT, length=536870912, pos=0, offset=0>, 0x0, 0x80)=0x0
2023-09-25 14:19:44,604 enabled fast mmap transfers using 512MB shared memory area
2023-09-25 14:19:44,604 XpraClient.clean_mmap() mmap_filename=/dev/shm/alpine-linux-v3.17.2-xpra
2023-09-25 14:19:44,604 enabled remote logging
2023-09-25 14:19:44,604 Xpra X11 seamless server version 4.4
2023-09-25 14:19:44,612 Attached to xpra server at vsock://4:14500
2023-09-25 14:19:44,613  (press Control-C to detach)

2023-09-25 14:19:44,621 running
```