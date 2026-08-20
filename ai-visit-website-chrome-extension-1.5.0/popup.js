// ------------------------------
// Helpers for folders (nested tree + paths)
// ------------------------------
function ensureFoldersStructure(store) {
  if (!store.folders || typeof store.folders !== "object") {
    store.folders = {};
  }
  return store.folders;
}

function getAllFolderPathsFromTree(tree, prefix = []) {
  const paths = [];
  const keys = Object.keys(tree).sort((a, b) => a.localeCompare(b));

  for (const key of keys) {
    const currentPath = [...prefix, key];
    paths.push(currentPath.join("/"));

    const children = tree[key];
    if (children && typeof children === "object") {
      paths.push(...getAllFolderPathsFromTree(children, currentPath));
    }
  }
  return paths;
}

function getOrCreateFolderNode(tree, pathSegments) {
  let node = tree;
  for (const segment of pathSegments) {
    if (!node[segment]) node[segment] = {};
    node = node[segment];
  }
  return node;
}

function getFolderNode(tree, pathSegments) {
  let node = tree;
  for (const segment of pathSegments) {
    if (!node[segment]) return null;
    node = node[segment];
  }
  return node;
}

function renameFolderInTree(tree, oldPath, newPath) {
  const oldSegments = oldPath.split("/");
  const newSegments = newPath.split("/");

  const parentOld = oldSegments.slice(0, -1);
  const parentNew = newSegments.slice(0, -1);

  const oldName = oldSegments.at(-1);
  const newName = newSegments.at(-1);

  const oldParentNode = getFolderNode(tree, parentOld);
  if (!oldParentNode || !oldParentNode[oldName]) return;

  const subtree = oldParentNode[oldName];
  delete oldParentNode[oldName];

  const newParentNode = getOrCreateFolderNode(tree, parentNew);
  newParentNode[newName] = subtree;
}

function deleteFolderFromTree(tree, path) {
  const segments = path.split("/");
  const parent = segments.slice(0, -1);
  const name = segments.at(-1);

  const parentNode = getFolderNode(tree, parent);
  if (parentNode && parentNode[name]) {
    delete parentNode[name];
  }
}

// ------------------------------
// State
// ------------------------------
let snippets = [];
let tags = [];
let foldersTree = {};
let activeFolderPath = "";
let activeTagFilter = null;
let dragSnippetIndex = null;
let currentSort = "newest";

// ------------------------------
// DOM elements
// ------------------------------
const folderTreeEl = document.getElementById("folderTree");
const snippetListEl = document.getElementById("snippetList");
const tagFilterChipsEl = document.getElementById("tagFilterChips");
const searchInput = document.getElementById("searchInput");
const sortSelect = document.getElementById("sortSelect");

const newFolderBtn = document.getElementById("newFolderBtn");
const newFolderModalOverlay = document.getElementById("newFolderModalOverlay");
const newFolderParentSelect = document.getElementById("newFolderParentSelect");
const newFolderNameInput = document.getElementById("newFolderNameInput");
const newFolderCancelBtn = document.getElementById("newFolderCancelBtn");
const newFolderCreateBtn = document.getElementById("newFolderCreateBtn");

const openTagManagerBtn = document.getElementById("openTagManagerBtn");

// ------------------------------
// Init
// ------------------------------
chrome.storage.local.get(
  { snippets: [], tags: [], folders: {} },
  (store) => {
    snippets = store.snippets || [];
    tags = store.tags || [];
    foldersTree = ensureFoldersStructure(store);

    renderFolderTree();
    renderTagFilters();
    renderSnippets();
  }
);

// ------------------------------
// Render folder tree
// ------------------------------
function renderFolderTree() {
  folderTreeEl.innerHTML = "";

  const rootUl = document.createElement("ul");
  rootUl.style.listStyle = "none";
  rootUl.style.paddingLeft = "0";

  const rootItem = document.createElement("li");
  
  // Enable dropping folders onto "All Snippets" (root)
rootItem.addEventListener("dragover", (e) => {
  e.preventDefault();
  rootItem.classList.add("folderDropTarget");
});

rootItem.addEventListener("dragleave", () => {
  rootItem.classList.remove("folderDropTarget");
});

rootItem.addEventListener("drop", (e) => {
  e.preventDefault();
  rootItem.classList.remove("folderDropTarget");

  const draggedPath = document.querySelector(".folderDragging")?.dataset.dragPath;
  if (!draggedPath) return;

  // Compute new root-level path
  const newName = draggedPath.split("/").pop();
  const newPath = newName; // root-level folder

  // Prevent no-op
  if (draggedPath === newPath) return;

  // Move folder in tree
  renameFolderInTree(foldersTree, draggedPath, newPath);

  // Update snippet folder paths
  snippets = snippets.map((s) => {
    if (s.folder === draggedPath) return { ...s, folder: newPath };
    if (s.folder.startsWith(draggedPath + "/")) {
      return { ...s, folder: s.folder.replace(draggedPath, newPath) };
    }
    return s;
  });

  chrome.storage.local.set({ folders: foldersTree, snippets }, () => {
    renderFolderTree();
    renderSnippets();
  });
});

  
  rootItem.className = "folderNodeRow";
  rootItem.innerHTML = `
    <span class="folderToggle" style="visibility:hidden;">•</span>
    <span class="folderNode ${!activeFolderPath ? "folderActive" : ""}">
      All Snippets
    </span>
  `;

  rootItem.addEventListener("click", () => {
    activeFolderPath = "";
    renderFolderTree();
    renderSnippets();
  });

  rootUl.appendChild(rootItem);

  const keys = Object.keys(foldersTree).sort((a, b) => a.localeCompare(b));
  keys.forEach((key) => {
    const li = createFolderNodeElement([key], foldersTree[key]);
    rootUl.appendChild(li);
  });

  folderTreeEl.appendChild(rootUl);
}

function createFolderNodeElement(pathSegments, node) {
  const li = document.createElement("li");
  li.style.listStyle = "none";

  const folderPath = pathSegments.join("/");

  const row = document.createElement("div");
  row.className = "folderNodeRow";

  const toggle = document.createElement("span");
  toggle.className = "folderToggle";
  const hasChildren = node && Object.keys(node).length > 0;
  toggle.textContent = hasChildren ? "▾" : "•";
  toggle.style.visibility = hasChildren ? "visible" : "hidden";

  const label = document.createElement("span");
  label.className = "folderNode";
  label.textContent = pathSegments.at(-1);

  if (activeFolderPath === folderPath) {
    label.classList.add("folderActive");
  }

  label.addEventListener("click", () => {
    activeFolderPath = folderPath;
    renderFolderTree();
    renderSnippets();
  });

  // ------------------------------
  // Snippet drag & drop (existing)
  // ------------------------------
  label.addEventListener("dragover", (e) => {
    e.preventDefault();
    label.classList.add("folderDropTarget");
  });

  label.addEventListener("dragleave", () => {
    label.classList.remove("folderDropTarget");
  });

  label.addEventListener("drop", (e) => {
    e.preventDefault();
    label.classList.remove("folderDropTarget");

    if (dragSnippetIndex !== null) {
      snippets[dragSnippetIndex].folder = folderPath || "Root";
      chrome.storage.local.set({ snippets }, () => {
        renderSnippets();
      });
    }
  });

  // ------------------------------
  // ⭐ Folder drag & drop (move folder)
  // ------------------------------
  label.draggable = true;

  label.addEventListener("dragstart", (e) => {
    e.stopPropagation();
    label.classList.add("folderDragging");
    label.dataset.dragPath = folderPath;
  });

  label.addEventListener("dragend", () => {
    label.classList.remove("folderDragging");
    delete label.dataset.dragPath;
  });

  label.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    label.classList.add("folderDropTarget");
  });

  label.addEventListener("dragleave", () => {
    label.classList.remove("folderDropTarget");
  });

  label.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    label.classList.remove("folderDropTarget");

    const draggedPath = document.querySelector(".folderDragging")?.dataset.dragPath;
    if (!draggedPath) return;

    // Prevent dropping onto itself
    if (draggedPath === folderPath) return;

    // Prevent dropping into its own descendant
    if (folderPath.startsWith(draggedPath + "/")) return;

    // Compute new path
    const newPath = folderPath + "/" + draggedPath.split("/").pop();

    // Move folder in tree
    renameFolderInTree(foldersTree, draggedPath, newPath);

    // Update snippet folder paths
    snippets = snippets.map((s) => {
      if (s.folder === draggedPath) return { ...s, folder: newPath };
      if (s.folder.startsWith(draggedPath + "/")) {
        return { ...s, folder: s.folder.replace(draggedPath, newPath) };
      }
      return s;
    });

    chrome.storage.local.set({ folders: foldersTree, snippets }, () => {
      renderFolderTree();
      renderSnippets();
    });
  });

  // ------------------------------
  // Folder actions (rename/delete)
  // ------------------------------
  const actions = document.createElement("span");
  actions.style.marginLeft = "auto";
  actions.style.display = "flex";
  actions.style.gap = "4px";

  const renameBtn = document.createElement("button");
  renameBtn.textContent = "✎";
  renameBtn.className = "btn-secondary btn-sm";
  renameBtn.onclick = (e) => {
    e.stopPropagation();
    renameFolder(folderPath);
  };

  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "🗑";
  deleteBtn.className = "btn-secondary btn-sm";
  deleteBtn.onclick = (e) => {
    e.stopPropagation();
    deleteFolder(folderPath);
  };

  actions.appendChild(renameBtn);
  actions.appendChild(deleteBtn);

  row.appendChild(toggle);
  row.appendChild(label);
  row.appendChild(actions);
  li.appendChild(row);

  if (hasChildren) {
    const childrenContainer = document.createElement("ul");
    childrenContainer.style.listStyle = "none";
    childrenContainer.style.paddingLeft = "16px";

    const childKeys = Object.keys(node).sort((a, b) =>
      a.localeCompare(b)
    );

    childKeys.forEach((childKey) => {
      const childLi = createFolderNodeElement(
        [...pathSegments, childKey],
        node[childKey]
      );
      childrenContainer.appendChild(childLi);
    });

    li.appendChild(childrenContainer);

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const expanded = childrenContainer.style.display !== "none";
      childrenContainer.style.display = expanded ? "none" : "block";
      toggle.textContent = expanded ? "▸" : "▾";
    });
  }

  return li;
}
// ------------------------------
// Folder rename/delete
// ------------------------------
function renameFolder(oldPath) {
  const newName = prompt("Rename folder:", oldPath.split("/").pop());
  if (!newName) return;

  const parent = oldPath.split("/").slice(0, -1).join("/");
  const newPath = parent ? `${parent}/${newName}` : newName;

  renameFolderInTree(foldersTree, oldPath, newPath);

  snippets = snippets.map((s) => {
    if (s.folder === oldPath) return { ...s, folder: newPath };
    if (s.folder.startsWith(oldPath + "/")) {
      return { ...s, folder: s.folder.replace(oldPath, newPath) };
    }
    return s;
  });

  chrome.storage.local.set({ folders: foldersTree, snippets }, () => {
    renderFolderTree();
    renderSnippets();
  });
}

function deleteFolder(path) {
  const choice = confirm(
    `Delete folder "${path}"?\n\nOK = delete all snippets inside.\nCancel = move snippets to Root.`
  );

  if (choice) {
    snippets = snippets.filter(
      (s) => s.folder !== path && !s.folder.startsWith(path + "/")
    );
  } else {
    snippets = snippets.map((s) => {
      if (s.folder === path || s.folder.startsWith(path + "/")) {
        return { ...s, folder: "Root" };
      }
      return s;
    });
  }

  deleteFolderFromTree(foldersTree, path);

  chrome.storage.local.set({ folders: foldersTree, snippets }, () => {
    renderFolderTree();
    renderSnippets();
  });
}

// ------------------------------
// Tag filters
// ------------------------------
function renderTagFilters() {
  tagFilterChipsEl.innerHTML = "";

  const allChip = document.createElement("span");
  allChip.textContent = "All";
  allChip.className = "tagChip clickableTag";
  if (!activeTagFilter) allChip.classList.add("tagSelected");

  allChip.addEventListener("click", () => {
    activeTagFilter = null;
    renderTagFilters();
    renderSnippets();
  });

  tagFilterChipsEl.appendChild(allChip);

  const sortedTags = [...tags].sort((a, b) => a.localeCompare(b));
  sortedTags.forEach((tag) => {
    const chip = document.createElement("span");
    chip.textContent = tag;
    chip.className = "tagChip clickableTag";

    if (activeTagFilter === tag) chip.classList.add("tagSelected");

    chip.addEventListener("click", () => {
      activeTagFilter = tag;
      renderTagFilters();
      renderSnippets();
    });

    tagFilterChipsEl.appendChild(chip);
  });
}

// ------------------------------
// Sorting
// ------------------------------
function sortSnippets(list) {
  switch (currentSort) {
    case "newest":
      return list.sort((a, b) => new Date(b.date) - new Date(a.date));
    case "oldest":
      return list.sort((a, b) => new Date(a.date) - new Date(b.date));
    case "az":
      return list.sort((a, b) => getSnippetSortText(a).localeCompare(getSnippetSortText(b)));
    case "za":
      return list.sort((a, b) => getSnippetSortText(b).localeCompare(getSnippetSortText(a)));
    default:
      return list;
  }
}

function isMarkdownPageSnippet(snippet) {
  return snippet.contentFormat === "markdown" || snippet.captureMode === "page";
}

function getSnippetTitle(snippet) {
  if (snippet.title) return snippet.title;
  if (isMarkdownPageSnippet(snippet)) {
    const heading = String(snippet.text || "").match(/^#\s+(.+)$/m);
    if (heading) return heading[1].trim();
  }
  return snippet.note || truncateText(snippet.text || "Untitled snippet", 80);
}

function getSnippetPreview(snippet) {
  const source = snippet.excerpt || snippet.text || "";
  const plainText = String(source)
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[`*_>|-]/g, "")
    .replace(/\s+/g, " ")
    .trim();

  return truncateText(plainText, isMarkdownPageSnippet(snippet) ? 260 : 500);
}

function getSnippetSortText(snippet) {
  return `${getSnippetTitle(snippet)} ${getSnippetPreview(snippet)}`;
}

function truncateText(text, maxLength) {
  const value = String(text || "").trim();
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trim()}…`;
}

// ------------------------------
// Render snippets
// ------------------------------
function renderSnippets() {
  snippetListEl.innerHTML = "";

  const query = searchInput ? searchInput.value.toLowerCase() : "";

  let filtered = snippets.filter((snippet) => {
    if (activeFolderPath) {
      if ((snippet.folder || "Root") !== activeFolderPath) return false;
    }

    if (activeTagFilter) {
      if (!snippet.tags || !snippet.tags.includes(activeTagFilter)) return false;
    }

    if (query) {
      const haystack = [
        snippet.text,
        snippet.note,
        snippet.title,
        snippet.excerpt,
        snippet.url,
        ...(snippet.tags || [])
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    return true;
  });

  filtered = sortSnippets(filtered);

  filtered.forEach((snippet) => {
    const index = snippets.indexOf(snippet);

    const li = document.createElement("li");
    li.className = "snippet-card";
    li.draggable = true;

    li.addEventListener("dragstart", () => {
      dragSnippetIndex = index;
      li.classList.add("snippetDragging");
    });

    li.addEventListener("dragend", () => {
      dragSnippetIndex = null;
      li.classList.remove("snippetDragging");
    });

    const textDiv = document.createElement("div");
    if (isMarkdownPageSnippet(snippet)) {
      const titleDiv = document.createElement("div");
      titleDiv.style.fontWeight = "700";
      titleDiv.style.marginBottom = "4px";
      titleDiv.textContent = getSnippetTitle(snippet);

      const previewDiv = document.createElement("div");
      previewDiv.style.whiteSpace = "pre-wrap";
      previewDiv.textContent = getSnippetPreview(snippet);

      textDiv.appendChild(titleDiv);
      textDiv.appendChild(previewDiv);
    } else {
      textDiv.textContent = snippet.text;
    }

    const noteDiv = document.createElement("div");
    noteDiv.style.fontSize = "12px";
    noteDiv.style.opacity = "0.85";
    noteDiv.style.marginTop = "4px";
    if (snippet.note && snippet.note !== snippet.title) {
      noteDiv.textContent = `Note: ${snippet.note}`;
    }

    const urlDiv = document.createElement("div");
    urlDiv.style.fontSize = "11px";
    urlDiv.style.marginTop = "4px";
    if (snippet.url) {
      const a = document.createElement("a");
      a.href = snippet.url;
      a.target = "_blank";
      a.textContent = "Source";
      urlDiv.appendChild(a);
    }

    const metaDiv = document.createElement("div");
    metaDiv.style.fontSize = "11px";
    metaDiv.style.opacity = "0.7";
    metaDiv.textContent = `${snippet.folder || "Root"} • ${snippet.date}`;

    const tagsDiv = document.createElement("div");
    if (snippet.tags && snippet.tags.length > 0) {
      snippet.tags.forEach((tag) => {
        const chip = document.createElement("span");
        chip.textContent = tag;
        chip.className = "tagChip";
        tagsDiv.appendChild(chip);
      });
    }

    // Inline editors and action buttons come in Block 3
    // They will be appended to this <li> after tagsDiv

    li.appendChild(textDiv);
    li.appendChild(noteDiv);
    li.appendChild(urlDiv);
    li.appendChild(metaDiv);
    li.appendChild(tagsDiv);

    snippetListEl.appendChild(li);
	
	attachInlineEditors(li, snippet, index);
	
  });
}
// ------------------------------
// Inline editors + action buttons (appended inside renderSnippets)
// ------------------------------
function attachInlineEditors(li, snippet, index) {
  // ------------------------------
  // Inline Note Editor
  // ------------------------------
  const noteEditor = document.createElement("div");
  noteEditor.style.display = "none";
  noteEditor.style.marginTop = "8px";

  const noteTextarea = document.createElement("textarea");
  noteTextarea.value = snippet.note || "";
  noteTextarea.style.width = "100%";
  noteTextarea.style.height = "70px";
  noteTextarea.style.marginBottom = "6px";

  const noteSaveBtn = document.createElement("button");
  noteSaveBtn.textContent = "Save Note";
  noteSaveBtn.className = "btn-primary btn-sm";

  const noteCancelBtn = document.createElement("button");
  noteCancelBtn.textContent = "Cancel";
  noteCancelBtn.className = "btn-secondary btn-sm";
  noteCancelBtn.style.marginLeft = "6px";

  noteSaveBtn.onclick = () => {
    snippet.note = noteTextarea.value.trim();
    chrome.storage.local.set({ snippets }, () => {
      renderSnippets();
    });
  };

  noteCancelBtn.onclick = () => {
    noteEditor.style.display = "none";
  };

  noteEditor.appendChild(noteTextarea);
  noteEditor.appendChild(noteSaveBtn);
  noteEditor.appendChild(noteCancelBtn);

  // ------------------------------
  // Inline Tag Editor
  // ------------------------------
  const tagEditor = document.createElement("div");
  tagEditor.style.display = "none";
  tagEditor.style.marginTop = "8px";
  tagEditor.style.padding = "8px";
  tagEditor.style.border = "1px solid var(--border)";
  tagEditor.style.borderRadius = "6px";
  tagEditor.style.background = "var(--card-bg)";

  function renderTagSelector() {
    tagEditor.innerHTML = "";

    const allTags = Array.from(new Set([...tags, ...(snippet.tags || [])]));

    allTags.forEach((tag) => {
      const chip = document.createElement("span");
      chip.textContent = tag;
      chip.className = "tagChip clickableTag";

      chip.style.opacity = snippet.tags?.includes(tag) ? "1" : "0.5";

      chip.onclick = () => {
        if (!snippet.tags) snippet.tags = [];

        if (snippet.tags.includes(tag)) {
          snippet.tags = snippet.tags.filter((t) => t !== tag);
        } else {
          snippet.tags.push(tag);
        }

        chrome.storage.local.set({ snippets }, () => {
          renderSnippets();
        });
      };

      tagEditor.appendChild(chip);
    });

    const newTagInput = document.createElement("input");
    newTagInput.placeholder = "New tag";
    newTagInput.style.marginTop = "6px";

    const addBtn = document.createElement("button");
    addBtn.textContent = "Add";
    addBtn.className = "btn-primary btn-sm";
    addBtn.style.marginLeft = "6px";

    addBtn.onclick = () => {
      const val = newTagInput.value.trim();
      if (!val) return;

      if (!snippet.tags) snippet.tags = [];
      if (!snippet.tags.includes(val)) snippet.tags.push(val);

      if (!tags.includes(val)) tags.push(val);

      chrome.storage.local.set({ snippets, tags }, () => {
        renderTagFilters();
        renderSnippets();
      });
    };

    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.marginTop = "6px";
    row.appendChild(newTagInput);
    row.appendChild(addBtn);

    tagEditor.appendChild(row);
  }

  renderTagSelector();

  // ------------------------------
  // Action Buttons
  // ------------------------------
  const actionsDiv = document.createElement("div");
  actionsDiv.style.marginTop = "8px";
  actionsDiv.style.display = "flex";
  actionsDiv.style.gap = "6px";

  const editNoteBtn = document.createElement("button");
  editNoteBtn.textContent = "Edit Note";
  editNoteBtn.className = "btn-secondary btn-sm";
  editNoteBtn.onclick = () => {
    noteEditor.style.display =
      noteEditor.style.display === "none" ? "block" : "none";
  };

  const editTagsBtn = document.createElement("button");
  editTagsBtn.textContent = "Edit Tags";
  editTagsBtn.className = "btn-secondary btn-sm";
  editTagsBtn.onclick = () => {
    tagEditor.style.display =
      tagEditor.style.display === "none" ? "block" : "none";
  };

  const copyBtn = document.createElement("button");
  copyBtn.textContent = "Copy";
  copyBtn.className = "btn-secondary btn-sm";
  copyBtn.onclick = async () => {
    copyBtn.disabled = true;

    try {
      await SnippetClipboard.copySnippetToClipboard(snippet);
      copyBtn.textContent = "Copied!";
    } catch (error) {
      console.error("Failed to copy snippet to clipboard:", error);
      copyBtn.textContent = "Copy failed";
    }

    setTimeout(() => {
      copyBtn.textContent = "Copy";
      copyBtn.disabled = false;
    }, 1200);
  };

  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "Delete";
  deleteBtn.className = "btn-secondary btn-sm";
  deleteBtn.style.background = "#b00020";
  deleteBtn.onclick = () => deleteSnippet(index);

  actionsDiv.appendChild(editNoteBtn);
  actionsDiv.appendChild(editTagsBtn);
  actionsDiv.appendChild(copyBtn);
  actionsDiv.appendChild(deleteBtn);

  // Append everything to the snippet card
  li.appendChild(actionsDiv);
  li.appendChild(noteEditor);
  li.appendChild(tagEditor);
}

// ------------------------------
// Delete Snippet
// ------------------------------
function deleteSnippet(index) {
  if (!confirm("Delete this snippet?")) return;

  snippets.splice(index, 1);

  chrome.storage.local.set({ snippets }, () => {
    renderSnippets();
  });
}

// ------------------------------
// Settings Page
// ------------------------------
document.getElementById("openSettingsBtn")?.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

// Gear icon (same behavior)
openTagManagerBtn?.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

// ------------------------------
// ⭐ Restored + Upgraded New Folder Modal
// ------------------------------
newFolderBtn?.addEventListener("click", () => {
  openNewFolderModal();
});

newFolderCancelBtn?.addEventListener("click", () => {
  closeNewFolderModal();
});

newFolderCreateBtn?.addEventListener("click", () => {
  const parentPath = newFolderParentSelect.value;
  const name = newFolderNameInput.value.trim();
  if (!name) return;

  const segments = parentPath ? parentPath.split("/") : [];
  segments.push(name);

  getOrCreateFolderNode(foldersTree, segments);

  chrome.storage.local.set({ folders: foldersTree }, () => {
    closeNewFolderModal();
    renderFolderTree();
  });
});

function openNewFolderModal() {
  newFolderParentSelect.innerHTML = "";

  // Root option
  const rootOption = document.createElement("option");
  rootOption.value = "";
  rootOption.textContent = "(root)";
  newFolderParentSelect.appendChild(rootOption);

  // Existing folders (reflecting rename/delete)
  const paths = getAllFolderPathsFromTree(foldersTree);
  paths.forEach((path) => {
    const depth = path.split("/").length - 1;
    const opt = document.createElement("option");
    opt.value = path;
    opt.innerHTML = "&nbsp;".repeat(depth * 4) + path.split("/").pop();
    newFolderParentSelect.appendChild(opt);
  });

  newFolderNameInput.value = "";
  newFolderModalOverlay.style.display = "flex";
}

function closeNewFolderModal() {
  newFolderModalOverlay.style.display = "none";
}
