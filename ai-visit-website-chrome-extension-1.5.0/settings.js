document.addEventListener("DOMContentLoaded", () => {
  const openShortcutBtn = document.getElementById("openShortcutBtn");
  const exportBtn = document.getElementById("exportBtn");
  const importBtn = document.getElementById("importBtn");
  const importFileInput = document.getElementById("importFileInput");
  const openChangelogBtn = document.getElementById("openChangelogBtn");
  const openReutersBtn = document.getElementById("openReutersBtn");
  const openReutersValidationBtn = document.getElementById("openReutersValidationBtn");
  const agentBridgeEnabled = document.getElementById("agentBridgeEnabled");
  const agentBridgePort = document.getElementById("agentBridgePort");
  const agentBridgeToken = document.getElementById("agentBridgeToken");
  const agentBridgeAllowedOrigins = document.getElementById("agentBridgeAllowedOrigins");
  const saveAgentBridgeBtn = document.getElementById("saveAgentBridgeBtn");
  const checkAgentBridgeBtn = document.getElementById("checkAgentBridgeBtn");
  const agentBridgeStatus = document.getElementById("agentBridgeStatus");

  // Tag Manager elements
  const newTagInput = document.getElementById("newTagInput");
  const addTagBtn = document.getElementById("addTagBtn");
  const tagListEl = document.getElementById("tagList");

  let tags = [];
  let snippets = [];

  // ------------------------------------------------------------
  // Open Chrome Shortcut Settings
  // ------------------------------------------------------------
  openShortcutBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
  });

  openReutersBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: "https://www.reuters.com/business/" });
  });

  openReutersValidationBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("reuters-validation.html") });
  });

  function normalizeOrigins(value) {
    const origins = [];
    const seen = new Set();
    String(value || "").split(/[\n,]+/).forEach((entry) => {
      const text = entry.trim();
      if (!text) return;
      try {
        const parsed = new URL(text.includes("://") ? text : `https://${text}`);
        if (!["http:", "https:"].includes(parsed.protocol)) return;
        const origin = parsed.origin.toLowerCase();
        if (!seen.has(origin)) {
          seen.add(origin);
          origins.push(origin);
        }
      } catch (_error) {
        return;
      }
    });
    return origins;
  }

  function readBridgeForm() {
    const port = Number.parseInt(agentBridgePort.value, 10);
    return {
      enabled: agentBridgeEnabled.checked,
      port: Number.isInteger(port) && port >= 1024 && port <= 65535 ? port : 32145,
      token: agentBridgeToken.value.trim(),
      allowedOrigins: normalizeOrigins(agentBridgeAllowedOrigins.value)
    };
  }

  function loadAgentBridgeSettings() {
    chrome.storage.local.get(
      {
        agentBridgeEnabled: false,
        agentBridgePort: 32145,
        agentBridgeToken: "",
        agentBridgeAllowedOrigins: []
      },
      (stored) => {
        agentBridgeEnabled.checked = stored.agentBridgeEnabled === true;
        agentBridgePort.value = String(stored.agentBridgePort || 32145);
        agentBridgeToken.value = stored.agentBridgeToken || "";
        agentBridgeAllowedOrigins.value = normalizeOrigins(
          stored.agentBridgeAllowedOrigins
        ).join("\n");
        agentBridgeStatus.textContent = agentBridgeEnabled.checked
          ? "Bridge settings loaded; check the local connection."
          : "Bridge is disabled.";
      }
    );
  }

  saveAgentBridgeBtn.addEventListener("click", () => {
    const config = readBridgeForm();
    if (config.enabled && config.token.length < 32) {
      agentBridgeStatus.textContent = "A pairing token of at least 32 characters is required.";
      return;
    }
    if (config.enabled && !config.allowedOrigins.length) {
      agentBridgeStatus.textContent = "Add at least one authorized website origin.";
      return;
    }
    chrome.storage.local.set(
      {
        agentBridgeEnabled: config.enabled,
        agentBridgePort: config.port,
        agentBridgeToken: config.token,
        agentBridgeAllowedOrigins: config.allowedOrigins
      },
      () => {
        chrome.runtime.sendMessage(
          { type: "agent-browser-bridge-config-changed", enabled: config.enabled },
          () => {
            agentBridgeStatus.textContent = config.enabled
              ? "Bridge settings saved."
              : "Bridge disabled."
          }
        );
      }
    );
  });

  checkAgentBridgeBtn.addEventListener("click", async () => {
    const config = readBridgeForm();
    if (!config.token) {
      agentBridgeStatus.textContent = "Enter the pairing token first.";
      return;
    }
    agentBridgeStatus.textContent = "Checking the local bridge…";
    try {
      const response = await fetch(
        `http://127.0.0.1:${config.port}/v1/extension/heartbeat`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${config.token}`,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ extensionVersion: chrome.runtime.getManifest().version }),
          cache: "no-store",
          credentials: "omit"
        }
      );
      agentBridgeStatus.textContent = response.ok
        ? "Local bridge connected."
        : `Bridge rejected the pairing token (HTTP ${response.status}).`;
    } catch (_error) {
      agentBridgeStatus.textContent = "Local bridge is not running on this port.";
    }
  });

  // ------------------------------------------------------------
  // Export Snippets / Tags / Folders
  // ------------------------------------------------------------
  exportBtn.addEventListener("click", () => {
    chrome.storage.local.get(
      { snippets: [], tags: [], folders: {} },
      (data) => {
        const exportData = {
          version: "1.5.0",
          exportedAt: new Date().toISOString(),
          snippets: data.snippets,
          tags: data.tags,
          folders: data.folders
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
          type: "application/json"
        });

        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "snippet_export_1.5.0.json";
        a.click();
        URL.revokeObjectURL(url);
      }
    );
  });

  // ------------------------------------------------------------
  // Import Snippets / Tags / Folders
  // ------------------------------------------------------------
  importBtn.addEventListener("click", () => {
    const file = importFileInput.files[0];
    if (!file) {
      alert("Please select a JSON file to import.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);

        // Basic validation
        if (
          !json ||
          typeof json !== "object" ||
          !Array.isArray(json.snippets) ||
          !Array.isArray(json.tags) ||
          typeof json.folders !== "object"
        ) {
          alert("Invalid file format.");
          return;
        }

        const confirmReplace = confirm(
          "Import successful.\n\nReplace existing data with imported data?\n\nClick OK to replace, Cancel to merge."
        );

        chrome.storage.local.get(
          { snippets: [], tags: [], folders: {} },
          (current) => {
            let newSnippets, newTags, newFolders;

            if (confirmReplace) {
              // Replace everything
              newSnippets = json.snippets;
              newTags = json.tags;
              newFolders = json.folders;
            } else {
              // Merge
              newSnippets = [...current.snippets, ...json.snippets];

              const tagSet = new Set([...current.tags, ...json.tags]);
              newTags = Array.from(tagSet);

              newFolders = { ...current.folders, ...json.folders };
            }

            chrome.storage.local.set(
              {
                snippets: newSnippets,
                tags: newTags,
                folders: newFolders
              },
              () => {
                alert("Import completed successfully.");
                loadTagsAndSnippets();
              }
            );
          }
        );
      } catch (err) {
        alert("Failed to parse JSON file.");
      }
    };

    reader.readAsText(file);
  });

  // ------------------------------------------------------------
  // Open Changelog
  // ------------------------------------------------------------
  // openChangelogBtn.addEventListener("click", () => {
    // chrome.tabs.create({
      // url: chrome.runtime.getURL("CHANGELOG.md")
    // });
  // });

  // ------------------------------------------------------------
  // Tag Manager logic (moved from tag.js)
  // ------------------------------------------------------------
  function loadTagsAndSnippets() {
    chrome.storage.local.get(
      { tags: [], snippets: [] },
      (store) => {
        tags = store.tags || [];
        snippets = store.snippets || [];
        renderTagList();
      }
    );
  }

  addTagBtn.addEventListener("click", () => {
    const name = newTagInput.value.trim();
    if (!name) return;

    if (!tags.includes(name)) {
      tags.push(name);
      chrome.storage.local.set({ tags }, () => {
        newTagInput.value = "";
        renderTagList();
      });
    }
  });

  function renderTagList() {
    if (!tagListEl) return;
    tagListEl.innerHTML = "";

    const sorted = [...tags].sort((a, b) => a.localeCompare(b));

    sorted.forEach((tag) => {
      const li = document.createElement("li");
      li.style.display = "flex";
      li.style.alignItems = "center";
      li.style.justifyContent = "space-between";
      li.style.padding = "6px 0";

      const nameSpan = document.createElement("span");
      nameSpan.textContent = tag;

      const actions = document.createElement("div");
      actions.style.display = "flex";
      actions.style.gap = "6px";

      const renameBtn = document.createElement("button");
      renameBtn.textContent = "Rename";
      renameBtn.className = "btn-secondary btn-sm";
      renameBtn.onclick = () => renameTag(tag);

      const deleteBtn = document.createElement("button");
      deleteBtn.textContent = "Delete";
      deleteBtn.className = "btn-secondary btn-sm";
      deleteBtn.style.background = "#b00020";
      deleteBtn.onclick = () => deleteTag(tag);

      actions.appendChild(renameBtn);
      actions.appendChild(deleteBtn);

      li.appendChild(nameSpan);
      li.appendChild(actions);

      tagListEl.appendChild(li);
    });
  }

  function renameTag(oldName) {
    const newName = prompt("Rename tag:", oldName);
    if (!newName || newName === oldName) return;

    tags = tags.map((t) => (t === oldName ? newName : t));

    snippets = snippets.map((s) => {
      if (!s.tags) return s;
      if (!s.tags.includes(oldName)) return s;

      return {
        ...s,
        tags: s.tags.map((t) => (t === oldName ? newName : t))
      };
    });

    chrome.storage.local.set({ tags, snippets }, () => {
      renderTagList();
    });
  }

  function deleteTag(name) {
    if (!confirm(`Delete tag "${name}" from all snippets?`)) return;

    tags = tags.filter((t) => t !== name);

    snippets = snippets.map((s) => {
      if (!s.tags) return s;
      return {
        ...s,
        tags: s.tags.filter((t) => t !== name)
      };
    });

    chrome.storage.local.set({ tags, snippets }, () => {
      renderTagList();
    });
  }

  // Initial load for Tag Manager
  if (tagListEl) {
    loadTagsAndSnippets();
  }
  loadAgentBridgeSettings();
});
