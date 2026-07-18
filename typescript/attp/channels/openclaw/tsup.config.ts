import { defineConfig } from "tsup";

/**
 * Bundle the openclaw channel plugin into a SELF-CONTAINED dist/index.js.
 *
 * Inlines: ../core/* + ../app/* (relative source) + ws + @modelcontextprotocol/sdk
 *          + zod + @noble/* (so the installed plugin needs no node_modules / npm install).
 * External: openclaw/* (provided by the openclaw host at runtime) + node: builtins.
 *
 * Run from this dir: `npx tsup`  (tsup resolves from the typescript/ root devDeps).
 */
export default defineConfig({
  entry: ["index.ts"],
  format: ["esm"],
  target: "node18",
  platform: "node",
  outDir: "dist",
  bundle: true,
  clean: true,
  sourcemap: false,
  // External: openclaw/* (provided by the openclaw host at runtime; also a peerDep)
  // + node: builtins. Everything else (../core, ../app, ws, @modelcontextprotocol/sdk,
  // zod, @noble/*) is inlined — the plugin package declares no `dependencies`, so tsup
  // does not auto-externalize them. NOTE: do NOT use noExternal: it removes openclaw too.
  external: [/^openclaw($|\/)/, /^node:/],
});
