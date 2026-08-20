(function exposeReutersArticleExtractor(root, factory) {
  const api = factory();
  root.injectedExtractReutersArticle = api.injectedExtractReutersArticle;
  root.ReutersArticleExtractor = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  function sanitizeReutersText(value) {
    return String(value || "")
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
      .replace(/\s*,?\s*opens new tab\b/gi, "")
      .replace(/[ \t]+([,.;:!?])/g, "$1")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\s*\n\s*/g, "\n")
      .trim();
  }

  function isReutersNoiseText(value) {
    const text = sanitizeReutersText(value);
    if (!text) return true;
    return [
      /^advertisement$/i,
      /^already a subscriber\??/i,
      /^editing by\b/i,
      /^our standards:/i,
      /^purchase licensing rights\b/i,
      /^read next\b/i,
      /^reporting by\b/i,
      /^sign up here\b/i,
      /^subscribe\b/i,
      /^thomson reuters\b/i,
      /^©\s*\d{4}/i,
      /\bthe reuters .{0,120} newsletter\b/i,
      /\bsign up for .{0,100} newsletter\b/i
    ].some((pattern) => pattern.test(text));
  }

  function buildReutersMarkdown({ title, sourceUrl, publishedAt, author, bodyMarkdown }) {
    const cleanTitle = sanitizeReutersText(title).replace(/\s*\|\s*Reuters\s*$/i, "");
    const lines = [`# ${cleanTitle || "Untitled Reuters article"}`];
    if (sourceUrl) lines.push(`Source: ${sourceUrl}`);
    if (publishedAt) lines.push(`Published: ${sanitizeReutersText(publishedAt)}`);
    if (author) lines.push(`Author: ${sanitizeReutersText(author)}`);
    lines.push("", String(bodyMarkdown || "").trim());
    return lines.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  async function injectedExtractReutersArticle() {
    const cleanText = (value) => String(value || "")
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
      .replace(/\s*,?\s*opens new tab\b/gi, "")
      .replace(/[ \t]+([,.;:!?])/g, "$1")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\s*\n\s*/g, "\n")
      .trim();

    const isNoiseText = (value) => {
      const text = cleanText(value);
      if (!text) return true;
      return [
        /^advertisement$/i,
        /^already a subscriber\??/i,
        /^editing by\b/i,
        /^our standards:/i,
        /^purchase licensing rights\b/i,
        /^read next\b/i,
        /^reporting by\b/i,
        /^sign up here\b/i,
        /^subscribe\b/i,
        /^thomson reuters\b/i,
        /^©\s*\d{4}/i,
        /\bthe reuters .{0,120} newsletter\b/i,
        /\bsign up for .{0,100} newsletter\b/i
      ].some((pattern) => pattern.test(text));
    };

    const noiseSignaturePattern =
      /(^|[\s_-])(ad|advertisement|author-bio|cookie|footer|legal|menu|newsletter|paywall|promo|recommend|related|share|sidebar|social|sponsor|subscribe|toolbar)([\s_-]|$)/i;
    const hiddenSignaturePattern =
      /(^|[\s_-])(a11y|assistive|screen-reader|sr-only|visually-hidden)([\s_-]|$)/i;

    const elementSignature = (element) => {
      if (!element || element.nodeType !== Node.ELEMENT_NODE) return "";
      return [
        element.id || "",
        typeof element.className === "string" ? element.className : "",
        element.getAttribute("data-testid") || "",
        element.getAttribute("aria-label") || "",
        element.getAttribute("role") || ""
      ].join(" ").toLowerCase();
    };

    const hasNoiseAncestor = (element) => {
      let current = element;
      for (let depth = 0; current && depth < 7; depth += 1) {
        if (noiseSignaturePattern.test(elementSignature(current))) return true;
        current = current.parentElement;
      }
      return false;
    };

    const isHiddenElement = (element) => {
      if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
      if (element.hidden || element.getAttribute("aria-hidden") === "true") return true;
      if (hiddenSignaturePattern.test(elementSignature(element))) return true;
      const style = getComputedStyle(element);
      return style.display === "none" || style.visibility === "hidden";
    };

    const escapeMarkdownText = (value) => String(value || "")
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
      .replace(/\s*,?\s*opens new tab\b/gi, "")
      .replace(/[\r\n\t ]+/g, " ")
      .replace(/\\/g, "\\\\")
      .replace(/\[/g, "\\[")
      .replace(/\]/g, "\\]");

    const renderInline = (node) => {
      if (!node) return "";
      if (node.nodeType === Node.TEXT_NODE) return escapeMarkdownText(node.textContent || "");
      if (node.nodeType !== Node.ELEMENT_NODE || isHiddenElement(node)) return "";

      const tag = node.tagName.toLowerCase();
      if (["button", "script", "style", "svg", "noscript", "form"].includes(tag)) return "";
      if (hasNoiseAncestor(node) && node !== node.closest("[data-testid^='paragraph-']")) return "";
      if (tag === "br") return "\n";

      const children = Array.from(node.childNodes || []).map(renderInline).join("");
      const text = cleanText(children);
      if (!text) return "";

      if (tag === "a") {
        let href = "";
        try {
          const parsed = new URL(node.href, location.href);
          if (["http:", "https:"].includes(parsed.protocol)) href = parsed.href;
        } catch (_error) {
          href = "";
        }
        return href ? `[${text}](${href})` : text;
      }
      if (["strong", "b"].includes(tag)) return `**${text}**`;
      if (["em", "i"].includes(tag)) return `*${text}*`;
      if (tag === "code") return `\`${text.replace(/`/g, "\\`")}\``;
      return children;
    };

    const textForNode = (node) => cleanText(node?.innerText || node?.textContent || "");
    const isLeafBlock = (node) => {
      const meaningfulChild = Array.from(node.children || []).find((child) => {
        if (!/^(DIV|P|SECTION)$/.test(child.tagName)) return false;
        return textForNode(child).length >= 20;
      });
      return !meaningfulChild;
    };

    const collectCandidates = (selectors, requireLeaf = false) => {
      const candidates = [];
      const seenNodes = new Set();
      let rejectedNoise = 0;

      selectors.forEach((selector) => {
        document.querySelectorAll(selector).forEach((node) => {
          if (seenNodes.has(node)) return;
          seenNodes.add(node);
          const rawText = textForNode(node);
          if (rawText.length < 20) return;
          if (
            isHiddenElement(node) ||
            hasNoiseAncestor(node) ||
            isNoiseText(rawText) ||
            (requireLeaf && !isLeafBlock(node))
          ) {
            rejectedNoise += 1;
            return;
          }
          candidates.push(node);
        });
      });
      return { candidates, rejectedNoise };
    };

    const strategies = [
      {
        name: "data-testid-paragraph",
        selectors: ["article [data-testid^='paragraph-']", "main [data-testid^='paragraph-']"],
        requireLeaf: false
      },
      {
        name: "itemprop-article-body",
        selectors: ["[itemprop='articleBody'] p", "[itemprop='articleBody'] div"],
        requireLeaf: true
      },
      {
        name: "article-paragraph",
        selectors: ["article p"],
        requireLeaf: false
      },
      {
        name: "article-leaf-div",
        selectors: ["article div"],
        requireLeaf: true
      }
    ];

    let selected = [];
    let selectorStrategy = "none";
    let removedNoiseCount = 0;
    for (const strategy of strategies) {
      const collected = collectCandidates(strategy.selectors, strategy.requireLeaf);
      removedNoiseCount += collected.rejectedNoise;
      if (collected.candidates.length >= 2 || (collected.candidates.length === 1 && textForNode(collected.candidates[0]).length >= 300)) {
        selected = collected.candidates;
        selectorStrategy = strategy.name;
        break;
      }
    }

    selected.sort((a, b) => {
      if (a === b) return 0;
      const position = a.compareDocumentPosition(b);
      return position & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });

    const seenParagraphs = new Set();
    const paragraphs = [];
    selected.forEach((node) => {
      const plainText = textForNode(node);
      if (isNoiseText(plainText)) {
        removedNoiseCount += 1;
        return;
      }
      const key = plainText.toLowerCase();
      if (seenParagraphs.has(key)) return;
      seenParagraphs.add(key);
      const rendered = cleanText(renderInline(node)) || escapeMarkdownText(plainText);
      if (rendered.length >= 20) paragraphs.push(rendered);
    });

    const readMeta = (...selectors) => {
      for (const selector of selectors) {
        const value = document.querySelector(selector)?.getAttribute("content");
        if (value && value.trim()) return cleanText(value);
      }
      return null;
    };

    const findArticleJsonLd = () => {
      const visit = (value) => {
        if (!value || typeof value !== "object") return null;
        if (Array.isArray(value)) {
          for (const item of value) {
            const found = visit(item);
            if (found) return found;
          }
          return null;
        }
        const type = value["@type"];
        if (["Article", "NewsArticle", "ReportageNewsArticle"].includes(type)) return value;
        return visit(value["@graph"]);
      };
      for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
        try {
          const found = visit(JSON.parse(script.textContent || "null"));
          if (found) return found;
        } catch (_error) {
          continue;
        }
      }
      return null;
    };

    const jsonLd = findArticleJsonLd();
    const rawTitle =
      cleanText(document.querySelector("h1")?.innerText) ||
      readMeta('meta[property="og:title"]') ||
      cleanText(jsonLd?.headline) ||
      cleanText(document.title);
    const title = rawTitle.replace(/\s*\|\s*Reuters\s*$/i, "");
    const publishedAt =
      readMeta('meta[property="article:published_time"]', 'meta[name="date"]') ||
      cleanText(jsonLd?.datePublished) ||
      null;
    const jsonLdAuthor = Array.isArray(jsonLd?.author) ? jsonLd.author[0] : jsonLd?.author;
    const author =
      readMeta('meta[name="author"]', 'meta[property="article:author"]') ||
      cleanText(typeof jsonLdAuthor === "string" ? jsonLdAuthor : jsonLdAuthor?.name) ||
      null;
    const bodyMarkdown = paragraphs.join("\n\n").trim();
    const articleTextLength = cleanText(paragraphs.join(" ")).length;

    if (!bodyMarkdown || articleTextLength < 100) {
      return {
        success: false,
        adapter: "chrome-reuters-dom",
        finalUrl: location.href,
        title,
        publishedAt,
        author,
        selectorStrategy,
        removedNoiseCount,
        paragraphCount: paragraphs.length,
        articleTextLength,
        failure: {
          code: "empty_article",
          message: "Reuters article paragraphs were not found in the visible DOM.",
          retryable: false
        }
      };
    }

    const metadataLines = [`# ${title || "Untitled Reuters article"}`, `Source: ${location.href}`];
    if (publishedAt) metadataLines.push(`Published: ${publishedAt}`);
    if (author) metadataLines.push(`Author: ${author}`);
    const markdown = `${metadataLines.join("\n\n")}\n\n${bodyMarkdown}`.replace(/\n{3,}/g, "\n\n").trim();
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(markdown));
    const contentHash = `sha256:${Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;

    return {
      success: true,
      adapter: "chrome-reuters-dom",
      finalUrl: location.href,
      title,
      publishedAt,
      author,
      markdown,
      bodyMarkdown,
      contentHash,
      selectorStrategy,
      removedNoiseCount,
      paragraphCount: paragraphs.length,
      articleTextLength,
      excerpt: cleanText(paragraphs.join("\n\n")).slice(0, 280),
      failure: null
    };
  }

  return {
    buildReutersMarkdown,
    injectedExtractReutersArticle,
    isReutersNoiseText,
    sanitizeReutersText
  };
});
