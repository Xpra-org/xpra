# MMAP

The `mmap` modules are used for fast memory transfers
between client and server when both reside on the same host.

The client creates its mmap areas before the connection is established,
so it cannot know yet whether the server will be able to use them.
On MS Windows, where the areas are charged to the system commit limit as soon
as they are created and the server is very rarely local, the default value of
the `mmap` option (`auto`) therefore means `no`: it must be enabled explicitly
with `mmap=yes`.

<div class="docs-section-heading" markdown="1">

## Implementations

</div>

The prefix for all packets and capabilities is `mmap`.

| Component         | Link                                                                                                     |
|-------------------|----------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/mmap.py) |
| client connection | [xpra.server.source.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/mmap.py)       |
| server            | [xpra.server.subsystem.mmap](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/mmap.py) |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client and server expose these capabilities in an `mmap` map in their `hello` packet.

The client creates an `mmap` backing file for each direction it wants to use:
* `read` for receiving data from the server
* `write` for sending data to the server

For each capability,
the client writes a random token at a random position within this mmap area
and sends the following attributes:

| Capability    | Value                                |
|---------------|--------------------------------------|
| `file`        | path to the mmap backing file        |
| `size`        | size of the mmap area                |
| `token`       | random token value generated         |
| `token_index` | position where the token was written |
| `token_bytes` | length of the token in bytes         |

Each area is described by its own map: `{"mmap": {"read": {...}, "write": {...}}}`.
The `token` is a random positive integer, usually 128 bits long (so it is encoded
as a big integer, code `61` in rencodeplus). It is stored in the area starting at
`token_index`, as `token_bytes` bytes in little-endian order: byte `token_index`
holds the least significant 8 bits. `token_bytes` defaults to 128 and MUST NOT
exceed 512. The token MUST NOT overlap the 8-byte header described below.
The area size must be at least 64 MiB and less than 4 GiB.

The server should attempt to open the mmap file specified,
and verify that the token is found.

The client does not get to choose which directory the server opens the file from:
the server only uses the basename of the `file` attribute, and looks for it
in one of the directories it accepts.
Unless directories have been specified with the `mmap` option, these are
the server's own mmap directory and, when the peer can be identified as
another local user, that user's mmap directory.
Clients specifying a file anywhere else are refused and mmap is then disabled.

The file is opened relative to that directory and symbolic links are never
followed, then the file descriptor itself is verified rather than the path:
it must be a regular file, with a single link, belonging either to the server
or to the client's user. The directory must not be writable by everyone
unless the sticky bit prevents other users from replacing files in it.
None of these checks apply to a path specified with the `mmap` option:
that one is chosen by the administrator and can legitimately be a symbolic
link, a device file, or a file belonging to another user.

To use this mmap file, it must write a new token
and return this information to the client, using the same format.

The names in the server's reply are from the server's point of view: the area the
client called `read` (server to client) is returned as the server's `write`, and
the client's `write` area as the server's `read`.
The client then reads the server's token from the area to verify that the server
really is using the same memory. A token value of zero means that the server is
not using that area.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

There are no specific `mmap` packets used, `mmap` is used as an [encoding](../Usage/Encodings.md).

<div class="docs-section-heading" markdown="1">

## Data transfer

</div>

The first 8 bytes of each area are a header holding two unsigned 32-bit integers
in the native byte order of the host:

| Offset | Name | Written by | Meaning |
|---:|---|---|---|
| 0 | `data_start` | reader | Offset up to which the reader has consumed the data |
| 4 | `data_end` | writer | Offset up to which the writer has written data |

Both are absolute offsets within the area, in the range `8..size`; zero means that
nothing has been read or written yet. The rest of the area is a ring buffer: the
writer only writes into the free space between `data_end` and `data_start`,
wrapping around to offset 8 at the end of the area.

A `window-draw` packet using the `mmap` encoding has empty `data`. Its options
contain `rgb_format` and `chunks`: a list of one or two `(offset, length)` pairs
(two when the data wraps around), whose concatenation is the raw pixel data,
with the packet's `rowstride`. Once it has copied or painted the pixels, the client
MUST set `data_start` to the end (`offset + length`) of the last chunk, even if
painting failed: the server cannot reuse that space otherwise. It then sends the
`window-ack` as usual. Chunks MUST be validated against the area size before use.


<div class="docs-section-heading" markdown="1">

## virtio-shmem

</div>

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
  xpra seamless --bind-vsock=auto:${VSOCK_PORT} --mmap=$MMAP_PATH
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
