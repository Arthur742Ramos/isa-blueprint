import { execFile } from "child_process";
import * as fs from "fs/promises";
import * as path from "path";
import * as vscode from "vscode";

interface ProjectSource {
  file?: string | null;
  line?: number | null;
}

interface NodeStatus {
  blueprint: string;
  formal: string;
  agent: string;
  check_error?: string | null;
}

interface IsabelleRef {
  fact?: string | null;
  theory?: string | null;
  session?: string | null;
}

interface BlueprintNode {
  id: string;
  kind: string;
  title: string;
  uses: string[];
  isabelle: IsabelleRef;
  status: NodeStatus;
  source?: ProjectSource;
}

interface BlueprintProject {
  name: string;
  nodes: BlueprintNode[];
}

interface LoadedProject {
  folder: vscode.WorkspaceFolder;
  jsonPath: string;
  project: BlueprintProject;
}

interface NextTaskPayload {
  task?: { id?: string; title?: string } | null;
  prompt?: string | null;
  message?: string | null;
}

class BlueprintTreeProvider implements vscode.TreeDataProvider<TreeItem> {
  private readonly changeEmitter = new vscode.EventEmitter<TreeItem | undefined | null | void>();
  readonly onDidChangeTreeData = this.changeEmitter.event;

  private projects: LoadedProject[] = [];

  setProjects(projects: LoadedProject[]): void {
    this.projects = projects;
    this.changeEmitter.fire();
  }

  getTreeItem(element: TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeItem): TreeItem[] {
    if (element instanceof ProjectItem) {
      return element.loaded.project.nodes.map((node) => new NodeItem(element.loaded, node));
    }
    if (element instanceof NodeItem) {
      return element.dependencies();
    }
    return this.projects.map((loaded) => new ProjectItem(loaded));
  }

  /** Every node known across all loaded projects, for editor completion. */
  allNodes(): BlueprintNode[] {
    return this.projects.flatMap((loaded) => loaded.project.nodes);
  }

  loadedProjects(): LoadedProject[] {
    return this.projects;
  }

  findNode(id: string): { loaded: LoadedProject; node: BlueprintNode } | undefined {
    for (const loaded of this.projects) {
      const node = loaded.project.nodes.find((candidate) => candidate.id === id);
      if (node) {
        return { loaded, node };
      }
    }
    return undefined;
  }
}

type TreeItem = ProjectItem | NodeItem | DependencyItem;

class ProjectItem extends vscode.TreeItem {
  constructor(readonly loaded: LoadedProject) {
    super(loaded.project.name, vscode.TreeItemCollapsibleState.Expanded);
    this.description = path.relative(loaded.folder.uri.fsPath, loaded.jsonPath) || loaded.jsonPath;
    this.iconPath = new vscode.ThemeIcon("symbol-namespace");
    this.contextValue = "isabelleBlueprintProject";
  }
}

class NodeItem extends vscode.TreeItem {
  constructor(
    readonly loaded: LoadedProject,
    readonly node: BlueprintNode,
  ) {
    super(`${node.id}: ${node.title}`, vscode.TreeItemCollapsibleState.Collapsed);
    this.description = `${node.kind} | ${node.status.formal} | ${node.status.agent}`;
    this.tooltip = tooltipForNode(node);
    this.iconPath = new vscode.ThemeIcon(iconForStatus(node.status.formal));
    this.contextValue = "isabelleBlueprintNode";
    this.command = {
      command: "isabelleBlueprint.openNode",
      title: "Open Node",
      arguments: [loaded, node],
    };
  }

  dependencies(): DependencyItem[] {
    if (!this.node.uses || this.node.uses.length === 0) {
      return [];
    }
    const byId = new Map(this.loaded.project.nodes.map((node) => [node.id, node]));
    return this.node.uses.map((id) => new DependencyItem(this.loaded, id, byId.get(id)));
  }
}

class DependencyItem extends vscode.TreeItem {
  constructor(loaded: LoadedProject, id: string, node: BlueprintNode | undefined) {
    super(node ? `${id}: ${node.title}` : id, vscode.TreeItemCollapsibleState.None);
    this.description = node ? `${node.status.formal} dependency` : "missing dependency";
    this.iconPath = new vscode.ThemeIcon(node ? iconForStatus(node.status.formal) : "error");
    this.contextValue = "isabelleBlueprintDependency";
    if (node) {
      this.command = {
        command: "isabelleBlueprint.openNode",
        title: "Open Dependency",
        arguments: [loaded, node],
      };
    }
  }
}

/**
 * Suggests known node ids after Markdown `uses:`/LaTeX `\uses{...}` and known
 * Isabelle facts after Markdown `isabelle:`/LaTeX `\isabelle{...}`. Ids and
 * facts are drawn from the most recently loaded project JSON, so completion
 * improves after a `build`/`check` regenerates it.
 */
class BlueprintCompletionProvider implements vscode.CompletionItemProvider {
  constructor(private readonly provider: BlueprintTreeProvider) {}

  provideCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): vscode.CompletionItem[] {
    const line = document.lineAt(position.line).text.slice(0, position.character);
    const nodes = this.provider.allNodes();
    if (nodes.length === 0) {
      return [];
    }

    if (this.isUsesContext(document, position, line)) {
      return nodes.map((node) => {
        const item = new vscode.CompletionItem(node.id, vscode.CompletionItemKind.Reference);
        item.detail = `${node.kind} — ${node.title}`;
        item.documentation = new vscode.MarkdownString(tooltipForNode(node));
        return item;
      });
    }

    if (this.isIsabelleContext(document, line)) {
      return nodes
        .filter((node) => node.isabelle && node.isabelle.fact)
        .map((node) => {
          const fact = node.isabelle.fact as string;
          const item = new vscode.CompletionItem(fact, vscode.CompletionItemKind.Value);
          item.detail = `fact of ${node.id}`;
          return item;
        });
    }

    return [];
  }

  /**
   * Node-id completion fires either directly after a `uses:` line, or on a
   * bare list item (`- `) that belongs to a `uses:` block. A bare `- ` on its
   * own matches any empty list item (e.g. under a `Notes:` block), so we scan
   * upward to confirm the enclosing block key is actually `uses:`.
   */
  private isUsesContext(
    document: vscode.TextDocument,
    position: vscode.Position,
    line: string,
  ): boolean {
    if (isLatexDocument(document)) {
      return /\\uses\{[^}]*$/.test(line);
    }
    if (/^\s*uses:\s*$/.test(line)) {
      return true;
    }
    if (!/^\s*-\s*\S*$/.test(line)) {
      return false;
    }
    for (let ln = position.line - 1; ln >= 0; ln--) {
      const text = document.lineAt(ln).text;
      if (/^\s*$/.test(text)) {
        continue;
      }
      if (/^\s*-\s*/.test(text)) {
        // Another list item in the same block; keep scanning upward.
        continue;
      }
      if (/^\s*uses:\s*$/.test(text)) {
        return true;
      }
      // A heading, container fence, a different block key, or a dedented
      // non-list line ends the block without finding `uses:`.
      return false;
    }
    return false;
  }

  private isIsabelleContext(document: vscode.TextDocument, line: string): boolean {
    if (isLatexDocument(document)) {
      return /\\isabelle\{[^}]*$/.test(line);
    }
    return /^\s*isabelle:\s*\S*$/.test(line);
  }
}

class BlueprintDefinitionProvider implements vscode.DefinitionProvider {
  constructor(private readonly provider: BlueprintTreeProvider) {}

  provideDefinition(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): vscode.Definition | undefined {
    const range = document.getWordRangeAtPosition(position, /[\w.\-/:]+/);
    if (!range) {
      return undefined;
    }
    const word = document.getText(range);
    const found = this.provider.findNode(word);
    if (!found) {
      return undefined;
    }
    return locationForNode(found.loaded, found.node);
  }
}

class BlueprintCodeActionProvider implements vscode.CodeActionProvider {
  constructor(private readonly provider: BlueprintTreeProvider) {}

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    for (const diagnostic of context.diagnostics) {
      const code = typeof diagnostic.code === "string" ? diagnostic.code : "";
      if (!code.startsWith("missing-dependency:")) {
        continue;
      }
      const missingId = code.slice("missing-dependency:".length);
      const action = new vscode.CodeAction(
        `Create missing blueprint node '${missingId}'`,
        vscode.CodeActionKind.QuickFix,
      );
      action.diagnostics = [diagnostic];
      action.command = {
        command: "isabelleBlueprint.createMissingDependency",
        title: "Create Missing Blueprint Node",
        arguments: [document.uri, missingId, this.provider.loadedProjects()],
      };
      actions.push(action);
    }
    return actions;
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const diagnostics = vscode.languages.createDiagnosticCollection("isabelle-blueprint");
  const provider = new BlueprintTreeProvider();
  const output = vscode.window.createOutputChannel("IsabelleBlueprint");
  const running = new Set<string>();
  const blueprintDocuments: vscode.DocumentSelector = [
    { language: "markdown", scheme: "file" },
    { language: "latex", scheme: "file" },
  ];

  context.subscriptions.push(diagnostics);
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.window.registerTreeDataProvider("isabelleBlueprint.nodes", provider));
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.refresh", async () => {
      await refresh(provider, diagnostics);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.openNode", async (loaded: LoadedProject, node: BlueprintNode) => {
      await openNode(loaded, node);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.runReport", async () => {
      await runBlueprintCommand("report", provider, diagnostics, output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.runCheck", async () => {
      await runBlueprintCommand("check", provider, diagnostics, output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.runTasks", async () => {
      await runBlueprintCommand("tasks", provider, diagnostics, output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.runRoadmap", async () => {
      await runBlueprintCommand("roadmap", provider, diagnostics, output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.runAgentContext", async () => {
      await runBlueprintCommand("agent-context", provider, diagnostics, output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("isabelleBlueprint.openNextTaskPrompt", async () => {
      await openNextTaskPrompt(output, running);
    }),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "isabelleBlueprint.previewTaskPrompt",
      async (loaded?: LoadedProject, node?: BlueprintNode) => {
        await previewTaskPrompt(loaded, node, provider);
      },
    ),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "isabelleBlueprint.createMissingDependency",
      async (uri: vscode.Uri, missingId: string, projects: LoadedProject[]) => {
        await createMissingDependency(uri, missingId, projects);
        await refresh(provider, diagnostics);
      },
    ),
  );

  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      blueprintDocuments,
      new BlueprintCompletionProvider(provider),
      ":",
      " ",
      "-",
      "{",
      ",",
    ),
  );
  context.subscriptions.push(
    vscode.languages.registerDefinitionProvider(
      blueprintDocuments,
      new BlueprintDefinitionProvider(provider),
    ),
  );
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      blueprintDocuments,
      new BlueprintCodeActionProvider(provider),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] },
    ),
  );

  const watcher = vscode.workspace.createFileSystemWatcher("**/project.json");
  context.subscriptions.push(watcher);
  context.subscriptions.push(watcher.onDidChange(async () => refresh(provider, diagnostics)));
  context.subscriptions.push(watcher.onDidCreate(async () => refresh(provider, diagnostics)));
  context.subscriptions.push(watcher.onDidDelete(async () => refresh(provider, diagnostics)));
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(async () => refresh(provider, diagnostics)));

  void refresh(provider, diagnostics);
}

export function deactivate(): void {
  return;
}

async function refresh(
  provider: BlueprintTreeProvider,
  diagnostics: vscode.DiagnosticCollection,
): Promise<void> {
  const projects: LoadedProject[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const configuredPath = vscode.workspace
      .getConfiguration("isabelleBlueprint", folder.uri)
      .get<string>("projectJson", "build/project.json");
    const jsonPath = path.resolve(folder.uri.fsPath, configuredPath);
    const project = await readProject(jsonPath);
    if (project) {
      projects.push({ folder, jsonPath, project });
    }
  }
  provider.setProjects(projects);
  diagnostics.clear();
  for (const loaded of projects) {
    applyDiagnostics(loaded, diagnostics);
  }
}

async function runBlueprintCommand(
  command: "report" | "check" | "tasks" | "roadmap" | "agent-context",
  provider: BlueprintTreeProvider,
  diagnostics: vscode.DiagnosticCollection,
  output: vscode.OutputChannel,
  running: Set<string>,
): Promise<void> {
  const folder = await pickWorkspaceFolder();
  if (!folder) {
    return;
  }
  const key = `${folder.uri.fsPath}:${command}`;
  if (running.has(key)) {
    void vscode.window.showInformationMessage(`IsabelleBlueprint ${command} is already running.`);
    return;
  }
  running.add(key);
  const cliPath = vscode.workspace
    .getConfiguration("isabelleBlueprint", folder.uri)
    .get<string>("cliPath", "isabelle-blueprint");
  output.show(true);
  output.appendLine(`> ${cliPath} ${command} ${folder.uri.fsPath}`);
  try {
    const { stdout, stderr } = await execFilePromise(cliPath, [command, folder.uri.fsPath], folder.uri.fsPath);
    if (stdout.trim()) {
      output.appendLine(stdout.trimEnd());
    }
    if (stderr.trim()) {
      output.appendLine(stderr.trimEnd());
    }
    await refresh(provider, diagnostics);
    void vscode.window.showInformationMessage(`IsabelleBlueprint ${command} completed.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(message);
    void vscode.window.showErrorMessage(`IsabelleBlueprint ${command} failed. See output for details.`);
  } finally {
    running.delete(key);
  }
}

async function openNextTaskPrompt(
  output: vscode.OutputChannel,
  running: Set<string>,
): Promise<void> {
  const folder = await pickWorkspaceFolder();
  if (!folder) {
    return;
  }
  const command = "next";
  const key = `${folder.uri.fsPath}:${command}`;
  if (running.has(key)) {
    void vscode.window.showInformationMessage("IsabelleBlueprint next task is already running.");
    return;
  }
  running.add(key);
  const cliPath = vscode.workspace
    .getConfiguration("isabelleBlueprint", folder.uri)
    .get<string>("cliPath", "isabelle-blueprint");
  output.show(true);
  output.appendLine(`> ${cliPath} next ${folder.uri.fsPath} --json`);
  try {
    const { stdout, stderr } = await execFilePromise(
      cliPath,
      ["next", folder.uri.fsPath, "--json"],
      folder.uri.fsPath,
    );
    if (stderr.trim()) {
      output.appendLine(stderr.trimEnd());
    }
    const payload = JSON.parse(stdout) as NextTaskPayload;
    if (!payload.prompt) {
      void vscode.window.showInformationMessage(payload.message ?? "No ready IsabelleBlueprint tasks are available.");
      return;
    }
    const document = await vscode.workspace.openTextDocument({
      content: payload.prompt,
      language: "markdown",
    });
    await vscode.window.showTextDocument(document, { preview: true });
    void vscode.commands.executeCommand("markdown.showPreview", document.uri);
    const suffix = payload.task?.id ? ` (${payload.task.id})` : "";
    void vscode.window.showInformationMessage(`IsabelleBlueprint next task prompt opened${suffix}.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(message);
    void vscode.window.showErrorMessage("IsabelleBlueprint next task failed. See output for details.");
  } finally {
    running.delete(key);
  }
}

async function pickWorkspaceFolder(): Promise<vscode.WorkspaceFolder | undefined> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length === 0) {
    void vscode.window.showWarningMessage("Open a workspace folder before running IsabelleBlueprint.");
    return undefined;
  }
  if (folders.length === 1) {
    return folders[0];
  }
  return vscode.window.showWorkspaceFolderPick();
}

function execFilePromise(
  command: string,
  args: string[],
  cwd: string,
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    execFile(command, args, { cwd, windowsHide: true, maxBuffer: 1024 * 1024 * 8 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`${error.message}\n${stdout}${stderr}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function readProject(jsonPath: string): Promise<BlueprintProject | undefined> {
  try {
    const raw = await fs.readFile(jsonPath, "utf8");
    const parsed = JSON.parse(raw) as BlueprintProject;
    return {
      name: parsed.name || "IsabelleBlueprint",
      nodes: Array.isArray(parsed.nodes) ? parsed.nodes : [],
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      void vscode.window.showWarningMessage(`Could not read IsabelleBlueprint project JSON: ${String(error)}`);
    }
    return undefined;
  }
}

function applyDiagnostics(loaded: LoadedProject, diagnostics: vscode.DiagnosticCollection): void {
  const byFile = new Map<string, vscode.Diagnostic[]>();
  const byId = new Map(loaded.project.nodes.map((node) => [node.id, node]));
  for (const node of loaded.project.nodes) {
    const sourceFile = node.source?.file;
    if (!sourceFile) {
      continue;
    }
    const absPath = path.isAbsolute(sourceFile) ? sourceFile : path.resolve(loaded.folder.uri.fsPath, sourceFile);
    const line = Math.max(0, (node.source?.line ?? 1) - 1);
    const range = new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);
    const existing = byFile.get(absPath) ?? [];
    const severity = severityForStatus(node.status.formal);
    if (severity !== undefined) {
      const message = `${node.id}: formal=${node.status.formal}, agent=${node.status.agent}${
        node.status.check_error ? ` (${node.status.check_error})` : ""
      }`;
      const diagnostic = new vscode.Diagnostic(range, message, severity);
      diagnostic.source = "IsabelleBlueprint";
      diagnostic.code = node.id;
      existing.push(diagnostic);
    }

    for (const depId of node.uses ?? []) {
      if (byId.has(depId)) {
        continue;
      }
      const depDiagnostic = new vscode.Diagnostic(
        range,
        `${node.id}: missing dependency '${depId}'`,
        vscode.DiagnosticSeverity.Error,
      );
      depDiagnostic.source = "IsabelleBlueprint";
      depDiagnostic.code = `missing-dependency:${depId}`;
      existing.push(depDiagnostic);
    }
    byFile.set(absPath, existing);
  }
  for (const [file, fileDiagnostics] of byFile) {
    diagnostics.set(vscode.Uri.file(file), fileDiagnostics);
  }
}

async function openNode(loaded: LoadedProject, node: BlueprintNode): Promise<void> {
  const location = locationForNode(loaded, node);
  if (!location) {
    return;
  }
  try {
    const document = await vscode.workspace.openTextDocument(location.uri);
    const editor = await vscode.window.showTextDocument(document);
    editor.selection = new vscode.Selection(location.range.start, location.range.start);
    editor.revealRange(location.range, vscode.TextEditorRevealType.InCenter);
  } catch (error) {
    void vscode.window.showWarningMessage(`Could not open IsabelleBlueprint source ${location.uri.fsPath}: ${String(error)}`);
  }
}

async function previewTaskPrompt(
  loaded: LoadedProject | undefined,
  node: BlueprintNode | undefined,
  provider: BlueprintTreeProvider,
): Promise<void> {
  let target = loaded && node ? { loaded, node } : undefined;
  if (!target) {
    const items = provider.allNodes().map((candidate) => ({
      label: candidate.title,
      description: candidate.id,
      node: candidate,
    }));
    const picked = await vscode.window.showQuickPick(items, { placeHolder: "Pick a blueprint node" });
    if (!picked) {
      return;
    }
    const found = provider.findNode(picked.node.id);
    if (!found) {
      void vscode.window.showWarningMessage(`Could not find node '${picked.node.id}'.`);
      return;
    }
    target = found;
  }
  const promptPath = path.join(path.dirname(target.loaded.jsonPath), "prompts", `task-${target.node.id}.md`);
  try {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(promptPath));
    await vscode.window.showTextDocument(document, { preview: true });
  } catch {
    void vscode.window.showWarningMessage(
      `No prompt found for '${target.node.id}'. Run "IsabelleBlueprint: Generate Tasks" first.`,
    );
  }
}

function locationForNode(loaded: LoadedProject, node: BlueprintNode): vscode.Location | undefined {
  const sourceFile = node.source?.file;
  if (!sourceFile) {
    return undefined;
  }
  const absPath = path.isAbsolute(sourceFile) ? sourceFile : path.resolve(loaded.folder.uri.fsPath, sourceFile);
  const line = Math.max(0, (node.source?.line ?? 1) - 1);
  const position = new vscode.Position(line, 0);
  return new vscode.Location(vscode.Uri.file(absPath), new vscode.Range(position, position));
}

async function createMissingDependency(
  uri: vscode.Uri,
  missingId: string,
  projects: LoadedProject[],
): Promise<void> {
  if (projects.some((loaded) => loaded.project.nodes.some((node) => node.id === missingId))) {
    void vscode.window.showInformationMessage(`Blueprint node '${missingId}' already exists.`);
    return;
  }
  const document = await vscode.workspace.openTextDocument(uri);
  const edit = new vscode.WorkspaceEdit();
  const latex = isLatexDocument(document);
  const insertAt = latex ? latexInsertPosition(document) : endOfDocument(document);
  const prefix = latex ? "\n" : document.getText().endsWith("\n") ? "\n" : "\n\n";
  const stub = latex ? renderLatexNodeStub(missingId, prefix) : renderNodeStub(missingId, prefix);
  edit.insert(document.uri, insertAt, stub);
  const applied = await vscode.workspace.applyEdit(edit);
  if (!applied) {
    void vscode.window.showWarningMessage(`Could not insert missing blueprint node '${missingId}'.`);
    return;
  }
  await document.save();
}

function endOfDocument(document: vscode.TextDocument): vscode.Position {
  const lastLine = document.lineAt(document.lineCount - 1);
  return new vscode.Position(document.lineCount - 1, lastLine.text.length);
}

function latexInsertPosition(document: vscode.TextDocument): vscode.Position {
  for (let line = document.lineCount - 1; line >= 0; line--) {
    if (/\\end\{document\}/.test(document.lineAt(line).text)) {
      return new vscode.Position(line, 0);
    }
  }
  return endOfDocument(document);
}

function renderNodeStub(nodeId: string, prefix: string): string {
  const title = humanizeId(nodeId);
  const fact = suggestFact(nodeId);
  return `${prefix}::: lemma {#${nodeId}}
title: ${title}
isabelle: ${fact}
status: stub

<!-- TODO: state the lemma here. -->

## Proof

<!-- TODO: sketch the proof. -->
:::
`;
}

function renderLatexNodeStub(nodeId: string, prefix: string): string {
  const title = humanizeId(nodeId);
  const fact = suggestFact(nodeId);
  return `${prefix}\\begin{lemma}[${title}]
\\label{${nodeId}}
\\isabelle{${fact}}
\\status{stub}

% TODO: state the lemma here.

\\begin{proof}
% TODO: sketch the proof.
\\end{proof}
\\end{lemma}
`;
}

function isLatexDocument(document: vscode.TextDocument): boolean {
  return document.languageId === "latex" || document.uri.fsPath.toLowerCase().endsWith(".tex");
}

function humanizeId(nodeId: string): string {
  const tail = nodeId.split(":").pop()?.replace(/[-_]+/g, " ").trim() || nodeId;
  return tail.charAt(0).toUpperCase() + tail.slice(1);
}

function suggestFact(nodeId: string): string {
  const tail = nodeId.split(":").pop() || nodeId;
  return tail.replace(/[^0-9A-Za-z_]+/g, "_").replace(/^_+|_+$/g, "") || nodeId;
}

function severityForStatus(status: string): vscode.DiagnosticSeverity | undefined {
  switch (status) {
    case "proved":
    case "found":
      return undefined;
    case "tainted":
    case "stale":
    case "named":
      return vscode.DiagnosticSeverity.Warning;
    case "missing":
      return vscode.DiagnosticSeverity.Information;
    case "not_found":
    case "broken":
    case "failed_check":
      return vscode.DiagnosticSeverity.Error;
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

function iconForStatus(status: string): string {
  switch (status) {
    case "proved":
      return "verified-filled";
    case "found":
      return "pass-filled";
    case "tainted":
    case "stale":
      return "warning";
    case "not_found":
    case "broken":
    case "failed_check":
      return "error";
    case "named":
      return "symbol-key";
    default:
      return "circle-outline";
  }
}

function tooltipForNode(node: BlueprintNode): string {
  const fact = node.isabelle?.fact ? `\nFact: ${node.isabelle.fact}` : "";
  const deps = node.uses?.length ? `\nUses: ${node.uses.join(", ")}` : "";
  const error = node.status.check_error ? `\nCheck: ${node.status.check_error}` : "";
  return `${node.kind} ${node.id}\nBlueprint: ${node.status.blueprint}\nFormal: ${node.status.formal}\nAgent: ${node.status.agent}${fact}${deps}${error}`;
}
