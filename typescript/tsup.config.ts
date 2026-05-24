import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["attp/core/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  sourcemap: true,
});