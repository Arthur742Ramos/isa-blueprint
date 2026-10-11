import assert from "node:assert/strict";
import * as fs from "fs/promises";
import * as path from "path";
import { execFile } from "child_process";
import { promisify } from "util";
import * as vscode from "vscode";

const exec = promisify(execFile);
async function waitFor(predicate: () => boolean, label: string): Promise<void> {
  const deadline = Date.now() + 120000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`Timed out: ${label}`);
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}
async function snapshot(root: string): Promise<any> {
  const result = await exec("isabelle-blueprint", ["snapshot", root, "--json"], { timeout: 60000 });
  return JSON.parse(result.stdout);
}
async function mcpSnapshot(root: string): Promise<any> {
  const program = `import asyncio,json,sys
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
async def read():
    parameters=StdioServerParameters(command=sys.executable,args=["-m","isabelle_blueprint.mcp_server","--project-dir",sys.argv[1]])
    async with stdio_client(parameters) as (receive,send):
        async with ClientSession(receive,send) as session:
            await session.initialize()
            result=await session.call_tool("evidence_snapshot",arguments={})
            assert not result.isError
            print(json.dumps(result.structuredContent))
asyncio.run(read())`;
  const result = await exec("python", ["-c", program, root], { timeout: 60000 });
  return JSON.parse(result.stdout);
}

export async function run(): Promise<void> {
  const first = process.env.ISABELLE_BLUEPRINT_HOST_FIRST!;
  const second = process.env.ISABELLE_BLUEPRINT_HOST_SECOND!;
  const kernel = process.env.ISABELLE_BLUEPRINT_EDITOR_KERNEL_TESTS === "1";
  const extension = vscode.extensions.getExtension("isabelle-blueprint.isabelle-blueprint-vscode");
  assert.ok(extension, "extension is loaded into a real development host");
  const api = await extension.activate();
  const view = (root: string) => api.snapshotState().find((p: any) => p.projectRoot === root);
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  await waitFor(() => view(first) && view(second), "both workspace roots");
  const initial = await snapshot(first); const mcp = await mcpSnapshot(first);
  assert.deepEqual(initial.metrics, mcp.metrics);
  assert.deepEqual(initial.ready_task_ids, mcp.ready_task_ids);
  assert.equal(view(first).metrics.coveragePercent, initial.metrics.coverage_percent);
  assert.deepEqual(view(first).readyTaskIds, initial.ready_task_ids);
  assert.equal(view(first).state, kernel ? "current" : "absent");
  assert.equal(view(first).metrics.provedCount, 1);
  assert.deepEqual(view(second).readyTaskIds, ["other"]);

  const assignments = path.join(first, ".isabelle-blueprint/assignments.json");
  await fs.mkdir(path.dirname(assignments), { recursive: true });
  await fs.writeFile(assignments, JSON.stringify({ schema_version: 1, nodes: { clean: { owner: "Ada" } } }));
  await waitFor(() => view(first).owners.clean === "Ada", "ownership refresh without proof invalidation");
  const ownershipDocument = await vscode.workspace.openTextDocument(assignments);
  const ownershipEditor = await vscode.window.showTextDocument(ownershipDocument);
  await ownershipEditor.edit((builder) => builder.insert(new vscode.Position(0, 0), " "));
  assert.equal(view(first).state, kernel ? "current" : "absent");
  assert.equal(view(first).metrics.provedCount, 1);
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  await waitFor(() => view(first).state === (kernel ? "current" : "absent"), "dirty ownership retains canonical evidence");
  assert.equal(view(first).metrics.provedCount, 1);
  await ownershipDocument.save();

  const source = path.join(first, "Kernel_Fixture.thy");
  const document = await vscode.workspace.openTextDocument(source);
  const editor = await vscode.window.showTextDocument(document);
  await editor.edit((builder) => builder.insert(new vscode.Position(0, 0), "(* editor source change *)\n"));
  await waitFor(() => view(first).state === "pending", "immediate unsaved invalidation");
  assert.equal(view(first).metrics.provedCount, 0);
  assert.deepEqual(view(first).readyTaskIds, []);
  const cleanDiagnostics = vscode.languages.getDiagnostics(vscode.Uri.file(path.join(first, "chapters/main.md")));
  assert.ok(cleanDiagnostics.some((diagnostic) => diagnostic.message.includes("formal=stale")), "pending proof also updates real editor diagnostics");
  assert.equal(view(second).state, "absent", "unrelated root stays available");
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  assert.match(view(first).reason, /Unsaved/);
  await document.save();
  await waitFor(() => view(first).state === (kernel ? "source_changed" : "absent"), "saved source revalidation");
  if (kernel) {
    const changed = await snapshot(first); const changedMcp = await mcpSnapshot(first);
    assert.equal(changed.evidence.state, "source_changed");
    assert.equal(changedMcp.evidence.state, changed.evidence.state);
    assert.equal(view(first).metrics.provedCount, 0);
    assert.deepEqual(view(first).readyTaskIds, changed.ready_task_ids);
    assert.equal(view(first).reason, changed.evidence.reason);
    await exec("isabelle-blueprint", ["check", first, "--jobs", "1"], { timeout: 360000 });
    await vscode.commands.executeCommand("isabelleBlueprint.refresh");
    await waitFor(() => view(first).state === "current", "fresh kernel check");
    const fresh = await snapshot(first); const freshMcp = await mcpSnapshot(first);
    assert.deepEqual(fresh.metrics, freshMcp.metrics);
    assert.equal(view(first).metrics.provedCount, fresh.metrics.proved_count);
    assert.deepEqual(view(first).readyTaskIds, fresh.ready_task_ids);
    assert.equal(view(first).project.nodes.find((n: any) => n.id === "admitted").status.formal, "tainted");
  }

  const detail = path.join(first, "chapters/details.md");
  const text = await fs.readFile(detail, "utf8");
  await fs.unlink(detail);
  await waitFor(() => ["historical", "unavailable"].includes(view(first).state), "deleted configured source");
  assert.equal(view(first).metrics.provedCount, 0);
  await fs.writeFile(detail, text);
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  const config = vscode.workspace.getConfiguration("isabelleBlueprint", vscode.Uri.file(first));
  await config.update("cliPath", "missing-blueprint-cli", vscode.ConfigurationTarget.WorkspaceFolder);
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  await waitFor(() => view(first).state === "historical", "unavailable CLI historical fallback");
  assert.equal(view(first).state, "historical", "unavailable/old CLI never makes raw reports current");
  assert.equal(view(first).metrics.provedCount, 0);
  assert.deepEqual(view(first).readyTaskIds, []);
  assert.equal(view(second).state, "absent", "folder-specific CLI settings leave other roots canonical");
  assert.deepEqual(view(second).readyTaskIds, ["other"]);
  const report = path.join(first, "build/project.json");
  const savedReport = await fs.readFile(report, "utf8");
  await fs.writeFile(report, "{malformed");
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  await waitFor(() => view(first).state === "unavailable", "malformed report failure after watcher refresh");
  assert.equal(view(first).state, "unavailable", "malformed historical report cannot restore proof claims");
  assert.equal(view(first).metrics.provedCount, 0);
  assert.match(view(first).reason, /JSON|malformed|property/i);
  await fs.writeFile(report, savedReport);
  await config.update("cliPath", undefined, vscode.ConfigurationTarget.WorkspaceFolder);
  await vscode.commands.executeCommand("isabelleBlueprint.refresh");
  await waitFor(() => view(first).state === (kernel ? "current" : "absent"), "restored CLI evidence");
  assert.equal(view(first).state, kernel ? "current" : "absent");
  console.log(`Real extension-host lifecycle passed (kernel=${kernel}).`);
}
