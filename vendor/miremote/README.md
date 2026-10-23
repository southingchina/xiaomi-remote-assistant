# Source and license provenance

The local `capture_support.py` file contains selected and modified functions from
[`qi-o/miremote-vibe`](https://github.com/qi-o/miremote-vibe), commit
`2f477fbdd3634d7767b20f07f9835b86f2a1540b`:

- `miremote/tapinject.py`: `is_wudfhost_process`, `inject_library`.
- `miremote/backkey.py`: `enable_debug_privilege`.

The unmodified upstream `LICENSE` is included here. It expressly licenses these
two files under GPL-3.0, derived from
[`xxb26553663-star/remote-bridge-hub`](https://github.com/xxb26553663-star/remote-bridge-hub).
The full GNU GPL v3 text is in `COPYING.GPL3`.

Modifications made 2026-10-23: retained only the functions above, added a helper
singleton, revalidated the target process before injection, rejected incomplete
DLL-path writes, retained the remote path if LoadLibrary has not finished, and
declared the missing 64-bit privilege API types. No upstream process termination,
host restart, download, CLI or application service code is included. The complete
modified source is delivered as `capture_support.py` in the source distribution.

Native usage mapping was cross-checked against `miremote/backkey.py`'s
`USAGE_NAMES` and `VOICE_USAGE`, plus the previously observed RC003 mapping in
the original bridge. No device identity, calibration, tokens or runtime state was
copied into this package.
