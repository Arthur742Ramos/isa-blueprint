# Canonical evidence snapshots

Read `isabelle-blueprint snapshot --json` for current project nodes, the shared
planning metrics, and canonical ready task IDs. The MCP `evidence_snapshot` tool
and `blueprint://evidence` resource return the same payload. A project selector
on the tool chooses another project in the server's catalog.

This read does not build Isabelle sessions or write reports, trends, tasks or
agent memory. It queries native provenance once when the selected saved report
contains a source fingerprint. Each later read revalidates provenance; there is
no time window in which old native trust is reused.

The payload has `schema_version: 1`. `observed_at` is the current read time;
`evidence.attempted_at` records the selected report's attempt time and
`evidence.checked_at` records its native check time when a check ran. These times
do not certify proof completeness: inspect the evidence state and node status.
`node_evidence` retains each node's authored formal claim and historical check
time separately from its effective status. An absent, malformed or incomplete
observation supplies no node evidence time.

Evidence states distinguish:

- `absent`: no saved native evidence; formal statuses remain authored claims.
- `malformed`: the latest report cannot be read or its evidence fields are invalid.
- `legacy`: required source provenance or a report timestamp is missing.
- `source_changed`: the saved source context differs, or the producer marked
  its context as changed/unverifiable during the check.
- `probe_unavailable`: the current native provenance query could not establish
  a digest; inspect the Isabelle executable, session and directory configuration.
- `node_changed`: a node's reference or proof inputs no longer match its record.
- `current`: provenance and matching inputs are current. The node's formal
  status still distinguishes fact existence, complete proofs and oracle dependencies.
- `incomplete`: the selected attempt did not supply usable current evidence;
  its actual error is retained in `reason`.
- `offline`: raw dump observations without current native proof verification.

Nodes without a formal target use `no_target`. A changed node does not make
unaffected nodes' evidence historical. `inputs` supplies the resolved blueprint,
configuration and report paths plus configured Isabelle directories for clients
that watch source edits.

Existing planning metric definitions and the `found` dependency-completion
policy are preserved. A `proved` authored claim can contribute to those metrics
when evidence is absent; `origin: authored` and `authored_formal_claim` make that
distinction explicit. Clients should show evidence state alongside coverage and
ready counts. Run `isabelle-blueprint check --proof-status` to establish or renew
native proof evidence.

The packaged `snapshot.schema.json` describes the payload. Existing CLI/Action
outputs and JSON fields remain unchanged; this command and these fields are
additive. Native provenance checking may take time, so clients should coalesce
refresh requests and invalidate displayed proof claims while new input is pending.
