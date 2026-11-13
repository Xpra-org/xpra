# Fuzz harnesses

[Atheris](https://github.com/google/atheris) harnesses for the decoders that parse network input,
run continuously by [OSS-Fuzz](https://github.com/google/oss-fuzz/tree/master/projects/xpra), see [#5148](https://github.com/Xpra-org/xpra/issues/5148).

| harness | target |
|---|---|
| `rencodeplus_fuzzer.py` | the `rencodeplus` packet decoder |
| `packet_header_fuzzer.py` | packet header parsing, validation and resynchronization |
| `decompress_fuzzer.py` | the `lz4`, `brotli` and `zstd` decompressors |
| `packet_datagram_fuzzer.py` | a whole packet: header, decompression and decoding |
| `websocket_header_fuzzer.py` | websocket frames, including the native unmasking code |

`make_corpus.py` generates the seed corpus from valid packets.

## Running locally

Against the working tree, using a build with the Cython extensions compiled in place:
```sh
pip install atheris
python3 setup.py build_ext --inplace
PYTHONPATH=. python3 tests/fuzz/make_corpus.py /tmp/corpus
PYTHONPATH=. python3 tests/fuzz/rencodeplus_fuzzer.py -max_total_time=60 /tmp/corpus/rencodeplus_fuzzer
```
This only instruments the Python code. To also get coverage and sanitizer checks for the native code,
use the OSS-Fuzz tooling with a local checkout:
```sh
python3 infra/helper.py build_image xpra
python3 infra/helper.py build_fuzzers --sanitizer address xpra /path/to/xpra
python3 infra/helper.py run_fuzzer xpra rencodeplus_fuzzer
```
