const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const projectRoot = path.resolve(__dirname, "..");
const extensionRoot = path.join(projectRoot, "ai-visit-website-chrome-extension-1.5.0");
const read = (relativePath) => fs.readFileSync(path.join(extensionRoot, relativePath), "utf8");

const manifest = JSON.parse(read("manifest.json"));
assert.equal(manifest.name, "AI Visit website");
assert.equal(manifest.version, "1.5.0");
assert.match(manifest.description, /AI Visit website agents/);
assert.deepEqual(manifest.permissions.sort(), ["alarms", "scripting", "storage", "tabs"]);
assert.equal(manifest.commands, undefined);
assert.equal(manifest.action.default_title, "Open AI Visit website bridge settings");

const requiredFiles = [
  "agent-browser-bridge.js",
  "background.js",
  "reuters-article-extractor.js",
  "settings.css",
  "settings.html",
  "settings.js"
];
requiredFiles.forEach((relativePath) => {
  assert.equal(fs.existsSync(path.join(extensionRoot, relativePath)), true, `${relativePath} is required`);
});

const removedFiles = [
  "clipboard.js",
  "popup.html",
  "popup.js",
  "reuters-validation-core.js",
  "reuters-validation.css",
  "reuters-validation.html",
  "reuters-validation.js",
  "styles.css"
];
removedFiles.forEach((relativePath) => {
  assert.equal(fs.existsSync(path.join(extensionRoot, relativePath)), false, `${relativePath} must stay removed`);
});

const background = read("background.js");
assert.match(background, /importScripts\("reuters-article-extractor\.js", "agent-browser-bridge\.js"\)/);
assert.match(background, /executeAgentBrowserRead/);
assert.match(background, /openOptionsPage/);
[
  "chrome.contextMenus",
  "chrome.commands",
  "saveTabAsMarkdown",
  "capture-page-for-validation",
  "reuters-validation.html"
].forEach((legacyEntry) => assert.doesNotMatch(background, new RegExp(legacyEntry.replace(".", "\\."))));

const listeners = {};
let optionsPageOpenCount = 0;
const event = (name) => ({
  addListener(listener) {
    listeners[name] = listener;
  }
});
vm.runInNewContext(background, {
  URL,
  TextEncoder,
  clearTimeout,
  console,
  crypto: globalThis.crypto,
  setTimeout,
  chrome: {
    action: { onClicked: event("actionClicked") },
    alarms: {
      create() {},
      onAlarm: event("alarm")
    },
    runtime: {
      lastError: null,
      onInstalled: event("installed"),
      onMessage: event("message"),
      onStartup: event("startup"),
      openOptionsPage(callback) {
        optionsPageOpenCount += 1;
        callback();
      }
    },
    tabs: {
      get() {},
      onRemoved: { addListener() {}, removeListener() {} },
      onUpdated: { addListener() {}, removeListener() {} }
    }
  }
});
assert.equal(typeof listeners.actionClicked, "function");
listeners.actionClicked();
assert.equal(optionsPageOpenCount, 1);
assert.equal(listeners.message({ type: "legacy-manual-action" }, null, () => {}), false);

const settingsHtml = read("settings.html");
[
  "agentBridgeEnabled",
  "agentBridgePort",
  "agentBridgeToken",
  "agentBridgeAllowedOrigins",
  "saveAgentBridgeBtn",
  "checkAgentBridgeBtn"
].forEach((id) => assert.match(settingsHtml, new RegExp(`id="${id}"`)));
assert.doesNotMatch(settingsHtml, /Snippet Saver|Tag Manager|Import Snippets|Reuters Browser Validation/);

const bridge = require(path.join(extensionRoot, "agent-browser-bridge.js"));
assert.equal(bridge.buildBridgeEndpoint(32145), "http://127.0.0.1:32145");
assert.equal(bridge.buildBridgeEndpoint(80), "http://127.0.0.1:32145");
assert.deepEqual(
  bridge.normalizeAllowedOrigins(["example.com", "https://EXAMPLE.com/path", "file:///tmp/test"]),
  ["https://example.com"]
);
assert.equal(
  bridge.isOriginAllowed("https://example.com/article", ["https://example.com"]),
  true
);
assert.equal(
  bridge.isOriginAllowed("https://other.example/article", ["https://example.com"]),
  false
);

console.log("Chrome extension agent-first contract passed.");
