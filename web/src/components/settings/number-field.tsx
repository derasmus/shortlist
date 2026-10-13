import { useState } from "react";

import { Input } from "@/components/ui/input";
import { changedWithoutFocus } from "@/lib/unfocused-change";

/** Keep incomplete typing local; only a committed, bounded number reaches autosave. */
export function SettingsNumberField({ value, onCommit, min, max, step = 1, ...props }: {
  value: number; onCommit: (value: number) => void; min: number; max: number; step?: number;
  id: string; className?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = (raw: string | null) => {
    if (raw !== null && raw.trim() !== "") {
      const number = Number(raw);
      if (Number.isFinite(number)) onCommit(Math.min(max, Math.max(min, Math.round(number / step) * step)));
    }
    setDraft(null);
  };
  return <Input {...props} type="number" min={min} max={max} step={step}
    value={draft ?? value}
    onChange={(event) => {
      if (changedWithoutFocus(event.currentTarget)) commit(event.target.value);
      else setDraft(event.target.value);
    }}
    onBlur={() => commit(draft)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }} />;
}
