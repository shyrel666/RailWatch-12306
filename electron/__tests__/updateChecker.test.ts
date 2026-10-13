import { describe, expect, test } from "vitest";
import { releaseTagUrl } from "../updateChecker";

describe("releaseTagUrl", () => {
  test("links the tag page of the public GitHub Release repository", () => {
    expect(releaseTagUrl("0.7.1")).toBe("https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.7.1");
    expect(releaseTagUrl("v0.7.1")).toBe("https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.7.1");
  });

  test("encodes tags that are not URL-safe", () => {
    expect(releaseTagUrl("0.8.0-beta.1+build 2")).toBe(
      "https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.8.0-beta.1%2Bbuild%202",
    );
  });
});
