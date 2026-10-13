/** A run of release-note text. Notes come from GitHub, so only text and two marks survive. */
export type ReleaseNoteSpan = { text: string; strong?: true; code?: true };
export type ReleaseNoteBlock = { kind: "heading" | "item" | "paragraph"; level?: number; spans: ReleaseNoteSpan[] };
export type ReleaseNotes = { headline: string; blocks: ReleaseNoteBlock[] };

// electron-updater reads GitHub notes from the releases feed, which carries
// rendered HTML; other providers may pass the Markdown source through.
const HTML_TAG = /<\/?(?:h[1-6]|p|ul|ol|li|br|strong|b|em|code|a|div|blockquote|pre|hr)\b[^>]*>/i;
const VERSION_TOKEN = /\bv?\d+\.\d+\.\d+(?:-[0-9a-z.-]+)?/gi;
const EDGE_SEPARATORS = /^[\s:：·|—–-]+|[\s:：·|—–-]+$/g;
// The panel already labels the section, so these release headings would repeat it.
const SECTION_TITLES = new Set(["本次更新", "更新内容"]);
const SKIPPED_TAGS = new Set(["hr", "img", "script", "style", "template", "iframe", "svg", "video", "picture"]);
const CONTAINER_TAGS = new Set(["div", "section", "article", "blockquote", "details", "main"]);

type Marks = Omit<ReleaseNoteSpan, "text">;

function spanText(spans: ReleaseNoteSpan[]): string {
  return spans.map((span) => span.text).join("");
}

/** Collapse whitespace the way HTML renders it and merge neighbouring runs with the same marks. */
function normalizeSpans(spans: ReleaseNoteSpan[]): ReleaseNoteSpan[] {
  const result: ReleaseNoteSpan[] = [];
  for (const span of spans) {
    let text = span.text.replace(/\s+/g, " ");
    const previous = result.at(-1);
    if ((!previous || previous.text.endsWith(" ")) && text.startsWith(" ")) text = text.slice(1);
    if (!text) continue;
    if (previous && previous.strong === span.strong && previous.code === span.code) {
      previous.text += text;
    } else {
      result.push({ text, ...(span.strong ? { strong: true } : {}), ...(span.code ? { code: true } : {}) });
    }
  }
  const last = result.at(-1);
  if (last) {
    last.text = last.text.trimEnd();
    if (!last.text) result.pop();
  }
  return result;
}

function pushBlock(blocks: ReleaseNoteBlock[], kind: ReleaseNoteBlock["kind"], spans: ReleaseNoteSpan[], level?: number) {
  const normalized = normalizeSpans(spans);
  if (normalized.length) blocks.push(level ? { kind, level, spans: normalized } : { kind, spans: normalized });
}

function tagName(node: Node): string {
  return node.nodeType === Node.ELEMENT_NODE ? (node as Element).tagName.toLowerCase() : "";
}

function inlineSpans(nodes: Node[]): ReleaseNoteSpan[] {
  const spans: ReleaseNoteSpan[] = [];
  const visit = (node: Node, marks: Marks) => {
    if (node.nodeType === Node.TEXT_NODE) {
      spans.push({ text: node.textContent ?? "", ...marks });
      return;
    }
    const tag = tagName(node);
    if (!tag || SKIPPED_TAGS.has(tag)) return;
    if (tag === "br") {
      spans.push({ text: " ", ...marks });
      return;
    }
    const next: Marks = tag === "strong" || tag === "b" ? { ...marks, strong: true } : tag === "code" ? { ...marks, code: true } : marks;
    node.childNodes.forEach((child) => visit(child, next));
    if (tag === "p" || tag === "div") spans.push({ text: " ", ...marks });
  };
  nodes.forEach((node) => visit(node, {}));
  return spans;
}

function collectListItem(item: Element, blocks: ReleaseNoteBlock[]) {
  const own: Node[] = [];
  const nested: Element[] = [];
  item.childNodes.forEach((node) => {
    const tag = tagName(node);
    if (tag === "ul" || tag === "ol") nested.push(node as Element);
    else own.push(node);
  });
  pushBlock(blocks, "item", inlineSpans(own));
  nested.forEach((list) => collectList(list, blocks));
}

function collectList(list: Element, blocks: ReleaseNoteBlock[]) {
  Array.from(list.children).forEach((child) => {
    if (child.tagName.toLowerCase() === "li") collectListItem(child, blocks);
  });
}

function collectBlocks(parent: Node, blocks: ReleaseNoteBlock[]) {
  let loose: Node[] = [];
  const flush = () => {
    pushBlock(blocks, "paragraph", inlineSpans(loose));
    loose = [];
  };
  parent.childNodes.forEach((node) => {
    const tag = tagName(node);
    if (/^h[1-6]$/.test(tag)) {
      flush();
      pushBlock(blocks, "heading", inlineSpans([node]), Number(tag[1]));
    } else if (tag === "ul" || tag === "ol") {
      flush();
      collectList(node as Element, blocks);
    } else if (tag === "p" || tag === "pre") {
      flush();
      pushBlock(blocks, "paragraph", inlineSpans([node]));
    } else if (CONTAINER_TAGS.has(tag)) {
      flush();
      collectBlocks(node, blocks);
    } else if (SKIPPED_TAGS.has(tag)) {
      flush();
    } else {
      loose.push(node);
    }
  });
  flush();
}

function parseHtml(html: string): ReleaseNoteBlock[] {
  // DOMParser builds an inert document: nothing in it runs or loads, and only
  // its text is read back, so the notes are never inserted as markup.
  const document = new DOMParser().parseFromString(html, "text/html");
  const blocks: ReleaseNoteBlock[] = [];
  collectBlocks(document.body, blocks);
  return blocks;
}

function markdownSpans(text: string): ReleaseNoteSpan[] {
  const plain = text.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1");
  const spans: ReleaseNoteSpan[] = [];
  let index = 0;
  for (const match of plain.matchAll(/(\*\*|__)(.+?)\1|`([^`]+)`/g)) {
    if (match.index > index) spans.push({ text: plain.slice(index, match.index) });
    spans.push(match[3] !== undefined ? { text: match[3], code: true } : { text: match[2], strong: true });
    index = match.index + match[0].length;
  }
  if (index < plain.length) spans.push({ text: plain.slice(index) });
  return spans;
}

function parseMarkdown(markdown: string): ReleaseNoteBlock[] {
  const blocks: ReleaseNoteBlock[] = [];
  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^([-*_])(?:\s*\1){2,}$/.test(line)) continue;
    const heading = line.match(/^(#{1,6})\s+(.+?)(?:\s+#+)?$/);
    const item = line.match(/^(?:[-*+]|\d+[.)])\s+(.+)$/);
    if (heading) pushBlock(blocks, "heading", markdownSpans(heading[2]), heading[1].length);
    else if (item) pushBlock(blocks, "item", markdownSpans(item[1]));
    else pushBlock(blocks, "paragraph", markdownSpans(line.replace(/^>\s?/, "")));
  }
  return blocks;
}

/**
 * Turns release notes into plain blocks for React to render as text. A leading
 * title heading becomes the headline once the product name and version are
 * removed ("v0.6.0：macOS 安装包" → "macOS 安装包"), and is dropped when nothing
 * else is left.
 */
export function parseReleaseNotes(notes: string): ReleaseNotes {
  const parsed = HTML_TAG.test(notes) ? parseHtml(notes) : parseMarkdown(notes);
  let headline = "";
  if (parsed[0]?.kind === "heading" && parsed[0].level === 1) {
    headline = spanText(parsed.shift()!.spans)
      .replace(/RailWatch(?:\s*12306)?/gi, "")
      .replace(VERSION_TOKEN, "")
      .replace(/\s+/g, " ")
      .replace(EDGE_SEPARATORS, "");
  }
  const blocks = parsed.filter((block) => block.kind !== "heading" || !SECTION_TITLES.has(spanText(block.spans)));
  return { headline, blocks };
}
