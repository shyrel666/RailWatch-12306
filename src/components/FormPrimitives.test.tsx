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
    expect(screen.getByLabelText("车次")).toBeTruthy();
    expect(screen.getByText("输入后自动转为大写")).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存" })).toBeTruthy();
  });
});
