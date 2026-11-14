// Construye el explorador: empaqueta site-src/explorador.js con esbuild y
// copia el motor DuckDB-WASM a site/vendor/. Todo se sirve desde el propio
// sitio (sin CDN), con versiones fijadas en package-lock.json.
import { build } from "esbuild";
import { copyFile, mkdir, readFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const DIST = "node_modules/@duckdb/duckdb-wasm/dist";
const OUT = "site/vendor";

await mkdir(`${OUT}/duckdb`, { recursive: true });

await build({
  entryPoints: ["site-src/explorador.js"],
  bundle: true,
  format: "esm",
  target: "es2020",
  minify: true,
  legalComments: "linked",
  outfile: `${OUT}/explorador.js`,
  logLevel: "info",
});

for (const f of ["duckdb-eh.wasm", "duckdb-browser-eh.worker.js"]) {
  await copyFile(`${DIST}/${f}`, `${OUT}/duckdb/${f}`);
}

// Registro de lo que se publicó (para auditar qué binarios están en el sitio)
const hash = async (p) => createHash("sha256").update(await readFile(p)).digest("hex");
const pkg = JSON.parse(await readFile("node_modules/@duckdb/duckdb-wasm/package.json", "utf8"));
console.log(`duckdb-wasm ${pkg.version}`);
for (const p of [`${OUT}/explorador.js`, `${OUT}/duckdb/duckdb-eh.wasm`, `${OUT}/duckdb/duckdb-browser-eh.worker.js`]) {
  console.log(`sha256 ${await hash(p)}  ${p}`);
}
