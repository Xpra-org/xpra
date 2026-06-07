# Cross-side subsystem "loopback" tests

These `*_loopback_test.py` files wire a **client** subsystem to its matching
**server** subsystem (and per-client *source*) in a single process and exchange
real packets between them. They test the *contract between the two sides* —
packet names/shapes, capability negotiation, request/response round-trips —
which the isolated client-only / server-only subsystem tests cannot catch.

This is possible because subsystems are now self-contained composition objects
(`StubClientMixin` on the client, `StubSubsystem` on the server) rather than
mixins that need the whole client/server class assembled.

## How it works

`loopback_util.py` provides `LoopbackTest`. Transport is **direct object
pass-through**: when one side calls `send(...)`, the harness looks up the
matching `_process_*` handler on the other side and calls it with a `Packet`.
No sockets, no serialization.

```
client.send("ping", t)            ->  server.packet_handlers["ping"](proto, Packet("ping", t))
server_source.send_async("ping_echo", ...) ->  client.packet_handlers["ping_echo"](Packet(...))
```

- client `_process_*` handlers take `(packet)`; server handlers take `(proto, packet)`.
- legacy packet aliases (e.g. `notify_show` -> `notification-show`) are resolved
  automatically, so assert against the packet-type **constants**, not literals.
- packets that crossed the wire are recorded in `self.c2s` (client→server) and
  `self.s2c` (server→client) as `(packet_type, *args)` tuples.
- a missing handler on the receiving side fails loudly (this is the point).

It reuses the existing harnesses verbatim: `ClientMixinTest`
(`client/subsystem/clientmixintest_util.py`) and `ServerMixinTest`
(`server/subsystem/servermixintest_util.py`).

## Writing a new one

```python
from unit.loopback_util import LoopbackTest

class FooLoopbackTest(LoopbackTest):
    def test_xxx(self):
        client, server, source = self.connect(
            FooClient, FooServer, FooConnection,
            client_opts=..., server_opts=..., caps={...})
        client.do_something()                       # -> sends a packet
        self.assertIn(("foo", 1), [tuple(p) for p in self.c2s])
        self.assertEqual(source.something, 1)       # server applied it
```

`connect()` returns `(client_subsystem, server_subsystem, server_source)`.
Pass `source_class=None` (or `StubClientConnection`) for subsystems with no
dedicated source; server→client wiring is skipped when there is no source.

## Running

Tests resolve `xpra` from the **installed** copy unless the repo root is first
on `PYTHONPATH` (see `../../../CLAUDE.md`). To exercise working-tree changes:

```sh
PYTHONPATH=$PWD:$PWD/tests/unittests python3 tests/unittests/unit/ping_loopback_test.py
```

Or via the build runner (builds + installs first):

```sh
python3 setup.py unittests unit.ping_loopback_test
```

## Patterns / gotchas

Subsystems differ in how much of the surrounding client/server they assume.
Recurring accommodations, with examples:

- **Background threads / native deps**: patch out codec/audio discovery so the
  test stays hermetic and fast — `AudioClient.load`, `AudioServer.init_audio_options`,
  `Encodings.load`, `EncodingServer.setup`.
- **Backwards-compat waits/paths**: `audio` patches `BACKWARDS_COMPATIBLE=False`
  to skip a 5s wait; `cursor` sets `cursor_backwards_compatible=False` to emit the
  clean `cursor-data` packet instead of the legacy `cursor` one.
- **No network compression layer**: direct pass-through doesn't unwrap
  `Compressed` objects — use a raw payload and stub `compressed_wrapper` with
  identity if the path compresses (see `cursor`).
- **Window/display plumbing**: handlers that fan out to window sources leave no
  observable state — inject a `MagicMock` window source
  (`source.window_sources = {1: ws}`, see `encoding`) or stub the client UI sink
  (`client.set_windows_cursor`, `client._id_to_window`, see `cursor`).
- **Source required even when "sourceless"**: `logging` has no dedicated source
  but its handler bails if `get_server_source()` is `None`, so pass the generic
  `StubClientConnection`.
- **Capability preconditions**: some sources reject empty caps (e.g. `encoding`
  raises if the client declares no encodings) — provide the minimal caps.
- **Queued sends (not `send()`)**: a few client subsystems (e.g. `pointer`) don't
  call `send()` — they append to `_ordinary_packets` / `_mouse_position` and flush
  via `have_more()`. The harness drains those queues in `_wire`, so driving e.g.
  `send_mouse_position` still works; nothing special is needed in the test.
- **Module-level `BACKWARDS_COMPATIBLE`**: when forcing it off to pin a modern
  packet name, patch it with `start()` + `addCleanup(stop)` (not a `with` scoped to
  `connect()`) so it stays patched while the test body sends (see `clipboard`).
- **Server handler is a stub**: some server `_process_*` handlers only log (the
  real work lives elsewhere, e.g. window models) — pick a path with an observable
  effect. The window pair uses the bell path for this reason.

## Coverage

| subsystem    | direction(s)            | notes                                  |
|--------------|-------------------------|----------------------------------------|
| ping         | both                    | full echo round-trip                   |
| audio        | both                    | capability negotiation + data path     |
| bandwidth    | client→server           | bandwidth-limit applied to source      |
| notification | both                    | action/close up, show down             |
| encoding     | client→server           | quality/speed dispatch to window source|
| logging      | client→server           | remote logging into server sink        |
| cursor       | server→client           | cursor-data build + decode             |
| power        | client→server           | suspend/resume re-emitted on source    |
| command      | client→server           | start-command dispatch (mocked spawn)  |
| pointer      | client→server           | mouse position recorded on source      |
| window-bell  | server→client           | bell packet build + decode             |
| clipboard    | server→client           | status-toggle (no GTK helper)          |

## Auth handshake loopback

A separate harness in `unit/auth/auth_loopback_util.py` covers the authentication
handshake. It is not a packet subsystem, so it does not use `loopback_util.py`:
the server side is a `SysAuthenticator` (`xpra/auth/*`) and the client side is the
`ChallengeClient` mixin (`xpra/client/base/challenge.py`).

`challenge_roundtrip(handler, authenticator)` builds the real `challenge` packet
from the authenticator, runs it through the real client dispatch
(`do_process_challenge` → `send_challenge_reply` → `send_hello`, captured), then
feeds the captured `challenge_response` back into `authenticator.authenticate`.
This catches drift between the client's salt/digest computation and the server's
`authenticate_hmac` verification — which `unit/server/auth_test.py` (hand-rolls the
client math) and `unit/auth/auth_handlers_test.py` (handlers in isolation) miss.

`unit/auth/auth_loopback_test.py` covers the hmac pairs that flow through the real
client end-to-end: `uri`/`env`/`file`/`prompt` handlers ↔ `password`/`env`/`file`
auth, plus negatives (wrong password, missing credential).

Deferred: **scram** — the client `send_challenge_reply` cannot send raw SCRAM
responses (`gendigest` returns `b""` for `SCRAM-*` and there is no scram code under
`xpra/client/`); its stage exchange is covered directly by `auth_scram_test.py`.
`kerberos`/`gss`/`fido2`/`u2f` need external services or hardware tokens.
