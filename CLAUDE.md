# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Build and Install
```sh
# Full build and install (required before running tests)
python3 setup.py install --prefix=/usr --root=dist/

# Build only (without installing)
python3 setup.py build

# Skip optional components to speed up builds
python3 setup.py install --without-nvidia --without-printing --without-docs
```

### Run Tests
```sh
# Run all unit tests (builds first, then runs)
python3 setup.py unittests

# Run a single test file
cd tests/unittests && PYTHONPATH=. python3 unit/codecs/argb_test.py

# Run tests by module path
python3 setup.py unittests unit.codecs.argb_test

# Skip slow or flaky tests (as done in CI)
python3 setup.py unittests --skip-fail unit.client.splash_test --skip-slow unit.x11.x11_server_test
```

### Lint
```sh
# ruff (fast linter, used in pre-commit)
ruff check ./xpra --ignore E902 --ignore E501

# flake8
flake8 --max-line-length=200 --ignore=E203,E231,E225,E226,E252,E221,E741,E262,E265,E501
```

Max line length is 120 (ruff config) / 200 (flake8 CI config). `E741` (ambiguous variable names) is always ignored.

## Architecture

Xpra is a remote display system with a client-server architecture. Both sides are composed of modular "subsystems" (mixins) assembled at runtime.

### Entry Point
`xpra/scripts/main.py` — parses CLI args and dispatches to server, client, or utility modes.

### Server (`xpra/server/`)
- `core.py` — `ServerCore`: base class handling sockets, connections, authentication, and the packet dispatch loop.
- `base.py` — `ServerBase`: extends `ServerCore` with per-client source management.
- `subsystem/` — one file per feature (clipboard, audio, encoding, keyboard, pointer, display, mmap, etc.). Each subsystem is mixed into the server class via `features.py`.
- `source/` — per-connected-client state objects, mirroring the subsystem structure.

### Client (`xpra/client/`)
- `base/client.py` — `XpraClientBase`: core connection/packet handling.
- `base/` — base mixins for network, factory, and feature negotiation.
- `subsystem/` — client-side subsystems mirroring the server's (clipboard, encoding, audio, keyboard, etc.).
- `gtk3/`, `qt6/`, `tk/`, `pyglet/` — GUI frontends. GTK3 is the primary desktop client.

### Network Layer (`xpra/net/`)
- `protocol/socket_handler.py` — `SocketProtocol`: threaded send/receive with header framing, compression, and encryption.
- `protocol/` — packet encoding/decoding (bencode, rencodeplus, etc.).
- `compression.py`, `crypto.py` — pluggable compression (lz4, brotli) and encryption (AES).
- `ssh/`, `tls/`, `quic/`, `websockets/` — transport adapters.
- `dispatch.py` — `PacketDispatcher`: routes incoming packets to `_process_<type>` handler methods.

### Codecs (`xpra/codecs/`)
Most codecs are Cython (`.pyx`) compiled to C extensions. Pure-Python fallbacks exist for some.
- `argb/` — pixel format conversions (Cython)
- `pillow/` — PIL-based encoder/decoder
- `video.py` — video pipeline management (CSC + encoder + decoder chains)
- `loader.py` — dynamic codec discovery and loading
- Each codec directory follows the pattern: `encoder.py`/`decoder.py` + optional `.pyx` implementation.

### Logging (`xpra/log.py`)
Logging uses a category system. Each module creates its own logger:
```python
from xpra.log import Logger
log = Logger("category")      # supports multiple categories: Logger("network", "ssl")
log("message %s", value)      # debug level
log.info(...)
log.warn(...)
log.error(...)
```
Debug output per category is toggled at runtime via `-d category` CLI flag or `XPRA_DEBUG_MODULES` env var.

### Subsystem Pattern
Both server and client use the same pattern: a `features.py` module defines boolean flags, and `factory.py` assembles the final class by collecting base classes from modules whose feature flag is enabled. This allows building lightweight clients/servers without unused subsystems.

### Cython Extensions
`.pyx` files alongside Python code are compiled by `setup.py`. The build detects available native libraries and conditionally compiles codecs. Run `python3 setup.py build_ext --inplace` to compile extensions in-place for development without a full install.
