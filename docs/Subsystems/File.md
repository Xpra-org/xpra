# File transfers

This subsystem transfers files in either direction, opens files and URLs on the peer,
and forwards print jobs.
For usage related information, see [file transfers](../Features/File-Transfers.md)
and [printing](../Features/Printing.md).

<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                             |
|-------------------|------------------------------------------------------------------------------------------------------------------|
| common            | [xpra.net.file_transfer](https://github.com/Xpra-org/xpra/blob/master/xpra/net/file_transfer.py)                 |
| client            | [xpra.client.base.file](https://github.com/Xpra-org/xpra/blob/master/xpra/client/base/file.py)                   |
| client connection | [xpra.server.source.file](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/file.py)               |
| server            | [xpra.server.subsystem.file](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/file.py)         |

<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

Each peer describes what it **accepts** in a `file` map:

| Capability     | Type    | Information                                                                 |
|----------------|---------|-----------------------------------------------------------------------------|
| `enabled`      | boolean | Files can be sent to this peer                                              |
| `ask`          | boolean | The peer asks its user before accepting a file: send a `file-data-request` first |
| `size-limit`   | integer | Largest file accepted, in bytes                                             |
| `chunks`       | integer | Largest chunk accepted, in bytes (`65536` by default), `0` disables chunking |
| `open`         | boolean | Received files may be opened                                                |
| `open-ask`     | boolean | The peer asks its user before opening a file                                |
| `open-url`     | boolean | URLs can be sent to this peer with `file-open-url`                          |
| `open-url-ask` | boolean | The peer asks its user before opening a URL                                 |
| `ask-timeout`  | integer | How long the peer waits for its user's answer, in seconds                   |
| `request-file` | boolean | The peer accepts `file-request`                                             |

Printing uses a separate `printer` map: `printing` (print jobs are accepted) and
`printing-ask`. The client lists its printers with `printer-devices`, see
[printing](../Features/Printing.md).

<div class="docs-section-heading" markdown="1">

## Sending a file

</div>

The packet layouts are in the [protocol registry](../Network/Protocol.md#810-files-urls-and-printers).

1. When the receiver advertises `ask` (or for print jobs, `printing-ask`), the sender
   first sends `file-data-request` with `type="file"`, a new random `send_id`, the
   file name as `url`, its mimetype, size and the `print` / `open` flags.
   The receiver answers with `file-data-response send_id accept`. Without an answer
   within `ask-timeout`, the request is dropped.
2. The sender sends `file-send` with the base name of the file (never a path), the
   mimetype, the `print` and `open` flags, the total `size`, the data, an options
   map and the `send_id` of the accepted request, if any. The options contain the
   `sha256` digest of the whole file, in hexadecimal. Receivers also accept `sha512`,
   `sha384`, `sha224` and `sha1`, and MUST verify the digest they find.
3. Small files are sent in one go, in the `data` argument.
4. A file larger than the smaller of the two peers' `chunks` values is sent in
   chunks of that size. The `file-send` packet then has empty `data` and its options
   contain a `file-chunk-id` (a random hexadecimal string). The transfer is
   stop-and-wait:
   * the receiver answers with `file-ack-chunk chunk_id True "" 0`,
   * the sender sends `file-send-chunk chunk_id 1 data has_more`,
   * the receiver acknowledges each chunk with `file-ack-chunk chunk_id True "" n`,
     and the sender sends chunk `n+1`, until a chunk has `has_more=False`.

   Either side aborts the transfer by acknowledging with `False` and an error
   message, or when it receives nothing for that transfer for 10 seconds.
   At most 10 transfers can be in progress at once.

The receiver MUST check the declared size against its `size-limit`, MUST NOT use any
directory component of the file name, and MUST verify the digest before opening or
printing the file.

<div class="docs-section-heading" markdown="1">

## Requesting a file, opening URLs

</div>

* `file-request filename open send_id` asks the peer to send one of its files.
  The peer answers with a `file-data-request` (or `file-send`) carrying the same
  `send_id`: a client only auto-accepts a file whose `send_id` and name match a
  request it made.
  This lets the peer read files on the receiving host: servers SHOULD restrict
  the files that can be requested, and MUST NOT honour requests from readonly clients.
* `file-open-url url send_id` asks the peer to open a URL. When the peer advertises
  `open-url-ask`, the sender first sends a `file-data-request` with `type="url"`.
