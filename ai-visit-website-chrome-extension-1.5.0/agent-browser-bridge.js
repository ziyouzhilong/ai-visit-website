(function exposeAgentBrowserBridge(root, factory) {
  const api = factory();
  root.AgentBrowserBridge = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const DEFAULT_PORT = 32145;
  const CONFIG_DEFAULTS = {
    agentBridgeEnabled: false,
    agentBridgePort: DEFAULT_PORT,
    agentBridgeToken: "",
    agentBridgeAllowedOrigins: []
  };
  let running = false;
  let stopRequested = false;

  function normalizeAllowedOrigins(values) {
    const origins = [];
    const seen = new Set();
    const candidates = Array.isArray(values)
      ? values
      : String(values || "").split(/[\n,]+/);
    candidates.forEach((value) => {
      const text = String(value || "").trim();
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

  function isOriginAllowed(url, allowedOrigins) {
    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol)) return false;
      return normalizeAllowedOrigins(allowedOrigins).includes(parsed.origin.toLowerCase());
    } catch (_error) {
      return false;
    }
  }

  function buildBridgeEndpoint(port) {
    const parsed = Number.parseInt(port, 10);
    const safePort = Number.isInteger(parsed) && parsed >= 1024 && parsed <= 65535
      ? parsed
      : DEFAULT_PORT;
    return `http://127.0.0.1:${safePort}`;
  }

  function failureResult(task, code, message, retryable = false) {
    return {
      success: false,
      original_url: String(task?.url || ""),
      final_url: null,
      title: null,
      published_at: null,
      author: null,
      markdown: null,
      content_hash: null,
      adapter: "chrome-extension",
      elapsed_ms: 0,
      status_code: null,
      paragraph_count: 0,
      article_text_length: 0,
      selector_strategy: null,
      failure: { code, message, retryable }
    };
  }

  function readStorage(chromeApi) {
    return new Promise((resolve) => {
      chromeApi.storage.local.get(CONFIG_DEFAULTS, (stored) => {
        resolve({
          enabled: stored.agentBridgeEnabled === true,
          port: Number(stored.agentBridgePort) || DEFAULT_PORT,
          token: String(stored.agentBridgeToken || "").trim(),
          allowedOrigins: normalizeAllowedOrigins(stored.agentBridgeAllowedOrigins)
        });
      });
    });
  }

  async function bridgeFetch(endpoint, token, path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 30000);
    try {
      const response = await fetch(`${endpoint}${path}`, {
        method: options.method || "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal
      });
      if (response.status === 204) return { status: 204, payload: null };
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(`bridge_http_${response.status}:${payload.error || "request_failed"}`);
      }
      return { status: response.status, payload };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function completeTask(config, task, result) {
    await bridgeFetch(
      buildBridgeEndpoint(config.port),
      config.token,
      `/v1/extension/tasks/${encodeURIComponent(task.requestId)}/complete`,
      {
        method: "POST",
        body: { result },
        timeoutMs: 10000
      }
    );
  }

  async function start(options = {}) {
    if (running) return;
    const chromeApi = options.chromeApi || globalThis.chrome;
    const readPage = options.readPage || globalThis.executeAgentBrowserRead;
    if (!chromeApi?.storage?.local || typeof readPage !== "function") return;

    running = true;
    stopRequested = false;
    try {
      while (!stopRequested) {
        const config = await readStorage(chromeApi);
        if (!config.enabled || !config.token || !config.allowedOrigins.length) break;
        try {
          const response = await bridgeFetch(
            buildBridgeEndpoint(config.port),
            config.token,
            "/v1/extension/tasks/claim",
            {
              method: "POST",
              body: {
                waitSeconds: 20,
                extensionVersion: chromeApi.runtime.getManifest().version
              },
              timeoutMs: 26000
            }
          );
          if (response.status === 204 || !response.payload) continue;
          const task = response.payload;
          if (!isOriginAllowed(task.url, config.allowedOrigins)) {
            await completeTask(
              config,
              task,
              failureResult(
                task,
                "domain_not_authorized",
                "The requested website origin is not authorized in the Chrome extension."
              )
            );
            continue;
          }
          let result;
          try {
            result = await readPage(task, { allowedOrigins: config.allowedOrigins });
          } catch (_error) {
            result = failureResult(
              task,
              "browser_execution_failed",
              "Chrome could not complete the read request.",
              true
            );
          }
          await completeTask(config, task, result);
        } catch (_error) {
          if (!stopRequested) await new Promise((resolve) => setTimeout(resolve, 3000));
        }
      }
    } finally {
      running = false;
    }
  }

  function stop() {
    stopRequested = true;
  }

  function restart(options = {}) {
    stop();
    const resume = () => {
      if (running) {
        setTimeout(resume, 250);
        return;
      }
      start(options);
    };
    resume();
  }

  return {
    CONFIG_DEFAULTS,
    DEFAULT_PORT,
    buildBridgeEndpoint,
    failureResult,
    isOriginAllowed,
    normalizeAllowedOrigins,
    restart,
    start,
    stop
  };
});
