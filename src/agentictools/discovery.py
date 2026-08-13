from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import html
from lxml.html import HtmlElement

from agentictools.models import LinkEvidence


ARTICLE_PATH = re.compile(r"/(article|articles|story|stories|news|posts?)/", re.I)


def discover_links(
    document: str, base_url: str
) -> tuple[list[LinkEvidence], list[str], list[str], list[LinkEvidence]]:
    if not document.strip():
        return [], [], [], []
    try:
        root = html.fromstring(document, base_url=base_url)
    except (ValueError, TypeError):
        return [], [], [], []

    navigation = _links_from_nodes(root.xpath("//nav//a[@href]"), base_url, "navigation")
    feeds = _resource_links(
        root.xpath(
            "//link[@href and contains(translate(@rel, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz'), 'alternate') and "
            "(contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            "'rss') or contains(translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz'), 'atom'))]"
        ),
        base_url,
    )
    sitemaps = _resource_links(
        root.xpath(
            "//link[@href and contains(translate(@rel, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz'), 'sitemap')]"
        ),
        base_url,
    )

    all_internal = []
    origin_host = (urlsplit(base_url).hostname or "").lower()
    for node in root.xpath("//a[@href]"):
        target = _normalize_link(base_url, node.get("href"))
        if not target or (urlsplit(target).hostname or "").lower() != origin_host:
            continue
        anchor = _clean_text(node.text_content()) or target
        context_node = node.getparent()
        surrounding = _clean_text(context_node.text_content()) if context_node is not None else anchor
        inferred = _infer_type(node, target)
        all_internal.append(
            LinkEvidence(
                url=target,
                anchor_text=anchor,
                surrounding_text=surrounding[:500],
                inferred_type=inferred,
            )
        )

    return (
        _dedupe_evidence(navigation),
        _dedupe_strings(feeds),
        _dedupe_strings(sitemaps),
        _dedupe_evidence(all_internal),
    )


def _links_from_nodes(
    nodes: Iterable[HtmlElement], base_url: str, inferred_type: str
) -> list[LinkEvidence]:
    links = []
    for node in nodes:
        target = _normalize_link(base_url, node.get("href"))
        if not target:
            continue
        anchor = _clean_text(node.text_content()) or target
        parent = node.getparent()
        surrounding = _clean_text(parent.text_content()) if parent is not None else anchor
        links.append(
            LinkEvidence(
                url=target,
                anchor_text=anchor,
                surrounding_text=surrounding[:500],
                inferred_type=inferred_type,
            )
        )
    return links


def _resource_links(nodes: Iterable[HtmlElement], base_url: str) -> list[str]:
    return [
        target
        for node in nodes
        if (target := _normalize_link(base_url, node.get("href"))) is not None
    ]


def _normalize_link(base_url: str, href: str | None) -> str | None:
    if not href or href.strip().startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href.strip())
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _infer_type(node: HtmlElement, url: str) -> str:
    if any(parent.tag == "article" for parent in node.iterancestors()):
        return "article"
    if any(parent.tag == "nav" for parent in node.iterancestors()):
        return "navigation"
    if ARTICLE_PATH.search(urlsplit(url).path):
        return "article"
    return "link"


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _dedupe_evidence(values: Iterable[LinkEvidence]) -> list[LinkEvidence]:
    result = []
    seen = set()
    for value in values:
        if value.url in seen:
            continue
        seen.add(value.url)
        result.append(value)
    return result


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
