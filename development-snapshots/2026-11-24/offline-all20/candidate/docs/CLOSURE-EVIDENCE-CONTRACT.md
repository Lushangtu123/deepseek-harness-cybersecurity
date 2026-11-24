# Closure Evidence Contract v2

Status: pending independent host/VM review. This document describes the offline evidence contract. It does not approve the product, does not promote formal targets beyond 0/16, and does not unblock R3.

## Capture and index path bases

The capture records stdout and stderr file names relative to the capture file parent directory. The fixed return-code sibling is returncode.txt in that same parent directory. The capture resultFile is either absolute or a path relative to the capture recorded cwd. In the evidence index, captureFile and resultFile are index-relative paths, relative to the evidence index parent directory. Index entries are minimal: suite, command, captureFile, captureSha256, resultFile, and resultSha256. Builders use the shared reader and do not select alternate files from hints or by directory search.

Old legacy index raw fields such as stdoutFile, stderrFile, and returncodeFile are accepted only when they match the derived files. Those fields are not authoritative. The validator and sealer reread the actual artifacts and derive decisions from the reread bytes.

## Validation, proof, and sealing

The evidence index is validated by rereading the actual capture, result, stdout, stderr, and fixed return-code files. The proof binds the source manifest, the evidence index, and the derived artifacts. verify_proof always propagates validatedArtifacts after rereading, and no external readset JSON is trusted as a substitute for validation.

The sealer requires exactly one real evidence index and exactly one real proof among the closure members. It performs a fresh verify_proof even for standalone use. A supplied expected verification is only a comparison context; it is never accepted as proof. If context is supplied, fresh proof, index, and source hashes plus sorted derived artifact identities, paths, hashes, and sizes must match. run_gate creates that context from its first proof verification, invokes the after_proof hook, and then passes the context to the sealer so a replacement index or proof must be revalidated and must match the original context.

The sealer uses only fresh derived validatedArtifacts as its evidence source. For each of the five roles it materializes the original bytes under evidence/<safe-suite>/capture.json, result.json, stdout.bin, stderr.bin, and returncode.txt. Suite names are safe single components. Before copying, the current device, inode, size, and SHA-256 must match the derived record. After copying, the actual destination bytes are rehashed. Input proof, index, source, and readset are reverified after copies, and all materialized members are rehashed before manifest publication.

The closure manifest includes validatedArtifactMap, a tool-derived list of the actual derived artifact records extended with archivePath. This map is not an index self-claim. Original capture bytes are unchanged, including absolute provenance paths recorded inside the capture. After export, package file-set and hash verification must work on the package alone. That is not a portable re-execution proof claim.

## Publication rules

Formal files are published with an exclusive pending file, data fsync, pending-byte readback, and no-overwrite hard-link publication. Existing targets are never replaced. This provides data fsync and no-overwrite publication, not full crash durability. Cleanup uncertainty handling is incomplete; it must not be described as fully disclosed if code ignores cleanup results. A failure before validation, publication, or readback leaves no formal proof or closure manifest with a verified or pass claim. Partial owned package copies may remain as diagnostics but are not formal success records.

## Packaged files and limits

The closure manifest covers the entire copied readset, source files, the protocol manifest, and the fixed REPORT, phase-result, evidence-index, and proof files. Source files outside the package base are copied under source/. Source already below the base may be reused at safe original-relative paths. No blanket deletion or cache cleanup is performed, and source bytes are not modified.

Absolute local paths are rehashed for local revalidation but are not a portable execution proof. The full-suite phase and VM phase remain pending independent review. Formal targets remain 0/16 and R3 remains blocked.
