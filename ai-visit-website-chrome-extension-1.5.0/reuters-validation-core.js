(function exposeReutersValidationCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.ReutersValidationCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const REUTERS_ORIGIN = "https://www.reuters.com";
  const BUSINESS_PATH_PREFIX = "/business/";

  function decodeXml(value) {
    return String(value || "")
      .replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/, "$1")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;|&apos;/g, "'")
      .trim();
  }

  function readTag(block, tagName) {
    const escaped = tagName.replace(":", "\\:");
    const match = block.match(
      new RegExp(`<${escaped}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${escaped}>`, "i")
    );
    return match ? decodeXml(match[1]) : "";
  }

  function parseReutersNewsSitemap(xmlText, options = {}) {
    const limit = Math.max(1, Math.min(Number(options.limit) || 10, 100));
    const entriesByUrl = new Map();
    const blocks = String(xmlText || "").match(/<url(?:\s[^>]*)?>[\s\S]*?<\/url>/gi) || [];

    blocks.forEach((block) => {
      const rawUrl = readTag(block, "loc");
      if (!rawUrl) return;

      let parsed;
      try {
        parsed = new URL(rawUrl);
      } catch (_error) {
        return;
      }

      if (
        parsed.origin !== REUTERS_ORIGIN ||
        !parsed.pathname.startsWith(BUSINESS_PATH_PREFIX)
      ) {
        return;
      }

      const publishedAt =
        readTag(block, "news:publication_date") || readTag(block, "lastmod") || null;
      const candidate = {
        url: parsed.href,
        title: readTag(block, "news:title") || parsed.pathname,
        publishedAt
      };
      const existing = entriesByUrl.get(candidate.url);
      if (!existing || toTimestamp(candidate.publishedAt) > toTimestamp(existing.publishedAt)) {
        entriesByUrl.set(candidate.url, candidate);
      }
    });

    return Array.from(entriesByUrl.values())
      .sort((a, b) => toTimestamp(b.publishedAt) - toTimestamp(a.publishedAt))
      .slice(0, limit);
  }

  function mergeReutersEntries(entryGroups, limit = 10) {
    const merged = new Map();
    entryGroups.flat().forEach((entry) => {
      if (!entry?.url) return;
      const existing = merged.get(entry.url);
      if (!existing || toTimestamp(entry.publishedAt) > toTimestamp(existing.publishedAt)) {
        merged.set(entry.url, entry);
      }
    });

    return Array.from(merged.values())
      .sort((a, b) => toTimestamp(b.publishedAt) - toTimestamp(a.publishedAt))
      .slice(0, Math.max(1, Math.min(Number(limit) || 10, 100)));
  }

  function classifyReutersCapture({ probe = {}, capture = {}, error = null } = {}) {
    if (error) {
      return { status: "extension_error", readable: false, stop: false };
    }

    if (!isReutersArticleUrl(probe.finalUrl)) {
      return { status: "unexpected_redirect", readable: false, stop: true };
    }
    if (probe.challengeDetected) {
      return { status: "bot_challenge", readable: false, stop: true };
    }
    if (probe.accessDeniedDetected) {
      return { status: "access_denied", readable: false, stop: true };
    }

    const articleTextLength =
      Number(capture.articleTextLength) || Number(probe.articleTextLength) || 0;
    const paragraphCount = Number(capture.paragraphCount) || Number(probe.paragraphCount) || 0;
    const markdownLength = String(capture.markdown || "").length;

    if (probe.loginRequiredDetected && articleTextLength < 500) {
      return { status: "login_required", readable: false, stop: true };
    }
    if (probe.paywallDetected && articleTextLength < 500) {
      return { status: "paywall", readable: false, stop: true };
    }
    if (capture.failure?.code === "empty_article") {
      return { status: "empty_article", readable: false, stop: false };
    }
    if (
      (articleTextLength >= 500 && paragraphCount >= 3) ||
      (articleTextLength >= 300 && paragraphCount >= 2 && markdownLength >= 500)
    ) {
      return { status: "readable", readable: true, stop: false };
    }
    if (articleTextLength >= 150 || paragraphCount >= 2) {
      return { status: "partial", readable: false, stop: false };
    }
    return { status: "empty_article", readable: false, stop: false };
  }

  function isReutersArticleUrl(value) {
    try {
      const parsed = new URL(value);
      return parsed.origin === REUTERS_ORIGIN && parsed.pathname.startsWith(BUSINESS_PATH_PREFIX);
    } catch (_error) {
      return false;
    }
  }

  function toTimestamp(value) {
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? parsed : 0;
  }

  return {
    BUSINESS_PATH_PREFIX,
    REUTERS_ORIGIN,
    classifyReutersCapture,
    decodeXml,
    isReutersArticleUrl,
    mergeReutersEntries,
    parseReutersNewsSitemap
  };
});
