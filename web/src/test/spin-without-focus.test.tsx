import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { NumberField } from "@/components/number-field";
import { RowLimitsFields } from "@/components/rows/row-limits-fields";
import { SeedWindowField } from "@/components/seed-window-field";
import { IdleHoldField } from "@/components/settings/idle-hold-field";
import { SettingsNumberField } from "@/components/settings/number-field";
import { RefreshDaysField } from "@/components/settings/refresh-days-field";
import { blankInput } from "@/lib/collections";
import type { CollectionInput } from "@/lib/types";

/**
 * Issue #160. Firefox's spin buttons change a number box's value WITHOUT focusing it (measured: the
 * `input` event fires with `document.activeElement` still the body), so no blur ever follows. A box
 * that saves only on blur kept the new number on screen and handed the old one to Save.
 *
 * `fireEvent.change` on a box nothing has focused is exactly that event.
 */
function spinWithoutFocus(box: HTMLElement, value: string) {
  expect(document.activeElement).not.toBe(box);
  fireEvent.change(box, { target: { value } });
}

describe("a number changed by a spin button that never focused the box", () => {
  it("reaches the row from Take turns", () => {
    const onChange = vi.fn();
    render(<SeedWindowField value={1} onChange={onChange} />);
    spinWithoutFocus(screen.getByLabelText(/Take turns between their last/i), "3");
    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("reaches the row from a whole-number field", () => {
    const onChange = vi.fn();
    render(<NumberField value={30} onChange={onChange} min={1} max={100} unit="titles" label="Size" fallbackLabel="Size" />);
    spinWithoutFocus(screen.getByLabelText("Size"), "31");
    expect(onChange).toHaveBeenCalledWith(31);
  });

  it("reaches the row from a limit", () => {
    const patches: Partial<CollectionInput>[] = [];
    function Harness() {
      const [input, setInput] = useState<CollectionInput>(blankInput());
      return (
        <RowLimitsFields
          input={input}
          set={(patch) => {
            patches.push(patch);
            setInput((prev) => ({ ...prev, ...patch }));
          }}
        />
      );
    }
    render(<Harness />);
    spinWithoutFocus(screen.getByLabelText("Longest it can run (minutes)"), "1");
    expect(patches).toContainEqual({ max_runtime: 1 });
  });

  it("is saved by a Settings number", () => {
    const onCommit = vi.fn();
    render(<SettingsNumberField id="count" value={30} min={5} max={100} onCommit={onCommit} />);
    spinWithoutFocus(screen.getByRole("spinbutton"), "31");
    expect(onCommit).toHaveBeenCalledWith(31);
  });

  it("is saved by the refresh cadence", () => {
    const onChange = vi.fn();
    render(<RefreshDaysField value={7} onChange={onChange} />);
    spinWithoutFocus(screen.getByRole("spinbutton", { name: /titles refresh every, in days/i }), "8");
    expect(onChange).toHaveBeenCalledWith(8);
  });

  it("is saved by the idle hold", () => {
    const onChange = vi.fn();
    render(<IdleHoldField id="hold" value={7} cadence={1} onChange={onChange} />);
    spinWithoutFocus(screen.getByRole("spinbutton", { name: /How long to hold a row/i }), "8");
    expect(onChange).toHaveBeenCalledWith(8);
  });
});

describe("typing into a focused box", () => {
  // The other half of the contract: a half-typed number still waits for blur or Enter, so typing
  // "12" never sends a 1 on the way.
  it("still waits for the box to be left", async () => {
    const onChange = vi.fn();
    render(<SeedWindowField value={1} onChange={onChange} />);
    const box = screen.getByLabelText(/Take turns between their last/i);
    await userEvent.clear(box);
    await userEvent.type(box, "12");
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledWith(12);
  });
});
