(function exposeSnippetClipboard(root) {
  function getSnippetClipboardText(snippet) {
    return String(snippet?.text ?? "");
  }

  async function copySnippetToClipboard(snippet, clipboard = root.navigator?.clipboard) {
    if (!clipboard || typeof clipboard.writeText !== "function") {
      throw new Error("Clipboard API is unavailable.");
    }

    const text = getSnippetClipboardText(snippet);
    await clipboard.writeText(text);
    return text;
  }

  const api = { copySnippetToClipboard, getSnippetClipboardText };
  root.SnippetClipboard = api;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
