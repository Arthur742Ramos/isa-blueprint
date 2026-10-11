/** Canonical evidence decoding and refresh scheduling, independent of VS Code. */
import * as path from "path";
export interface BlueprintNode {
  id: string;
  kind: string;
  title: string;
  uses: string[];
  isabelle: { fact?: string | null; theory?: string | null; session?: string | null };
  status: { blueprint: string; formal: string; agent: string; last_checked?: string | null; check_error?: string | null };
  source?: { file?: string | null; line?: number | null };
}

export interface BlueprintProject { name: string; source_files?: string[]; nodes: BlueprintNode[] }
export interface ProjectMetrics {
  nodeCount: number; targetCount: number; provedCount: number;
  problemCount: number; readyCount: number; coveragePercent: number | null;
}
export interface EvidenceSnapshot {
  schema_version: number;
  observed_at: string;
  project_root: string;
  project: BlueprintProject;
  metrics: {
    node_count: number; formal_target_count: number; proved_count: number; found_count: number;
    problem_count: number; stale_count: number; has_cycles: boolean; coverage_percent: number | null;
  };
  ready_task_ids: string[];
  evidence: { origin: string; state: string; reason: string | null; checked_at: string | null; attempted_at: string | null; report_path: string | null };
  node_evidence: Record<string, { state: string; origin: string; reason: string | null; authored_formal_claim: string; checked_at: string | null }>;
  inputs: { config_path: string; blueprint_paths: string[]; check_report_path: string; dump_report_path: string; isabelle_dirs: string[] };
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
function optionalString(value: unknown): boolean {
  return value == null || typeof value === "string";
}
function nullableString(value: unknown): boolean { return value === null || typeof value === "string"; }

export function validProject(value: unknown): value is BlueprintProject {
  if (!object(value) || typeof value.name !== "string" || !Array.isArray(value.nodes)) return false;
  if (value.source_files !== undefined && !strings(value.source_files)) return false;
  return value.nodes.every((node: unknown) => {
    if (!object(node) || !object(node.status) || !object(node.isabelle)) return false;
    if (![node.id, node.kind, node.title, node.status.formal, node.status.blueprint, node.status.agent].every((item) => typeof item === "string")) return false;
    if (!strings(node.uses) || ![node.isabelle.fact, node.isabelle.theory, node.isabelle.session, node.status.check_error, node.status.last_checked].every(optionalString)) return false;
    return node.source === undefined || (object(node.source) && optionalString(node.source.file) &&
      (node.source.line == null || (typeof node.source.line === "number" && Number.isInteger(node.source.line) && node.source.line > 0)));
  });
}

export function decodeSnapshot(raw: string): EvidenceSnapshot {
  const value: unknown = JSON.parse(raw);
  if (!object(value) || value.schema_version !== 1 || !validProject(value.project) ||
      typeof value.observed_at !== "string" || typeof value.project_root !== "string" ||
      !object(value.metrics) || !object(value.evidence) || !object(value.inputs) ||
      !object(value.node_evidence) || !strings(value.ready_task_ids)) {
    throw new Error("Unsupported or malformed canonical snapshot; update the CLI or check its output.");
  }
  const m = value.metrics;
  const counts = [m.node_count, m.formal_target_count, m.proved_count, m.found_count, m.problem_count, m.stale_count];
  if (!counts.every((n) => typeof n === "number" && Number.isInteger(n) && n >= 0) ||
      typeof m.has_cycles !== "boolean" || (m.coverage_percent !== null &&
        !(typeof m.coverage_percent === "number" && Number.isInteger(m.coverage_percent) && m.coverage_percent >= 0 && m.coverage_percent <= 100))) {
    throw new Error("Malformed canonical snapshot metrics.");
  }
  const e = value.evidence;
  const i = value.inputs;
  if (typeof e.origin !== "string" || typeof e.state !== "string" ||
      ![e.reason, e.checked_at, e.attempted_at, e.report_path].every(nullableString) ||
      ![i.config_path, i.check_report_path, i.dump_report_path].every((v) => typeof v === "string") ||
      !strings(i.blueprint_paths) || !strings(i.isabelle_dirs)) throw new Error("Malformed snapshot evidence or input paths.");
  const nodeIds = new Set(value.project.nodes.map((node) => node.id));
  if (nodeIds.size !== value.project.nodes.length || m.node_count !== value.project.nodes.length ||
      (m.formal_target_count as number) > (m.node_count as number) ||
      [m.proved_count, m.found_count, m.problem_count, m.stale_count].some((count) =>
        (count as number) > (m.formal_target_count as number))) {
    throw new Error("Inconsistent canonical snapshot node counts.");
  }
  if (new Set(value.ready_task_ids).size !== value.ready_task_ids.length ||
      value.ready_task_ids.some((id) => !nodeIds.has(id))) throw new Error("Malformed snapshot ready task IDs.");
  for (const id of nodeIds) {
    const entry = value.node_evidence[id];
    if (!object(entry) || ![entry.state, entry.origin, entry.authored_formal_claim].every((v) => typeof v === "string") ||
        ![entry.reason, entry.checked_at].every(nullableString)) throw new Error("Malformed per-node evidence.");
  }
  return value as unknown as EvidenceSnapshot;
}

export function snapshotMetrics(snapshot: EvidenceSnapshot): ProjectMetrics {
  return { nodeCount: snapshot.metrics.node_count, targetCount: snapshot.metrics.formal_target_count,
    provedCount: snapshot.metrics.proved_count, problemCount: snapshot.metrics.problem_count,
    readyCount: snapshot.ready_task_ids.length, coveragePercent: snapshot.metrics.coverage_percent };
}

export function invalidateProject(project: BlueprintProject, reason: string): BlueprintProject {
  return { ...project, nodes: project.nodes.map((node) => ({ ...node, status: {
    ...node.status, formal: node.status.formal === "missing" ? "missing" : "stale",
    agent: "blocked", check_error: node.status.formal === "missing" ? null : reason,
  } })) };
}

export function pendingMetrics(metrics: ProjectMetrics): ProjectMetrics {
  return { ...metrics, provedCount: 0, problemCount: 0, readyCount: 0,
    coveragePercent: metrics.targetCount > 0 ? 0 : null };
}

export function sourceInputPaths(root: string, project?: BlueprintProject, inputs?: EvidenceSnapshot["inputs"], report?: string): string[] {
  return [path.join(root, "isabelle-blueprint.toml"), report, ...inputs?.blueprint_paths ?? [],
    inputs?.check_report_path, inputs?.dump_report_path, ...project?.source_files ?? [],
    ...project?.nodes.map((node) => node.source?.file) ?? [], path.join(root, ".isabelle-blueprint/assignments.json")]
    .filter((file): file is string => typeof file === "string")
    .map((file) => path.resolve(root, file));
}

export function affectsSourcePath(root: string, file: string, project?: BlueprintProject, inputs?: EvidenceSnapshot["inputs"], report?: string): boolean {
  const normalize = (value: string) => process.platform === "win32" ? path.resolve(value).toLowerCase() : path.resolve(value);
  if (sourceInputPaths(root, project, inputs, report).some((source) => normalize(source) === normalize(file))) return true;
  const inside = (directory: string) => {
    const relative = path.relative(directory, file);
    return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
  };
  // Configured blueprint paths are unknown until the first canonical read.
  if (!inputs && inside(root)) return true;
  const native = /\.(thy|ML)$/i.test(file) || ["ROOT", "ROOTS"].includes(path.basename(file));
  if (native && [root, ...inputs?.isabelle_dirs ?? []].some(inside)) return true;
  return inside(root) && ["blueprint.md", "blueprint.tex", "project.json", "check_report.json", "dump_report.json"].includes(path.basename(file));
}

export function hasDirtySnapshotInputs(root: string, snapshot: EvidenceSnapshot, files: string[]): boolean {
  return files.some((file) => affectsSourcePath(root, file, snapshot.project, snapshot.inputs));
}

interface Slot {
  revision: number; busy: boolean; dirty: boolean; delay: number;
  timer?: ReturnType<typeof setTimeout>; waiters: Array<() => void>;
}

/** One request per project at a time; obsolete responses never reach the UI. */
export class RefreshQueue<T> {
  private slots = new Map<string, Slot>();
  private disposed = false;
  constructor(
    private load: (root: string) => Promise<T>,
    private apply: (root: string, value: T) => void,
    private invalidate: (root: string) => void,
    private error: (root: string, error: unknown) => void,
  ) {}

  request(root: string, delay = 0): Promise<void> {
    if (this.disposed) return Promise.resolve();
    let slot = this.slots.get(root);
    if (!slot) { slot = { revision: 0, busy: false, dirty: false, delay, waiters: [] }; this.slots.set(root, slot); }
    slot.revision++; slot.dirty = true; slot.delay = delay;
    this.invalidate(root);
    const done = new Promise<void>((resolve) => slot!.waiters.push(resolve));
    if (!slot.busy) this.schedule(root, slot);
    return done;
  }

  remove(root: string): void {
    const slot = this.slots.get(root);
    if (slot?.timer) clearTimeout(slot.timer);
    slot?.waiters.splice(0).forEach((resolve) => resolve());
    this.slots.delete(root);
  }
  dispose(): void {
    this.disposed = true;
    for (const root of this.slots.keys()) this.remove(root);
  }
  private schedule(root: string, slot: Slot): void {
    if (slot.timer) clearTimeout(slot.timer);
    slot.timer = setTimeout(() => { slot.timer = undefined; void this.run(root, slot); }, slot.delay);
  }
  private async run(root: string, slot: Slot): Promise<void> {
    if (slot.busy || this.disposed || this.slots.get(root) !== slot) return;
    slot.busy = true; slot.dirty = false;
    const revision = slot.revision;
    try {
      const value = await this.load(root);
      if (!this.disposed && this.slots.get(root) === slot && revision === slot.revision) this.apply(root, value);
    } catch (error) {
      if (!this.disposed && this.slots.get(root) === slot && revision === slot.revision) this.error(root, error);
    } finally {
      slot.busy = false;
      if (!this.disposed && this.slots.get(root) === slot && slot.dirty) this.schedule(root, slot);
      else slot.waiters.splice(0).forEach((resolve) => resolve());
    }
  }
}
