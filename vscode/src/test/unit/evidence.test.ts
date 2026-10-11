import assert from "node:assert/strict";
import { test } from "node:test";
import * as path from "path";
import { EvidenceSnapshot, RefreshQueue, affectsSourcePath, decodeSnapshot, invalidateProject, pendingMetrics, snapshotMetrics, sourceInputPaths, hasDirtySnapshotInputs } from "../../evidence";

function fixture(): EvidenceSnapshot {
  return { schema_version: 1, observed_at: "2026-10-10T00:00:00Z", project_root: path.resolve("project"),
    project: { name: "Proofs", source_files: ["chapters/main.md"], nodes: [
      { id: "a", title: "A", kind: "lemma", uses: [], isabelle: { fact: "Demo.a" },
        status: { blueprint: "done", formal: "proved", agent: "done" }, source: { file: "chapters/main.md", line: 1 } },
      { id: "b", title: "B", kind: "lemma", uses: ["a"], isabelle: { fact: "Demo.b" },
        status: { blueprint: "stub", formal: "named", agent: "ready" } },
    ] }, metrics: { node_count: 2, formal_target_count: 2, proved_count: 1, found_count: 0,
      problem_count: 0, stale_count: 0, has_cycles: false, coverage_percent: 50 }, ready_task_ids: ["b"],
    evidence: { state: "current", origin: "check", reason: null, checked_at: "2026-10-09T00:00:00Z", attempted_at: "2026-10-09T00:00:00Z", report_path: "build/check_report.json" },
    node_evidence: { a: { state: "current", origin: "check", reason: null, checked_at: null, authored_formal_claim: "named" }, b: { state: "current", origin: "check", reason: null, checked_at: null, authored_formal_claim: "named" } },
    inputs: { config_path: "isabelle-blueprint.toml", blueprint_paths: ["chapters/main.md", "chapters/details.tex"],
      check_report_path: "evidence/check_report.json", dump_report_path: "evidence/dump_report.json", isabelle_dirs: [path.resolve("external-session")] } };
}

test("canonical metrics and ready IDs are consumed without editor reinterpretation", () => {
  const value = decodeSnapshot(JSON.stringify(fixture()));
  assert.deepEqual(snapshotMetrics(value), { nodeCount: 2, targetCount: 2, provedCount: 1, problemCount: 0, readyCount: 1, coveragePercent: 50 });
  value.metrics.coverage_percent = 1;
  assert.equal(snapshotMetrics(value).coveragePercent, 1);
});

test("pending source state clears claims and ready counts without mutating prior data", () => {
  const previous = fixture();
  const changed = invalidateProject(previous.project, "Source changed");
  assert.equal(previous.project.nodes[0].status.formal, "proved");
  assert.equal(changed.nodes[0].status.formal, "stale");
  assert.equal(changed.nodes[0].status.check_error, "Source changed");
  assert.deepEqual(pendingMetrics(snapshotMetrics(previous)), { nodeCount: 2, targetCount: 2, provedCount: 0, problemCount: 0, readyCount: 0, coveragePercent: 0 });
});

test("configured multi-source and external session paths are watched independently per root", () => {
  const value = fixture(); const root = value.project_root;
  for (const file of ["chapters/main.md", "chapters/details.tex", "evidence/check_report.json", "evidence/dump_report.json", "ROOT", "ROOTS", "src/Demo.thy", "src/aux.ML"])
    assert.equal(affectsSourcePath(root, path.join(root, file), value.project, value.inputs), true, file);
  assert.equal(affectsSourcePath(root, path.join(value.inputs.isabelle_dirs[0], "nested/aux.ML"), value.project, value.inputs), true);
  assert.equal(affectsSourcePath(path.resolve("other"), path.join(root, "src/Demo.thy")), false);
  assert.equal(affectsSourcePath(root, path.join(root, "notes.md"), value.project, value.inputs), false);
  assert.ok(sourceInputPaths(root, value.project, value.inputs).includes(path.join(root, "chapters/details.tex")));
});

test("bootstrap ignores unrelated paths; fresh metadata guards dirty custom sources", () => {
  const root = path.resolve("project");
  assert.equal(affectsSourcePath(root, path.join(root, "chapters/main.md")), false);
  assert.equal(affectsSourcePath(path.resolve("other"), path.join(root, "chapters/main.md")), false);
  const value = fixture();
  assert.equal(hasDirtySnapshotInputs(root, value, [path.join(root, "chapters/main.md")]), true);
  assert.equal(affectsSourcePath(root, path.join(root, "notes.md")), false);
  assert.equal(affectsSourcePath(root, path.join(root, "notes.md"), value.project, value.inputs), false);
});

test("ownership changes never count as proof inputs", () => {
  const value = fixture(); const file = path.join(value.project_root, ".isabelle-blueprint/assignments.json");
  assert.equal(affectsSourcePath(value.project_root, file), false);
  assert.equal(hasDirtySnapshotInputs(value.project_root, value, [file]), false);
});

test("new snapshot metadata detects already dirty external configured sources", () => {
  const value = fixture(); const external = path.resolve("external-blueprints/main.md");
  value.inputs.blueprint_paths.push(external);
  assert.equal(hasDirtySnapshotInputs(value.project_root, value, [external]), true);
  assert.equal(hasDirtySnapshotInputs(value.project_root, value, [path.join(value.project_root, "notes.md")]), false);
});

test("malformed, old, and incomplete CLI outputs cannot become current evidence", () => {
  for (const mutate of [
    (v: any) => { v.schema_version = 2; }, (v: any) => { v.metrics.proved_count = "1"; },
    (v: any) => { v.metrics.coverage_percent = -1; }, (v: any) => { v.project.nodes[0].status = null; },
    (v: any) => { v.ready_task_ids = ["ghost"]; }, (v: any) => { v.ready_task_ids = ["b", "b"]; },
    (v: any) => { v.inputs.blueprint_paths = 7; }, (v: any) => { delete v.node_evidence.a; },
    (v: any) => { delete v.evidence.reason; }, (v: any) => { delete v.node_evidence.a.checked_at; },
    (v: any) => { v.metrics.proved_count = 3; }, (v: any) => { v.project.nodes[1].id = "a"; },
  ]) {
    const value = fixture(); mutate(value);
    assert.throws(() => decodeSnapshot(JSON.stringify(value)));
  }
  assert.throws(() => decodeSnapshot("not JSON"));
  assert.throws(() => decodeSnapshot(JSON.stringify(fixture().project)));
});

test("unknown additive fields and future evidence states remain readable", () => {
  const value = fixture(); value.evidence.state = "future_reason";
  const read = decodeSnapshot(JSON.stringify({ ...value, extra: true }));
  assert.equal(read.evidence.state, "future_reason");
});

test("large multilingual projects keep their IDs and source strings intact", () => {
  const value = fixture();
  value.project.nodes = Array.from({ length: 1000 }, (_, i) => ({ ...value.project.nodes[0], id: `lemma-${i}`, title: "\u5b9a\u7406 - prova \u03b1\u03b2\u03b3 \u0645\u0628\u0631\u0647\u0646\u0629 ".repeat(10) }));
  value.ready_task_ids = [];
  value.metrics.node_count = value.metrics.formal_target_count = 1000;
  value.node_evidence = Object.fromEntries(value.project.nodes.map((node) => [node.id, value.node_evidence.a]));
  const decoded = decodeSnapshot(JSON.stringify(value));
  assert.equal(decoded.project.nodes.length, 1000);
  assert.equal(decoded.project.nodes[999].title, value.project.nodes[0].title);
});

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 10));
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }

test("burst requests coalesce and invalidation happens before async work", async () => {
  let calls = 0; let invalidations = 0; const applied: number[] = [];
  const queue = new RefreshQueue(async () => ++calls, (_, value) => applied.push(value), () => invalidations++, () => assert.fail());
  const requests = Array.from({ length: 20 }, () => queue.request("a", 1));
  assert.equal(calls, 0); assert.equal(invalidations, 20);
  await Promise.all(requests);
  assert.equal(calls, 1); assert.deepEqual(applied, [1]); queue.dispose();
});

test("obsolete in-flight responses are ignored and only the latest request is applied", async () => {
  const first = deferred<number>(); const second = deferred<number>(); const applied: number[] = [];
  let calls = 0; let busy = 0; let maximum = 0;
  const queue = new RefreshQueue(async () => {
    busy++; maximum = Math.max(maximum, busy);
    const value = await (++calls === 1 ? first.promise : second.promise); busy--; return value;
  }, (_, value) => applied.push(value), () => {}, () => assert.fail());
  const a = queue.request("root"); await tick();
  const b = queue.request("root"); const c = queue.request("root");
  first.resolve(1); await tick();
  assert.deepEqual(applied, []); assert.equal(calls, 2);
  second.resolve(3); await Promise.all([a, b, c]);
  assert.deepEqual(applied, [3]); assert.equal(maximum, 1); queue.dispose();
});

test("independent roots, errors, removal and disposal do not reuse obsolete claims", async () => {
  const a = deferred<number>(); const b = deferred<number>(); const applied: string[] = [];
  const queue = new RefreshQueue((root) => root === "a" ? a.promise : b.promise, (root) => applied.push(root), () => {}, () => assert.fail());
  const pendingA = queue.request("a"); const pendingB = queue.request("b"); await tick();
  queue.remove("a"); a.resolve(1); b.resolve(2); await Promise.all([pendingA, pendingB]);
  assert.deepEqual(applied, ["b"]); queue.dispose();
  let errors = 0;
  const failed = new RefreshQueue(async () => { throw new Error("old CLI"); }, () => assert.fail(), () => {}, (_, error) => { assert.match(String(error), /old CLI/); errors++; });
  await failed.request("root"); assert.equal(errors, 1); failed.dispose();
  await failed.request("root"); assert.equal(errors, 1);
});
