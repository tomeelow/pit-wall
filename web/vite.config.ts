/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // Relative base so the same build works at a GitHub Pages project path and locally.
  base: "./",
  plugins: [react()],
  test: { environment: "node" },
});
