const {
  classifyReutersCapture,
  mergeReutersEntries,
  parseReutersNewsSitemap
} = globalThis.ReutersValidationCore;

const NEWS_SITEMAP_BASE =
  "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml";
const BLOCKING_STATUSES = new Set([
  "access_denied",
  "bot_challenge",
  "login_required",
  "paywall",
  "unexpected_redirect"
]);

const state = {
  running: false,
  stopRequested: false,
  validationTabId: null,
  workerTabId: null,
  startedAt: null,
  completedAt: null,
  results: []
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  Object.assign(elements, {
    articleCount: document.getElementById("articleCount"),
    attemptedCount: document.getElementById("attemptedCount"),
    blockedCount: document.getElementById("blockedCount"),
    consentCheckbox: document.getElementById("consentCheckbox"),
    exportBtn: document.getElementById("exportBtn"),
    openReutersBtn: document.getElementById("openReutersBtn"),
    partialCount: document.getElementById("partialCount"),
    readableCount: document.getElementById("readableCount"),
    resultsBody: document.getElementById("resultsBody"),
    startBtn: document.getElementById("startBtn"),
    statusText: document.getElementById("statusText"),
    stopBtn: document.getElementById("stopBtn")
  });

  elements.openReutersBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: "https://www.reuters.com/business/", active: true });
  });
  elements.startBtn.addEventListener("click", startValidation);
  elements.stopBtn.addEventListener("click", () => {
    state.stopRequested = true;
    setStatus("正在停止；当前页面读取结束后不会继续下一篇……");
  });
  elements.exportBtn.addEventListener("click", exportResults);

  restoreLastRun();
});

async function startValidation() {
  if (state.running) return;
  if (!elements.consentCheckbox.checked) {
    setStatus("请先确认本次 reuters.com 只读访问授权。");
    return;
  }

  const requestedCount = clampArticleCount(elements.articleCount.value);
  elements.articleCount.value = String(requestedCount);
  resetRunState();
  state.running = true;
  state.startedAt = new Date().toISOString();
  setControlsRunning(true);
  renderResults();

  try {
    const currentTab = await getCurrentTab();
    state.validationTabId = currentTab?.id || null;
    setStatus("正在从 Reuters 公开新闻 sitemap 获取最新 Business 文章……");
    const entries = await discoverLatestBusinessEntries(requestedCount);
    if (!entries.length) {
      throw new Error("Reuters sitemap 中没有找到 Business 文章。");
    }

    for (let index = 0; index < entries.length; index += 1) {
      if (state.stopRequested) break;
      const entry = entries[index];
      setStatus(`正在读取第 ${index + 1}/${entries.length} 篇：${entry.title}`);
      const result = await validateOneEntry(entry, index);
      state.results.push(result);
      renderResults();
      await persistRun();

      if (result.stop) {
        setStatus(
          `检测到 ${statusLabel(result.status)}，验证已停止。文章标签页保留供人工检查。`
        );
        break;
      }
      if (index < entries.length - 1 && !state.stopRequested) {
        await delay(1800);
      }
    }

    state.completedAt = new Date().toISOString();
    await persistRun();
    if (!state.results.some((result) => result.stop)) {
      await closeWorkerTab();
      await reactivateValidationTab();
      setStatus(
        state.stopRequested
          ? `已由用户停止，共完成 ${state.results.length} 篇。`
          : `验证完成，共检查 ${state.results.length} 篇。`
      );
    }
  } catch (error) {
    setStatus(`验证失败：${error.message || String(error)}`);
    await closeWorkerTab();
    await reactivateValidationTab();
  } finally {
    state.running = false;
    setControlsRunning(false);
    elements.exportBtn.disabled = state.results.length === 0;
  }
}

async function discoverLatestBusinessEntries(count) {
  const groups = [];
  for (const offset of [0, 100, 200]) {
    const url = offset ? `${NEWS_SITEMAP_BASE}&from=${offset}` : NEWS_SITEMAP_BASE;
    const response = await fetchWithTimeout(url, 20000);
    if (!response.ok) {
      throw new Error(`sitemap 返回 HTTP ${response.status}`);
    }
    const xml = await response.text();
    groups.push(parseReutersNewsSitemap(xml, { limit: 100 }));
    if (mergeReutersEntries(groups, count).length >= count) break;
  }
  return mergeReutersEntries(groups, count);
}

async function validateOneEntry(entry, index) {
  const startedAt = performance.now();
  let probe = null;
  let capture = null;
  let capturedError = null;

  try {
    if (!state.workerTabId) {
      const tab = await createTab(entry.url);
      state.workerTabId = tab.id;
      await waitForTabComplete(tab.id, entry.url, 45000);
    } else {
      await navigateTab(state.workerTabId, entry.url, 45000);
    }

    await delay(2200);
    probe = await runPageProbe(state.workerTabId);
    const captureResponse = await sendCaptureRequest(state.workerTabId);
    capture = captureResponse?.capture || null;
    if (!captureResponse?.success && captureResponse?.error !== "empty_article") {
      capturedError = captureResponse?.error || "capture_failed";
    }
  } catch (error) {
    capturedError = error.message || String(error);
  }

  const classification = classifyReutersCapture({
    probe: probe || {},
    capture: capture || {},
    error: capturedError
  });
  return {
    index: index + 1,
    sourceTitle: entry.title,
    publishedAt: entry.publishedAt,
    requestedUrl: entry.url,
    finalUrl: probe?.finalUrl || entry.url,
    pageTitle: capture?.title || probe?.title || null,
    status: classification.status,
    readable: classification.readable,
    stop: classification.stop,
    articleTextLength:
      Number(capture?.articleTextLength) || Number(probe?.articleTextLength) || 0,
    paragraphCount: Number(capture?.paragraphCount) || Number(probe?.paragraphCount) || 0,
    markdownLength: String(capture?.markdown || "").length,
    contentHash: capture?.contentHash || null,
    adapter: capture?.adapter || null,
    selectorStrategy: capture?.selectorStrategy || "none",
    removedNoiseCount: Number(capture?.removedNoiseCount) || 0,
    excerpt: String(capture?.excerpt || probe?.excerpt || "").slice(0, 280),
    elapsedMs: Math.round(performance.now() - startedAt),
    error: capturedError
  };
}

async function runPageProbe(tabId) {
  const results = await executeScript({
    target: { tabId },
    func: async () => {
      const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
      let previousHeight = 0;
      let stableRounds = 0;

      for (let step = 0; step < 7; step += 1) {
        const height = Math.max(document.body?.scrollHeight || 0, document.documentElement.scrollHeight || 0);
        window.scrollTo({ top: Math.min(height, (step + 1) * window.innerHeight * 0.9), behavior: "auto" });
        await wait(450);
        if (height === previousHeight) stableRounds += 1;
        else stableRounds = 0;
        previousHeight = height;
        if (stableRounds >= 2) break;
      }
      await wait(700);

      const selectors = [
        "article [data-testid^='paragraph-']",
        "main [data-testid^='paragraph-']",
        "[itemprop='articleBody'] p",
        "article p"
      ];
      const nodes = [];
      const seen = new Set();
      selectors.forEach((selector) => {
        document.querySelectorAll(selector).forEach((node) => {
          if (seen.has(node)) return;
          seen.add(node);
          const text = String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
          if (text.length >= 20) nodes.push({ node, text });
        });
      });

      const articleText = nodes.map((item) => item.text).join("\n\n");
      const bodyText = String(document.body?.innerText || "").replace(/\s+/g, " ").trim();
      const detectionText = bodyText.toLowerCase().slice(0, 30000);
      return {
        finalUrl: location.href,
        title: document.title,
        articleTextLength: articleText.length,
        paragraphCount: nodes.length,
        excerpt: articleText.slice(0, 280),
        challengeDetected:
          /captcha|verify you are human|are you a human|unusual traffic|datadome|press and hold|security check/.test(detectionText),
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

function renderResults() {
  elements.resultsBody.textContent = "";
  if (!state.results.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = "运行后将在这里显示结果。";
    row.appendChild(cell);
    elements.resultsBody.appendChild(row);
  } else {
    state.results.forEach((result) => elements.resultsBody.appendChild(createResultRow(result)));
  }

  elements.attemptedCount.textContent = String(state.results.length);
  elements.readableCount.textContent = String(
    state.results.filter((result) => result.status === "readable").length
  );
  elements.partialCount.textContent = String(
    state.results.filter((result) => ["partial", "empty_article"].includes(result.status)).length
  );
  elements.blockedCount.textContent = String(
    state.results.filter((result) => BLOCKING_STATUSES.has(result.status)).length
  );
}

function createResultRow(result) {
  const row = document.createElement("tr");
  row.appendChild(textCell(result.index));

  const statusCell = document.createElement("td");
  const pill = document.createElement("span");
  pill.className = `status-pill ${result.status}`;
  pill.textContent = statusLabel(result.status);
  statusCell.appendChild(pill);
  row.appendChild(statusCell);

  const articleCell = document.createElement("td");
  const link = document.createElement("a");
  link.className = "article-link";
  link.href = result.finalUrl || result.requestedUrl;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = result.pageTitle || result.sourceTitle || "Untitled";
  articleCell.appendChild(link);
  if (result.excerpt) {
    const excerpt = document.createElement("div");
    excerpt.className = "excerpt";
    excerpt.textContent = result.excerpt;
    articleCell.appendChild(excerpt);
  }
  row.appendChild(articleCell);
  row.appendChild(textCell(result.articleTextLength));
  row.appendChild(textCell(result.paragraphCount));
  row.appendChild(
    textCell(`${result.selectorStrategy || "none"} / ${result.removedNoiseCount || 0}`)
  );
  row.appendChild(textCell(`${(result.elapsedMs / 1000).toFixed(1)}s`));
  return row;
}

function statusLabel(status) {
  const labels = {
    readable: "正文可读",
    partial: "部分正文",
    empty_article: "正文为空",
    bot_challenge: "CAPTCHA/挑战",
    access_denied: "访问拒绝",
    login_required: "需要登录",
    paywall: "订阅限制",
    unexpected_redirect: "异常跳转",
    extension_error: "扩展错误"
  };
  return labels[status] || status;
}

function resetRunState() {
  state.stopRequested = false;
  state.workerTabId = null;
  state.startedAt = null;
  state.completedAt = null;
  state.results = [];
}

function setControlsRunning(running) {
  elements.startBtn.disabled = running;
  elements.stopBtn.disabled = !running;
  elements.articleCount.disabled = running;
  elements.consentCheckbox.disabled = running;
  elements.exportBtn.disabled = running || state.results.length === 0;
}

function setStatus(message) {
  elements.statusText.textContent = message;
}

function clampArticleCount(value) {
  return Math.max(1, Math.min(Number.parseInt(value, 10) || 10, 10));
}

function textCell(value) {
  const cell = document.createElement("td");
  cell.textContent = String(value);
  return cell;
}

function getCurrentTab() {
  return new Promise((resolve) => chrome.tabs.getCurrent(resolve));
}

function createTab(url) {
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

function navigateTab(tabId, url, timeoutMs) {
  return new Promise((resolve, reject) => {
    chrome.tabs.update(tabId, { url, active: true }, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message || "tab_navigation_failed"));
        return;
      }
      waitForTabComplete(tabId, url, timeoutMs).then(resolve, reject);
    });
  });
}

function waitForTabComplete(tabId, expectedUrl, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(new Error("page_load_timeout")), timeoutMs);

    const onUpdated = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId !== tabId || changeInfo.status !== "complete") return;
      finish(null, tab);
    };
    const onRemoved = (removedTabId) => {
      if (removedTabId === tabId) finish(new Error("validation_tab_closed"));
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
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) return;
      if (tab.status === "complete" && tab.url && tab.url !== "about:blank") {
        finish(null, tab);
      }
    });
  });
}

function executeScript(details) {
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

function sendCaptureRequest(tabId) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "extract-reuters-article", tabId }, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ success: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response);
    });
  });
}

async function closeWorkerTab() {
  if (!state.workerTabId) return;
  const tabId = state.workerTabId;
  state.workerTabId = null;
  await new Promise((resolve) => chrome.tabs.remove(tabId, () => resolve()));
}

async function reactivateValidationTab() {
  if (!state.validationTabId) return;
  await new Promise((resolve) => {
    chrome.tabs.update(state.validationTabId, { active: true }, () => resolve());
  });
}

function fetchWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, {
    cache: "no-store",
    credentials: "omit",
    signal: controller.signal
  }).finally(() => clearTimeout(timer));
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function persistRun() {
  const payload = buildExportPayload();
  await new Promise((resolve) => {
    chrome.storage.local.set({ reutersValidationLastRun: payload }, resolve);
  });
}

function restoreLastRun() {
  chrome.storage.local.get({ reutersValidationLastRun: null }, (store) => {
    const previous = store.reutersValidationLastRun;
    if (!previous?.results?.length) return;
    state.startedAt = previous.startedAt || null;
    state.completedAt = previous.completedAt || null;
    state.results = previous.results;
    renderResults();
    elements.exportBtn.disabled = false;
    setStatus(`已载入上次验证结果：${state.results.length} 篇。`);
  });
}

function buildExportPayload() {
  return {
    schemaVersion: 2,
    extensionVersion: chrome.runtime.getManifest().version,
    mode: "reuters-visible-browser-production-extraction-validation",
    startedAt: state.startedAt,
    completedAt: state.completedAt,
    fullArticleContentStored: false,
    articleContentReturnedTransiently: true,
    results: state.results
  };
}

function exportResults() {
  const blob = new Blob([JSON.stringify(buildExportPayload(), null, 2)], {
    type: "application/json"
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `reuters-browser-validation-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
