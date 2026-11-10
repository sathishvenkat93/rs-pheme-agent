import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard reads /execution_report.json. In dev it is served straight from the report
// folder, so a rebuilt report shows up without restarting; `vite build` copies it into dist/.
const reportDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  process.env.PHEME_REPORT_DIR ?? "../report",
);

// Questions typed into the dashboard go to `pheme-report serve`, which holds the AWS credentials.
const api = { "/api": `http://127.0.0.1:${process.env.PHEME_API_PORT ?? 8787}` };

export default defineConfig({
  plugins: [react()],
  publicDir: reportDir,
  server: { port: 5174, proxy: api },
  preview: { port: 5174, proxy: api },
});
