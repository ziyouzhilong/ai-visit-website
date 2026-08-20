if (typeof importScripts === "function") {
  importScripts("reuters-article-extractor.js", "agent-browser-bridge.js");
}

const AGENT_BRIDGE_WAKE_ALARM = "agentBrowserBridgeWake";
let agentBrowserWorkerTabId = null;

globalThis.executeAgentBrowserRead = executeAgentBrowserRead;
if (globalThis.AgentBrowserBridge) {
  globalThis.AgentBrowserBridge.start();
}
if (chrome.runtime.onStartup?.addListener) {
  chrome.runtime.onStartup.addListener(() => {
    chrome.alarms?.create(AGENT_BRIDGE_WAKE_ALARM, { periodInMinutes: 0.5 });
    globalThis.AgentBrowserBridge?.start();
  });
}
if (chrome.alarms?.onAlarm?.addListener) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === AGENT_BRIDGE_WAKE_ALARM) {
      globalThis.AgentBrowserBridge?.start();
    }
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms?.create(AGENT_BRIDGE_WAKE_ALARM, { periodInMinutes: 0.5 });
  globalThis.AgentBrowserBridge?.start();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "agent-browser-bridge-config-changed") {
    return false;
  }
  if (message.enabled === false) {
    globalThis.AgentBrowserBridge?.stop();
  } else {
    globalThis.AgentBrowserBridge?.restart();
  }
  sendResponse({ success: true });
  return false;
});

chrome.action.onClicked.addListener(() => {
  chrome.runtime.openOptionsPage(() => {
    if (chrome.runtime.lastError) {
      console.warn("Could not open AI Visit website settings.");
    }
  });
});

function isReutersBusinessArticleUrl(value) {
  try {
    const url = new URL(value);
    return (
      url.hostname === "www.reuters.com" &&
      /^\/business\/.+-\d{4}-\d{2}-\d{2}\/?$/.test(url.pathname)
    );
  } catch (_error) {
    return false;
  }
}

// ------------------------------
// Agent Browser Bridge
// ------------------------------
async function executeAgentBrowserRead(task, context = {}) {
  const startedAt = Date.now();
  const taskUrl = String(task?.url || "");
  const allowedOrigins = context.allowedOrigins || [];
  if (!globalThis.AgentBrowserBridge?.isOriginAllowed(taskUrl, allowedOrigins)) {
    return bridgeFailure(
      task,
      "domain_not_authorized",
      "The requested website origin is not authorized in the Chrome extension.",
      false,
      startedAt
    );
  }

  let tab;
  try {
    tab = await openAgentBrowserTab(taskUrl, Number(task?.timeoutSeconds) || 60);
    await bridgeDelay(1600);
  } catch (_error) {
    return bridgeFailure(
      task,
      "page_load_failed",
      "Chrome could not load the requested page.",
      true,
      startedAt
    );
  }

  let probe;
  try {
    probe = await probeAgentBrowserTab(tab.id);
  } catch (_error) {
    return bridgeFailure(
      task,
      "page_probe_failed",
      "Chrome could not inspect the loaded page.",
      true,
      startedAt,
      { final_url: tab.url || taskUrl }
    );
  }

  if (!globalThis.AgentBrowserBridge.isOriginAllowed(probe.finalUrl, allowedOrigins)) {
    return bridgeFailure(
      task,
      "unexpected_redirect",
      "The page redirected outside the authorized website origins.",
      false,
      startedAt,
      { final_url: probe.finalUrl }
    );
  }
  const blockingFailure = classifyAgentBrowserProbe(probe);
  if (blockingFailure) {
    return bridgeFailure(
      task,
      blockingFailure.code,
      blockingFailure.message,
      false,
      startedAt,
      { final_url: probe.finalUrl, title: probe.title }
    );
  }

  const captureFunction = isReutersBusinessArticleUrl(probe.finalUrl)
    ? globalThis.injectedExtractReutersArticle
    : injectedCapturePageAsMarkdown;
  if (typeof captureFunction !== "function") {
    return bridgeFailure(
      task,
      "extractor_unavailable",
      "The required page extractor is unavailable.",
      false,
      startedAt,
      { final_url: probe.finalUrl, title: probe.title }
    );
  }

  let capture;
  try {
    const results = await executeAgentScript({
      target: { tabId: tab.id },
      func: captureFunction
    });
    capture = results?.[0]?.result;
  } catch (_error) {
    capture = null;
  }
  if (!capture?.markdown || capture.success === false) {
    return bridgeFailure(
      task,
      capture?.failure?.code || "empty_article",
      capture?.failure?.message || "The page produced no readable Markdown.",
      capture?.failure?.retryable === true,
      startedAt,
      { final_url: probe.finalUrl, title: capture?.title || probe.title }
    );
  }

  const markdown = String(capture.markdown).trim();
  const contentHash = await sha256Markdown(markdown);
  return {
    success: true,
    original_url: taskUrl,
    final_url: probe.finalUrl,
    title: capture.title || probe.title || null,
    published_at: capture.publishedAt || null,
    author: capture.author || null,
    markdown,
    content_hash: contentHash,
    adapter: "chrome-extension",
    elapsed_ms: Date.now() - startedAt,
    status_code: null,
    paragraph_count: Number(capture.paragraphCount) || Number(probe.paragraphCount) || 0,
    article_text_length:
      Number(capture.articleTextLength) || Number(probe.articleTextLength) || markdown.length,
    selector_strategy: capture.selectorStrategy || "generic-page-dom",
    failure: null
  };
}

function classifyAgentBrowserProbe(probe) {
  if (probe.challengeDetected) {
    return {
      code: "bot_challenge",
      message: "The website presented a CAPTCHA or automated-access challenge."
    };
  }
  if (probe.accessDeniedDetected) {
    return { code: "access_denied", message: "The website denied access to the page." };
  }
  if (probe.loginRequiredDetected && probe.articleTextLength < 500) {
    return { code: "login_required", message: "The Chrome website session requires login." };
  }
  if (probe.paywallDetected && probe.articleTextLength < 500) {
    return { code: "paywall", message: "The article is not readable with the current subscription." };
  }
  return null;
}

function bridgeFailure(task, code, message, retryable, startedAt, updates = {}) {
  return {
    ...globalThis.AgentBrowserBridge.failureResult(task, code, message, retryable),
    ...updates,
    elapsed_ms: Date.now() - startedAt
  };
}

async function openAgentBrowserTab(url, timeoutSeconds) {
  let existing = null;
  if (agentBrowserWorkerTabId) {
    existing = await getAgentBrowserTab(agentBrowserWorkerTabId).catch(() => null);
  }
  const tab = existing
    ? await updateAgentBrowserTab(existing.id, url)
    : await createAgentBrowserTab(url);
  agentBrowserWorkerTabId = tab.id;
  return waitForAgentBrowserTab(tab.id, Math.max(15000, timeoutSeconds * 1000));
}

function createAgentBrowserTab(url) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: true }, (tab) => {
      if (chrome.runtime.lastError || !tab?.id) {
        reject(new Error(chrome.runtime.lastError?.message || "tab_create_failed"));
        return;
      }
      resolve(tab);
    });
  });
}

function updateAgentBrowserTab(tabId, url) {
  return new Promise((resolve, reject) => {
    chrome.tabs.update(tabId, { url, active: true }, (tab) => {
      if (chrome.runtime.lastError || !tab) {
        reject(new Error(chrome.runtime.lastError?.message || "tab_update_failed"));
        return;
      }
      resolve(tab);
    });
  });
}

function getAgentBrowserTab(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError || !tab) {
        reject(new Error(chrome.runtime.lastError?.message || "tab_not_found"));
        return;
      }
      resolve(tab);
    });
  });
}

function waitForAgentBrowserTab(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error("page_load_timeout")), timeoutMs);
    const onUpdated = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") finish(null, tab);
    };
    const onRemoved = (removedTabId) => {
      if (removedTabId === tabId) {
        agentBrowserWorkerTabId = null;
        finish(new Error("browser_tab_closed"));
      }
    };
    const finish = (error, tab) => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      chrome.tabs.onRemoved.removeListener(onRemoved);
      if (error) reject(error);
      else resolve(tab);
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.onRemoved.addListener(onRemoved);
    getAgentBrowserTab(tabId).then((tab) => {
      if (tab.status === "complete" && tab.url && tab.url !== "about:blank") finish(null, tab);
    }).catch(() => {});
  });
}

async function probeAgentBrowserTab(tabId) {
  const results = await executeAgentScript({
    target: { tabId },
    func: async () => {
      const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
      for (let step = 0; step < 5; step += 1) {
        const height = Math.max(
          document.body?.scrollHeight || 0,
          document.documentElement?.scrollHeight || 0
        );
        window.scrollTo({
          top: Math.min(height, (step + 1) * window.innerHeight * 0.9),
          behavior: "auto"
        });
        await wait(350);
      }
      await wait(500);
      const selectors = [
        "article [data-testid^='paragraph-']",
        "main [data-testid^='paragraph-']",
        "[itemprop='articleBody'] p",
        "article p",
        "main p"
      ];
      const texts = [];
      const seen = new Set();
      selectors.forEach((selector) => {
        document.querySelectorAll(selector).forEach((node) => {
          if (seen.has(node)) return;
          seen.add(node);
          const text = String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
          if (text.length >= 20) texts.push(text);
        });
      });
      const bodyText = String(document.body?.innerText || "").replace(/\s+/g, " ").trim();
      const detectionText = bodyText.toLowerCase().slice(0, 30000);
      return {
        finalUrl: location.href,
        title: document.title,
        articleTextLength: texts.join("\n\n").length,
        paragraphCount: texts.length,
        challengeDetected:
          /captcha|verify you are human|are you a human|unusual traffic|press and hold|security check/.test(detectionText),
        accessDeniedDetected:
          /access denied|request blocked|forbidden|not available in your region/.test(detectionText),
        loginRequiredDetected:
          /sign in to continue|log in to continue|please sign in|login required/.test(detectionText),
        paywallDetected:
          /subscribe to continue|subscription required|already a subscriber/.test(detectionText)
      };
    }
  });
  if (!results?.[0]?.result) throw new Error("page_probe_failed");
  return results[0].result;
}

function executeAgentScript(details) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript(details, (results) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || "script_execution_failed"));
        return;
      }
      resolve(results);
    });
  });
}

async function sha256Markdown(markdown) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(String(markdown || ""))
  );
  return `sha256:${Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")}`;
}

function bridgeDelay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

// ------------------------------
// Injected Page Capture
// ------------------------------
function injectedCapturePageAsMarkdown() {
  const root = document.body;
  const title = normalizeInlineText(document.title) || "Untitled page";
  const bodyMarkdown = normalizeMarkdown(convertNodeToMarkdown(root));
  const source = location.href;
  const markdown = normalizeMarkdown(`# ${title}\n\nSource: ${source}\n\n${bodyMarkdown}`);
  const excerpt = getExcerpt(root);

  return {
    title,
    markdown,
    excerpt
  };

  function getVisibleText(node) {
    if (!node || shouldSkipElement(node)) return "";
    return normalizeInlineText(node.innerText || node.textContent || "");
  }

  function getExcerpt(node) {
    return getVisibleText(node).slice(0, 240);
  }

  function convertNodeToMarkdown(node, context = {}) {
    if (!node) return "";

    if (node.nodeType === Node.TEXT_NODE) {
      return normalizeTextNode(node.textContent || "");
    }

    if (node.nodeType !== Node.ELEMENT_NODE || shouldSkipElement(node)) {
      return "";
    }

    const tagName = node.tagName.toLowerCase();

    if (/^h[1-6]$/.test(tagName)) {
      const level = Number(tagName.slice(1));
      const text = renderInlineChildren(node).trim();
      return text ? `\n\n${"#".repeat(level)} ${text}\n\n` : "";
    }

    switch (tagName) {
      case "a":
        return renderLink(node);
      case "article":
      case "body":
      case "div":
      case "main":
      case "section":
        return renderBlockChildren(node, context);
      case "blockquote":
        return renderBlockquote(node, context);
      case "br":
        return "  \n";
      case "code":
        return node.parentElement?.tagName?.toLowerCase() === "pre"
          ? node.textContent || ""
          : renderInlineCode(node.textContent || "");
      case "em":
      case "i":
        return wrapInline(node, "*");
      case "hr":
        return "\n\n---\n\n";
      case "img":
        return renderImage(node);
      case "li":
        return renderInlineChildren(node).trim();
      case "ol":
      case "ul":
        return renderList(node, tagName === "ol", context);
      case "p":
        return renderParagraph(node);
      case "pre":
        return renderCodeBlock(node);
      case "strong":
      case "b":
        return wrapInline(node, "**");
      case "table":
        return renderTable(node);
      case "tbody":
      case "thead":
      case "tr":
        return renderBlockChildren(node, context);
      case "td":
      case "th":
        return renderInlineChildren(node).trim();
      default:
        return isBlockElement(tagName)
          ? renderBlockChildren(node, context)
          : renderInlineChildren(node);
    }
  }

  function renderBlockChildren(node, context = {}) {
    return getChildNodes(node)
      .map((child) => convertNodeToMarkdown(child, context))
      .join("");
  }

  function renderInlineChildren(node) {
    const children = getChildNodes(node);
    if (!children.length) return normalizeTextNode(node.textContent || "");

    return children
      .map((child) => convertNodeToMarkdown(child))
      .join("")
      .replace(/[ \t]{2,}/g, " ");
  }

  function renderParagraph(node) {
    const text = renderInlineChildren(node).trim();
    return text ? `\n\n${text}\n\n` : "";
  }

  function renderLink(node) {
    const href = node.href || node.getAttribute("href") || "";
    const text = renderInlineChildren(node).trim() || href;
    return href ? `[${text}](${href})` : text;
  }

  function renderImage(node) {
    const src = node.currentSrc || node.src || node.getAttribute("src") || "";
    if (!src) return "";
    const alt = normalizeInlineText(node.alt || node.getAttribute("alt") || "");
    return `![${alt}](${src})`;
  }

  function renderInlineCode(text) {
    const trimmed = normalizeInlineText(text);
    if (!trimmed) return "";
    const fence = trimmed.includes("`") ? "``" : "`";
    return `${fence}${trimmed}${fence}`;
  }

  function renderCodeBlock(node) {
    const code = (node.textContent || "").replace(/\n+$/g, "");
    return code ? `\n\n\`\`\`\n${code}\n\`\`\`\n\n` : "";
  }

  function wrapInline(node, marker) {
    const text = renderInlineChildren(node).trim();
    return text ? `${marker}${text}${marker}` : "";
  }

  function renderBlockquote(node, context) {
    const text = normalizeMarkdown(renderBlockChildren(node, context));
    if (!text) return "";
    return `\n\n${text.split("\n").map((line) => `> ${line}`).join("\n")}\n\n`;
  }

  function renderList(node, isOrdered, context = {}) {
    const depth = context.depth || 0;
    const items = getChildNodes(node).filter((child) => {
      return child.nodeType === Node.ELEMENT_NODE && child.tagName.toLowerCase() === "li";
    });

    const lines = items.map((item, index) => {
      const marker = isOrdered ? `${index + 1}.` : "-";
      const indent = "  ".repeat(depth);
      const text = renderInlineChildren(item).trim();
      const nestedLists = getChildNodes(item)
        .filter((child) => {
          if (child.nodeType !== Node.ELEMENT_NODE) return false;
          const tag = child.tagName.toLowerCase();
          return tag === "ul" || tag === "ol";
        })
        .map((child) => convertNodeToMarkdown(child, { depth: depth + 1 }).trim())
        .filter(Boolean)
        .join("\n");

      return nestedLists
        ? `${indent}${marker} ${text}\n${nestedLists}`
        : `${indent}${marker} ${text}`;
    });

    return lines.length ? `\n\n${lines.join("\n")}\n\n` : "";
  }

  function renderTable(node) {
    const rows = findDescendantsByTag(node, "tr");
    if (!rows.length) return "";

    const tableRows = rows
      .map((row) => findTableCells(row).map((cell) => escapeTableCell(renderInlineChildren(cell).trim())))
      .filter((cells) => cells.length > 0);

    if (!tableRows.length) return "";

    const columnCount = Math.max(...tableRows.map((cells) => cells.length));
    const normalizedRows = tableRows.map((cells) => {
      return Array.from({ length: columnCount }, (_value, index) => cells[index] || "");
    });
    const header = normalizedRows[0];
    const divider = header.map(() => "---");
    const bodyRows = normalizedRows.slice(1);
    const lines = [header, divider, ...bodyRows].map((cells) => `| ${cells.join(" | ")} |`);

    return `\n\n${lines.join("\n")}\n\n`;
  }

  function findTableCells(row) {
    return getChildNodes(row).filter((child) => {
      if (child.nodeType !== Node.ELEMENT_NODE) return false;
      const tag = child.tagName.toLowerCase();
      return tag === "td" || tag === "th";
    });
  }

  function findDescendantsByTag(node, tagName) {
    const matches = [];
    getChildNodes(node).forEach((child) => {
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      if (child.tagName.toLowerCase() === tagName) matches.push(child);
      matches.push(...findDescendantsByTag(child, tagName));
    });
    return matches;
  }

  function shouldSkipElement(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;

    const tagName = node.tagName.toLowerCase();
    if (
      [
        "aside",
        "button",
        "canvas",
        "dialog",
        "footer",
        "form",
        "iframe",
        "input",
        "menu",
        "nav",
        "noscript",
        "select",
        "script",
        "style",
        "svg",
        "textarea"
      ].includes(tagName)
    ) {
      return true;
    }

    if (node.hidden || node.getAttribute("aria-hidden") === "true") return true;
    if (isNoisyElement(node)) return true;

    const style = window.getComputedStyle(node);
    return style.display === "none" || style.visibility === "hidden";
  }

  function isNoisyElement(node) {
    const role = normalizeInlineText(node.getAttribute("role") || "").toLowerCase();
    if (["banner", "complementary", "contentinfo", "navigation", "search"].includes(role)) {
      return true;
    }

    const signature = [
      node.id || "",
      node.className || "",
      node.getAttribute("data-testid") || "",
      node.getAttribute("aria-label") || ""
    ].join(" ").toLowerCase();

    return /(^|[\s_-])(ad|ads|advertisement|breadcrumb|cookie|consent|footer|menu|modal|nav|newsletter|popup|promo|recommend|related|share|sidebar|social|sponsor|subscribe)([\s_-]|$)/.test(signature);
  }

  function getChildNodes(node) {
    return Array.from(node.childNodes || node.children || []);
  }

  function isBlockElement(tagName) {
    return [
      "address",
      "article",
      "aside",
      "blockquote",
      "dd",
      "details",
      "div",
      "dl",
      "dt",
      "figcaption",
      "figure",
      "footer",
      "header",
      "li",
      "main",
      "p",
      "pre",
      "section",
      "table"
    ].includes(tagName);
  }

  function escapeTableCell(text) {
    return text.replace(/\|/g, "\\|").replace(/\n+/g, " ");
  }

  function normalizeTextNode(text) {
    return String(text || "").replace(/\s+/g, " ");
  }

  function normalizeInlineText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function normalizeMarkdown(markdown) {
    return String(markdown || "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }
}

// ------------------------------
// Testable Markdown Helpers
// ------------------------------
function convertNodeToMarkdownForTest(node, context = {}) {
  const NodeRef = typeof Node === "undefined"
    ? { TEXT_NODE: 3, ELEMENT_NODE: 1 }
    : Node;

  if (!node) return "";

  if (node.nodeType === NodeRef.TEXT_NODE) {
    return normalizeTextNodeForTest(node.textContent || "");
  }

  if (node.nodeType !== NodeRef.ELEMENT_NODE || shouldSkipElementForTest(node)) {
    return "";
  }

  const tagName = node.tagName.toLowerCase();

  if (/^h[1-6]$/.test(tagName)) {
    const level = Number(tagName.slice(1));
    const text = renderInlineChildrenForTest(node).trim();
    return text ? `\n\n${"#".repeat(level)} ${text}\n\n` : "";
  }

  switch (tagName) {
    case "a": {
      const href = node.href || getAttributeForTest(node, "href") || "";
      const text = renderInlineChildrenForTest(node).trim() || href;
      return href ? `[${text}](${href})` : text;
    }
    case "article":
    case "body":
    case "div":
    case "main":
    case "section":
      return renderBlockChildrenForTest(node, context);
    case "blockquote": {
      const text = normalizeMarkdownForTest(renderBlockChildrenForTest(node, context));
      if (!text) return "";
      return `\n\n${text.split("\n").map((line) => `> ${line}`).join("\n")}\n\n`;
    }
    case "code":
      return renderInlineCodeForTest(node.textContent || "");
    case "li":
      return renderInlineChildrenForTest(node).trim();
    case "ol":
    case "ul":
      return renderListForTest(node, tagName === "ol", context);
    case "p": {
      const text = renderInlineChildrenForTest(node).trim();
      return text ? `\n\n${text}\n\n` : "";
    }
    case "pre": {
      const code = (node.textContent || "").replace(/\n+$/g, "");
      return code ? `\n\n\`\`\`\n${code}\n\`\`\`\n\n` : "";
    }
    case "table":
      return renderTableForTest(node);
    default:
      return renderBlockChildrenForTest(node, context) || renderInlineChildrenForTest(node);
  }
}

function renderBlockChildrenForTest(node, context = {}) {
  return getChildNodesForTest(node)
    .map((child) => convertNodeToMarkdownForTest(child, context))
    .join("");
}

function renderInlineChildrenForTest(node) {
  const children = getChildNodesForTest(node);
  if (!children.length) return normalizeTextNodeForTest(node.textContent || "");

  return children
    .map((child) => convertNodeToMarkdownForTest(child))
    .join("")
    .replace(/[ \t]{2,}/g, " ");
}

function renderInlineCodeForTest(text) {
  const trimmed = normalizeInlineTextForTest(text);
  if (!trimmed) return "";
  const fence = trimmed.includes("`") ? "``" : "`";
  return `${fence}${trimmed}${fence}`;
}

function renderListForTest(node, isOrdered, context = {}) {
  const depth = context.depth || 0;
  const items = getChildNodesForTest(node).filter((child) => {
    return child.nodeType === 1 && child.tagName.toLowerCase() === "li";
  });

  const lines = items.map((item, index) => {
    const marker = isOrdered ? `${index + 1}.` : "-";
    const indent = "  ".repeat(depth);
    const text = renderInlineChildrenForTest(item).trim();
    return `${indent}${marker} ${text}`;
  });

  return lines.length ? `\n\n${lines.join("\n")}\n\n` : "";
}

function renderTableForTest(node) {
  const rows = findDescendantsByTagForTest(node, "tr");
  if (!rows.length) return "";

  const tableRows = rows
    .map((row) => {
      return getChildNodesForTest(row)
        .filter((cell) => {
          if (cell.nodeType !== 1) return false;
          const tag = cell.tagName.toLowerCase();
          return tag === "td" || tag === "th";
        })
        .map((cell) => renderInlineChildrenForTest(cell).trim().replace(/\|/g, "\\|"));
    })
    .filter((cells) => cells.length > 0);

  if (!tableRows.length) return "";

  const columnCount = Math.max(...tableRows.map((cells) => cells.length));
  const normalizedRows = tableRows.map((cells) => {
    return Array.from({ length: columnCount }, (_value, index) => cells[index] || "");
  });
  const header = normalizedRows[0];
  const divider = header.map(() => "---");
  const bodyRows = normalizedRows.slice(1);
  const lines = [header, divider, ...bodyRows].map((cells) => `| ${cells.join(" | ")} |`);

  return `\n\n${lines.join("\n")}\n\n`;
}

function findDescendantsByTagForTest(node, tagName) {
  const matches = [];
  getChildNodesForTest(node).forEach((child) => {
    if (child.nodeType !== 1) return;
    if (child.tagName.toLowerCase() === tagName) matches.push(child);
    matches.push(...findDescendantsByTagForTest(child, tagName));
  });
  return matches;
}

function shouldSkipElementForTest(node) {
  if (!node || node.nodeType !== 1) return false;
  const tagName = node.tagName.toLowerCase();
  if (
    [
      "aside",
      "button",
      "canvas",
      "dialog",
      "footer",
      "form",
      "iframe",
      "input",
      "menu",
      "nav",
      "noscript",
      "select",
      "script",
      "style",
      "svg",
      "textarea"
    ].includes(tagName)
  ) {
    return true;
  }

  if (getAttributeForTest(node, "aria-hidden") === "true") return true;
  if (isNoisyElementForTest(node)) return true;

  return false;
}

function isNoisyElementForTest(node) {
  const role = normalizeInlineTextForTest(getAttributeForTest(node, "role")).toLowerCase();
  if (["banner", "complementary", "contentinfo", "navigation", "search"].includes(role)) {
    return true;
  }

  const signature = [
    node.id || "",
    node.className || "",
    getAttributeForTest(node, "data-testid"),
    getAttributeForTest(node, "aria-label")
  ].join(" ").toLowerCase();

  return /(^|[\s_-])(ad|ads|advertisement|breadcrumb|cookie|consent|footer|menu|modal|nav|newsletter|popup|promo|recommend|related|share|sidebar|social|sponsor|subscribe)([\s_-]|$)/.test(signature);
}

function getChildNodesForTest(node) {
  return Array.from(node.childNodes || node.children || []);
}

function getAttributeForTest(node, name) {
  return typeof node.getAttribute === "function" ? node.getAttribute(name) : "";
}

function normalizeTextNodeForTest(text) {
  return String(text || "").replace(/\s+/g, " ");
}

function normalizeInlineTextForTest(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function normalizeMarkdownForTest(markdown) {
  return String(markdown || "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    convertNodeToMarkdownForTest,
    normalizeMarkdownForTest
  };
}
