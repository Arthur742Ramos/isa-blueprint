/** Isolated real extension host; kernel lifecycle is explicitly opt-in. */
import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { execFileSync } from "child_process";
import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, "../..");
  const repo = path.dirname(extensionDevelopmentPath);
  const fixture = await fs.mkdtemp(path.join(os.tmpdir(), "isa-blueprint-editor-host-"));
  const first = path.join(fixture, "first"); const second = path.join(fixture, "second");
  const kernel = process.env.ISABELLE_BLUEPRINT_EDITOR_KERNEL_TESTS === "1";
  try {
    await fs.mkdir(path.join(first, "chapters"), { recursive: true });
    await fs.mkdir(second);
    if (kernel) await fs.cp(path.join(repo, "tests/fixtures/kernel"), first, { recursive: true });
    else await fs.writeFile(path.join(first, "Kernel_Fixture.thy"), "theory Kernel_Fixture imports Main begin end\n");
    await fs.writeFile(path.join(first, "isabelle-blueprint.toml"),
      '[project]\nname="Editor fixture"\nblueprints=["chapters/main.md","chapters/details.md"]\n[isabelle]\nsession="Blueprint_Kernel_Fixture"\ntimeout=300\n');
    await fs.writeFile(path.join(first, "chapters/main.md"),
      "::: lemma {#clean}\ntitle: Clean proof\nisabelle: Kernel_Fixture.clean\nstatus:\n  formal: proved\n\nClean.\n:::\n");
    await fs.writeFile(path.join(first, "chapters/details.md"),
      "::: lemma {#admitted}\ntitle: Admitted proof\nisabelle: Kernel_Fixture.admitted\nuses: [clean]\nstatus:\n  formal: named\n\nAdmitted.\n:::\n");
    await fs.writeFile(path.join(second, "isabelle-blueprint.toml"), '[project]\nname="Secondary"\n');
    await fs.writeFile(path.join(second, "blueprint.md"), "::: lemma {#other}\nisabelle: Demo.other\nstatus:\n  formal: named\n\nOther.\n:::\n");
    execFileSync("isabelle-blueprint", ["report", first], { timeout: 60000, windowsHide: true });
    if (kernel) execFileSync("isabelle-blueprint", ["check", first, "--jobs", "1"], { timeout: 360000, windowsHide: true });
    const workspace = path.join(fixture, "fixture.code-workspace");
    await fs.writeFile(workspace, JSON.stringify({ folders: [{ path: first }, { path: second }] }));
    await runTests({
      version: "1.90.2", cachePath: path.join(os.tmpdir(), "isa-blueprint-vscode-host-cache"),
      extensionDevelopmentPath, extensionTestsPath: path.join(__dirname, "host/suite.js"),
      launchArgs: [workspace, "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes", "--disable-gpu", "--no-sandbox"],
      extensionTestsEnv: { ISABELLE_BLUEPRINT_HOST_FIRST: first, ISABELLE_BLUEPRINT_HOST_SECOND: second,
        ISABELLE_BLUEPRINT_EDITOR_KERNEL_TESTS: kernel ? "1" : "0" },
    });
  } finally {
    // Only remove the explicitly created fixture beneath the temporary root.
    if (path.dirname(fixture) !== os.tmpdir() || !path.basename(fixture).startsWith("isa-blueprint-editor-host-")) throw new Error("Unsafe fixture cleanup path");
    await fs.rm(fixture, { recursive: true, force: true });
  }
}
void main().catch((error) => { console.error(error); process.exitCode = 1; });
