No confirmed safety blocker in the corrected tests.

The two S3 tests now exercise the actual production seam: `tree()` reads through `os.fdopen(os.dup(file),'rb')`, not obsolete `Path.read_bytes`. The first test records exactly one `stream.read`, verifies the returned bytes hash to the expected dependency digest, and would fail if the implementation used another read API. The second mutates the same path after the fd read and before the post-read `fstat`, deterministically changing size/metadata so `tree()` raises `ValueError('Dependency changed during read')`; the read count remains one.

Scoped limitations, not blockers: both tests are white-box and bind to `os.fdopen`; a future switch to `os.read` or another path would need a matching test update. The mutation test relies on ordinary filesystem metadata behavior, though the size change makes it strong here. This remains evidence-only; the Node excerpt is context, not live or R3 acceptance.
