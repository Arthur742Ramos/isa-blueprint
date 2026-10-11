# Dump evidence

`isabelle-blueprint dump` collects PIDE observations in a new `run-<id>`
directory beneath `build/pide-dump` on every invocation. Older runs and imported
directories are preserved. A successful command that writes no matching theorem
observations cannot reuse an older directory or establish a missing theorem.

When a fresh dump observes a referenced theorem, the tool runs its native proof
checker with proof status export enabled. Current status comes from that checker,
including oracle dependencies, source context and per-node input fingerprints.
The source context must agree before observation collection and verification.
`verification`, `proof_metadata_complete`, `observed_in_dump`, and
`evidence_reason` in the dump report explain the result.

`dump --from DIRECTORY` inspects an offline directory without running Isabelle.
Bare entity names, truncated records and absence of oracle text do not establish
proof completeness. These imports retain observations and oracle markers for
inspection, but their effective statuses are historical (`stale`) or unknown
(`named`). Missing records in an incomplete import do not establish `not_found`.
Run `isabelle-blueprint check` to obtain current native proof evidence.
This intentionally corrects earlier false proof promotions from offline dumps.

CLI reports and MCP reads restore whichever of `check_report.json` and
`dump_report.json` was written most recently (check wins equal filesystem write
times). A newer failed, incomplete or malformed artifact supersedes older
successful evidence. Copying or touching a report changes this ordering; the
selected report still needs valid native provenance before restoring current
proof status. Offline observations and failed attempts retain the previous check
time when their exact node, fact, theory and session reference matches.

Legacy dump reports remain readable as historical observations. Their old
`proof_status: proved` field alone cannot restore current proof trust.
