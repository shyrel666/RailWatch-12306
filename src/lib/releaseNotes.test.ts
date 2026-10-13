// @vitest-environment jsdom
import { describe, expect, test } from "vitest";
import { parseReleaseNotes } from "./releaseNotes";

// electron-updater passes GitHub release bodies through from the releases feed,
// where the Markdown source has already been rendered to HTML.
const githubFeedHtml = `<h1>RailWatch 12306 v0.7.0</h1>
<h2>新增功能</h2>
<ul>
<li>自动候补新增一等座、硬座，合计支持<strong>六种席别</strong>。</li>
<li>提示音支持自定义音频 <code>alert.wav</code> 导入与试听。</li>
</ul>
<h2>修复</h2>
<ul>
<li>修复更新站码时干扰运行中查询的问题。</li>
</ul>`;

describe("parseReleaseNotes", () => {
  test("reads GitHub feed HTML as text blocks instead of showing tags", () => {
    const notes = parseReleaseNotes(githubFeedHtml);

    expect(notes.headline).toBe("");
    expect(notes.blocks).toEqual([
      { kind: "heading", level: 2, spans: [{ text: "新增功能" }] },
      { kind: "item", spans: [{ text: "自动候补新增一等座、硬座，合计支持" }, { text: "六种席别", strong: true }, { text: "。" }] },
      { kind: "item", spans: [{ text: "提示音支持自定义音频 " }, { text: "alert.wav", code: true }, { text: " 导入与试听。" }] },
      { kind: "heading", level: 2, spans: [{ text: "修复" }] },
      { kind: "item", spans: [{ text: "修复更新站码时干扰运行中查询的问题。" }] },
    ]);
    expect(JSON.stringify(notes)).not.toMatch(/<\/?(?:h\d|ul|li|strong|code)>/);
  });

  test("keeps a descriptive release title as the headline and drops the repeated section title", () => {
    const notes = parseReleaseNotes("<h1>v0.6.0：macOS 安装包与「发车牌」界面</h1>\n<h2>本次更新</h2>\n<ul><li><strong>macOS 安装包</strong>：新增两个架构。</li></ul>");

    expect(notes.headline).toBe("macOS 安装包与「发车牌」界面");
    expect(notes.blocks).toEqual([
      { kind: "item", spans: [{ text: "macOS 安装包", strong: true }, { text: "：新增两个架构。" }] },
    ]);
  });

  test("never reads scripts, images or link targets from untrusted notes", () => {
    const notes = parseReleaseNotes(
      `<p>见 <a href="https://example.com/x">发布说明</a><img src="x" onerror="alert(1)"></p><script>alert(2)</script>`,
    );

    expect(notes.blocks).toEqual([{ kind: "paragraph", spans: [{ text: "见 发布说明" }] }]);
  });

  test("flattens nested and loose lists and collapses HTML whitespace", () => {
    const notes = parseReleaseNotes("<ul>\n<li>\n<p>外层\n条目</p>\n<ul><li>内层条目</li></ul>\n</li>\n</ul>");

    expect(notes.blocks).toEqual([
      { kind: "item", spans: [{ text: "外层 条目" }] },
      { kind: "item", spans: [{ text: "内层条目" }] },
    ]);
  });

  test("falls back to Markdown for plain release bodies", () => {
    const notes = parseReleaseNotes("# RailWatch 12306 v0.4.0\n\n本版本修复自动确认问题。\n\n## 更新内容\n\n- **自动确认**：等待按钮启用。\n* 见 [日志](https://example.com) 与 `latest.yml`\n---\n1. 编号条目");

    expect(notes.headline).toBe("");
    expect(notes.blocks).toEqual([
      { kind: "paragraph", spans: [{ text: "本版本修复自动确认问题。" }] },
      { kind: "item", spans: [{ text: "自动确认", strong: true }, { text: "：等待按钮启用。" }] },
      { kind: "item", spans: [{ text: "见 日志 与 " }, { text: "latest.yml", code: true }] },
      { kind: "item", spans: [{ text: "编号条目" }] },
    ]);
  });

  test("returns nothing for empty notes", () => {
    expect(parseReleaseNotes("")).toEqual({ headline: "", blocks: [] });
    expect(parseReleaseNotes("  \n ")).toEqual({ headline: "", blocks: [] });
  });
});
