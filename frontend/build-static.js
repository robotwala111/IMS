const fs = require("fs");
const path = require("path");

const root = __dirname;
const outputDirs = [
  path.join(root, "dist"),
  path.join(root, "public"),
  path.join(root, "..", "public"),
];
const entries = ["index.html", "css", "js", "assets"];
const apiBaseUrl = process.env.NDT_IMS_API_BASE_URL || "/api/v1";
const configJs = `window.__NDT_IMS_API_BASE_URL__ = ${JSON.stringify(apiBaseUrl)};\n`;

for (const outputDir of outputDirs) {
  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.mkdirSync(outputDir, { recursive: true });

  for (const entry of entries) {
    const source = path.join(root, entry);
    if (!fs.existsSync(source)) {
      continue;
    }

    fs.cpSync(source, path.join(outputDir, entry), { recursive: true });
  }

  const jsDir = path.join(outputDir, "js");
  fs.mkdirSync(jsDir, { recursive: true });
  fs.writeFileSync(path.join(jsDir, "config.js"), configJs);
}
