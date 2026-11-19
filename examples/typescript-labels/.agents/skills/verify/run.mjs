import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual, parseArgs } from "node:util";

const root = new URL("../../../", import.meta.url);
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const report = { state: "ERROR", checks: {} };
let buildDir;

try {
  const { values } = parseArgs({ options: {
    plan: { type: "string" }, catalog: { type: "string" },
    seed: { type: "string", default: "20261117" }, path: { type: "string" },
  } });
  if (!values.plan || !values.catalog) throw new Error("Provide --plan and --catalog from the pinned skill");
  const seed = Number(values.seed);
  if (!Number.isSafeInteger(seed) || seed < -2147483648 || seed > 2147483647) {
    throw new Error("Use a signed 32-bit integer seed");
  }
  const planBytes = await readFile(values.plan);
  const plan = JSON.parse(planBytes);
  if (plan.schema !== "i2e-verification-tools/v1" || plan.state !== "SELECTED" ||
      plan.e2e?.surface !== "web" || plan.e2e?.driver !== "chrome-devtools-mcp" ||
      plan.properties?.language !== "typescript" || plan.properties?.library !== "fast-check" ||
      plan.catalog?.feature !== "labels.normalize") {
    throw new Error("This project verifier requires the web TypeScript labels.normalize selection");
  }
  const catalogBytes = await readFile(values.catalog);
  if (digest(catalogBytes) !== plan.catalog.sha256) throw new Error("Selected catalog digest mismatch");
  const catalog = JSON.parse(catalogBytes);
  const feature = plan.catalog.feature;
  if (catalog.schema === "i2e-verification-catalog/v1") {
    const spec = catalog.features[feature];
    const ids = spec.checks.map(check => check.id);
    const rules = catalog.rules.filter(rule => rule.feature === feature).map(({ id, status }) => ({ id, status }));
    if (plan.catalog.root !== "checkout" || spec.entrypoint !== "normalizeLabels" ||
        plan.catalog.entrypoint !== spec.entrypoint ||
        !isDeepStrictEqual([...ids].sort(), ["labels.form.e2e", "labels.normalize.properties"]) ||
        !isDeepStrictEqual(plan.catalog.checks, ids) || !isDeepStrictEqual(plan.catalog.rules, rules)) {
      throw new Error("Selected checks or rules do not match this project verifier");
    }
  } else if (catalog.schema !== "i2e-label-catalog/v1" || plan.catalog.root !== undefined) {
    throw new Error("Unsupported label catalog and selection");
  }
  report.selection = plan;
  report.planSha256 = digest(planBytes);
  report.lockSha256 = digest(await readFile(new URL("package-lock.json", root)));
  report.node = process.version;
  buildDir = await mkdtemp(join(tmpdir(), "i2e-label-build-"));
  await writeFile(join(buildDir, "package.json"), '{"type":"module"}\n');
  const compiler = fileURLToPath(new URL("node_modules/typescript/bin/tsc", root));
  const build = spawnSync(process.execPath, [compiler, "-p", "tsconfig.json", "--outDir", buildDir], {
    cwd: root, stdio: ["ignore", 2, 2], timeout: 60000,
  });
  if (build.status !== 0) throw new Error("TypeScript build failed: " + (build.error?.message ?? build.status));
  const assets = new Map([
    ["/", { body: await readFile(new URL("index.html", root)), type: "text/html" }],
    ["/dist/app.js", { body: await readFile(join(buildDir, "app.js")), type: "text/javascript" }],
    ["/dist/labels.js", { body: await readFile(join(buildDir, "labels.js")), type: "text/javascript" }],
  ]);
  report.build = Object.fromEntries([...assets].map(([path, asset]) => [path, digest(asset.body)]));

  const { normalizeLabels } = await import(pathToFileURL(join(buildDir, "labels.js")));
  const { checkProperties, checkRules } = await import("./properties.mjs");
  report.checks.properties = checkProperties(normalizeLabels, seed);
  if (values.path !== undefined) report.checks.replay = checkProperties(normalizeLabels, seed, values.path);
  report.checks.rules = checkRules(normalizeLabels, catalog, feature);
  const { checkBrowser } = await import("./browser.mjs");
  report.checks.e2e = await checkBrowser(root, assets);
  const failed = [report.checks.properties, report.checks.replay, report.checks.e2e, ...report.checks.rules]
    .some(check => check?.state === "FAIL");
  report.state = failed ? "FAIL" : "PASS";
} catch (err) {
  report.error = err.message;
} finally {
  if (buildDir) await rm(buildDir, { recursive: true, force: true });
}
console.log(JSON.stringify(report, null, 2));
process.exitCode = { PASS: 0, FAIL: 1, ERROR: 2 }[report.state];
