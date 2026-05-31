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
    return this.node.uses.map((id) => new DependencyItem(id, byId.get(id)));
  }
}

class DependencyItem extends vscode.TreeItem {
  constructor(id: string, node: BlueprintNode | undefined) {
    super(node ? `${id}: ${node.title}` : id, vscode.TreeItemCollapsibleState.None);
    this.description = node ? `${node.status.formal} dependency` : "missing dependency";
    this.iconPath = new vscode.ThemeIcon(node ? iconForStatus(node.status.formal) : "error");
    this.contextValue = "isabelleBlueprintDependency";
  }
}

/**
 * Suggests known node ids after `uses:`/`- ` and known Isabelle facts after
 * `isabelle:` while editing a blueprint Markdown file. Ids and facts are drawn
 * from the most recently loaded project JSON, so completion improves after a
 * `build`/`check` regenerates it.
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

    if (/(^\s*uses:\s*$)|(^\s*-\s*$)/.test(line)) {
      return nodes.map((node) => {
        const item = new vscode.CompletionItem(node.id, vscode.CompletionItemKind.Reference);
        item.detail = `${node.kind} — ${node.title}`;
        item.documentation = new vscode.MarkdownString(tooltipForNode(node));
        return item;
      });
    }

    if (/^\s*isabelle:\s*\S*$/.test(line)) {
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
}

export function activate(context: vscode.ExtensionContext): void {
  const diagnostics = vscode.languages.createDiagnosticCollection("isabelle-blueprint");
  const provider = new BlueprintTreeProvider();

  context.subscriptions.push(diagnostics);
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
    vscode.languages.registerCompletionItemProvider(
      { language: "markdown", scheme: "file" },
      new BlueprintCompletionProvider(provider),
      ":",
      " ",
      "-",
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
  for (const node of loaded.project.nodes) {
    const severity = severityForStatus(node.status.formal);
    if (severity === undefined) {
      continue;
    }
    const sourceFile = node.source?.file;
    if (!sourceFile) {
      continue;
    }
    const absPath = path.isAbsolute(sourceFile) ? sourceFile : path.resolve(loaded.folder.uri.fsPath, sourceFile);
    const line = Math.max(0, (node.source?.line ?? 1) - 1);
    const range = new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);
    const message = `${node.id}: formal=${node.status.formal}, agent=${node.status.agent}${
      node.status.check_error ? ` (${node.status.check_error})` : ""
    }`;
    const diagnostic = new vscode.Diagnostic(range, message, severity);
    diagnostic.source = "IsabelleBlueprint";
    diagnostic.code = node.id;
    const existing = byFile.get(absPath) ?? [];
    existing.push(diagnostic);
    byFile.set(absPath, existing);
  }
  for (const [file, fileDiagnostics] of byFile) {
    diagnostics.set(vscode.Uri.file(file), fileDiagnostics);
  }
}

async function openNode(loaded: LoadedProject, node: BlueprintNode): Promise<void> {
  const sourceFile = node.source?.file;
  if (!sourceFile) {
    return;
  }
  const absPath = path.isAbsolute(sourceFile) ? sourceFile : path.resolve(loaded.folder.uri.fsPath, sourceFile);
  try {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(absPath));
    const editor = await vscode.window.showTextDocument(document);
    const line = Math.max(0, (node.source?.line ?? 1) - 1);
    const position = new vscode.Position(line, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  } catch (error) {
    void vscode.window.showWarningMessage(`Could not open IsabelleBlueprint source ${absPath}: ${String(error)}`);
  }
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
