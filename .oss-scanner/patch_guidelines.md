# How we would like patches made

## Size and scope of a fix
- against the `master` branch, as narrow as possible: fix the bug, no unrelated refactoring or reformatting
- validate data from the peer where it enters, in the packet handler (or the decoder) that receives it,
  rather than deep inside the subsystem that eventually uses it
- if the same mistake exists in sibling code (ie: the same size calculation in other codecs, the same unvalidated field
  in other packet handlers), fix all of them in the same patch and say so
- reject invalid required values, drop invalid optional ones, and log a short warning without echoing the hostile data in full
- do not change the network protocol or add new options unless there is no other way to fix the issue

## Code style
- follow the surrounding code; the patch must pass `ruff check ./xpra --ignore E902 --ignore E501`
  (ruff does not check Cython files, so `.pyx` / `.pxd` changes must be checked by building them)
- lines up to about 120 characters, 150 when that is more readable - do not break lines just to make them shorter
- add type hints to new functions
- to check whether a value belongs to an `Enum`, use `try: Enum(value)` / `except ValueError`,
  not the private `_value2member_map_`
- few comments: only where the code is not obvious, explaining why rather than what
- Cython: keep `cdef` types explicit, check sizes with 64-bit arithmetic before allocating or copying,
  and make sure the module still compiles: `python3 setup.py build_ext --inplace`

## Tests
- add a regression test to the existing test module matching the source file, under `tests/unittests/unit/`
  (ie: `xpra/codecs/argb/argb.pyx` -> `tests/unittests/unit/codecs/argb_test.py`), or create one there following the same layout
- the test should fail without the fix and pass with it; run it as a regular user (not root)
  with `python3 setup.py unittests unit/codecs/argb_test.py`
- tests that need an X11 display must start their own `Xvfb` on a free high display number, never use `:0`

## Branch and commit message
- a single commit against `master`
- subject line: a short lowercase description of the change, ie: `validate the icon size before decoding`,
  without a `component:` prefix and without a trailing period
- the body explains the bug, how it can be triggered and by whom (client, server, unauthenticated peer)
- for an actual vulnerability, also add a line to the "Known issues" list in `docs/SECURITY.md`
  describing the issue and the affected versions
