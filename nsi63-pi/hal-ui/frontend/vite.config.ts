import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

const ROOT_DIR = import.meta.dirname;
const UI_DIR = resolve(ROOT_DIR, "../ui");

const PROD_INDEX_HTML = `<!doctype html>
<html lang="no" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NSI63 — sikringsanlegg</title>
  <link rel="stylesheet" href="/ui/app.css">
</head>
<body>
  <div id="app"></div>
  <script src="/ui/signalfarger.js"></script>
  <script defer src="/ui/app.js"></script>
</body>
</html>
`;

function writeProdIndex() {
  return {
    name: "nsi63-write-prod-index",
    closeBundle() {
      writeFileSync(resolve(UI_DIR, "index.html"), PROD_INDEX_HTML, "utf8");
    },
  };
}

export default defineConfig({
  plugins: [tailwindcss(), svelte(), writeProdIndex()],
  resolve: {
    alias: {
      $lib: resolve(ROOT_DIR, "src/lib"),
      $components: resolve(ROOT_DIR, "src/components"),
      $views: resolve(ROOT_DIR, "src/views"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/panel": "http://127.0.0.1:8080",
      "/ota": "http://127.0.0.1:8080",
      "/ui/signalfarger.js": "http://127.0.0.1:8080",
      "/ui/hammerlakk.png": "http://127.0.0.1:8080",
    },
  },
  build: {
    outDir: UI_DIR,
    emptyOutDir: false,
    cssCodeSplit: false,
    sourcemap: false,
    target: "es2020",
    rollupOptions: {
      input: resolve(ROOT_DIR, "src/main.ts"),
      output: {
        format: "iife",
        name: "NSI63UI",
        entryFileNames: "app.js",
        assetFileNames: (assetInfo) => {
          const names = assetInfo.names ?? (assetInfo.name ? [assetInfo.name] : []);
          if (names.some((n) => n.endsWith(".css"))) return "app.css";
          return "[name][extname]";
        },
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
