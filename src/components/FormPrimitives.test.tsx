// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { ActionRow, Field, SectionTitle } from "./FormPrimitives";

describe("FormPrimitives", () => {
  test("renders accessible field labels, section titles, and action rows", () => {
    render(
      <section>
        <SectionTitle eyebrow="Quiet Safety Desk" title="行程设置" action={<button type="button">帮助</button>} />
        <Field label="车次" description="输入后自动转为大写">
          <input />
        </Field>
        <ActionRow>
          <button type="button">保存</button>
        </ActionRow>
      </section>,
    );

    expect(screen.getByText("Quiet Safety Desk")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "行程设置" })).toBeTruthy();
    const input = screen.getByLabelText("车次");
    const description = screen.getByText("输入后自动转为大写");
    expect(input).toBeTruthy();
    expect(description.id).toBeTruthy();
    expect(input.getAttribute("aria-describedby")).toBe(description.id);
    expect(screen.getByRole("button", { name: "保存" })).toBeTruthy();
  });

  test("appends field descriptions to existing describedby references", () => {
    render(
      <section>
        <span id="existing-help">已有帮助文本</span>
        <Field label="席别" description="优先匹配二等座">
          <input aria-describedby="existing-help" />
        </Field>
      </section>,
    );

    const input = screen.getByLabelText("席别");
    const description = screen.getByText("优先匹配二等座");
    expect(input.getAttribute("aria-describedby")).toBe(`existing-help ${description.id}`);
  });
});
