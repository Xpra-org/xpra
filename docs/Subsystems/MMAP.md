# MMAP

The `mmap` modules are used for fast memory transfers
between client and server when both reside on the same host.

## Implementations

The prefix for all packets and capabilities is `mmap`.

| Component         | Link                                                                                               |
|-------------------|----------------------------------------------------------------------------------------------------|
| client            | [xpra.client.mixins.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/client/mixins/mmap.py) |
| client connection | [xpra.server.source.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/mmap.py) |
| server            | [xpra.server.mixins.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/mixins/mmap.py) |


## Capabilities

The client and server should expose the following capabilities in their `hello` packet
using the `clipboard` prefix.

The client creates an `mmap` backing file,
writes a random token at a random position within this mmap area
and sends the following capabilities:

| Capability    | Value                                |
|---------------|--------------------------------------|
| `file`        | path to the mmap backing file        |
| `size`        | size of the mmap area                |
| `token`       | random token value generated         |
| `token_index` | position where the token was written |
| `token_bytes` | length of the token in bytes         |

The server should attempt to open the mmap file specified,
and verify that the token is found.

To use this mmap file, it must write a new token
and return this information to the client.
(using the same format, excluding the `file` and `size` that the client has already specified)

The client then verifies that the mmap file can be used bi-directionally.


## Network Packets

There are no specific `mmap` packets used, `mmap` is used as an [encoding](../Usage/Encodings.md).


# virtio-shmem

Xpra can use `mmap` with `virtio-shmem` to speed up connections between a host and guest or even between two guests.

Example steps for host to guest setup:
* add a `shmem` device to your VM, ie:
  ```shell
  DEV_NAME="shmem-xpra"
  virt-install --shmem name="${DEV_NAME}",model.type=ivshmem-plain,size.unit=M,size=512"`)
  ```
* enable the shared memory device on the guest:
  ```shell
  echo 1 > $(find /sys/devices/ -type f -name "resource2_wc" -exec dirname "{}" \;)/enable
  ```
  and start an xpra server with `mmap` pointing to it:
  ```shell
  VSOCK_PORT=10000
  MMAP_PATH=$(find /sys/devices/ -type f -name "resource2_wc")
  xpra start --bind-vsock=auto:${VSOCK_PORT} --mmap=$MMAP_PATH
  ```
* from the host, use `mmap` with the same device:
  ```shell
  DEV_NAME="shmem-xpra"
  VSOCK_PORT=10000
  VM_CID=$(virsh dumpxml "${DEV_NAME}" | grep cid | sed 's/[^0-9]*//g')
  xpra attach vsock://"${VM_CID}":${VSOCK_PORT}/ -d mmap --mmap="/dev/shm/${DEV_NAME}"
  ```

Documentation:
* [qemu ivshmem device](https://www.qemu.org/docs/master/system/devices/ivshmem.html)
* [ivshmem-spec](https://github.com/qemu/qemu/blob/master/docs/specs/ivshmem-spec.txt)
* [mmap support for `--bind-vsock` (and `--bind-tcp`) ](https://github.com/Xpra-org/xpra/issues/1387)
* [add documentation for virtio-shmem mmap usage](https://github.com/Xpra-org/xpra/pull/4020)
