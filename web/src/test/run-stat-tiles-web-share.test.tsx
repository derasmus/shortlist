/** The run summary says how much of what a run delivered the AI web search found (#152). */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunStatTiles } from "@/components/runs/run-stat-tiles";
import { makeTilesRun } from "@/test/run-fixtures";

function renderShare(web_share: unknown) {
  render(<RunStatTiles run={makeTilesRun({ web_share })} />);
}

describe("the AI-search share line", () => {
  it("shows the share of all rows and of the Picked for You row", () => {
    renderShare({ picked: 0.06, all: 0.27 });
    const line = screen.getByText("AI-search titles in rows").closest("p");
    expect(line).toHaveTextContent("AI-search titles in rows 27% · Picked for You: 6%");
  });

  it("leaves the Picked for You figure out when the run delivered none", () => {
    renderShare({ picked: null, all: 0.5 });
    const line = screen.getByText("AI-search titles in rows").closest("p");
    expect(line).toHaveTextContent("50%");
    expect(line).not.toHaveTextContent("Picked for You");
  });

  it("is hidden when the run did not use the AI web search", () => {
    renderShare(null);
    expect(screen.queryByText("AI-search titles in rows")).not.toBeInTheDocument();
  });

  it("is hidden when the run delivered no picks", () => {
    renderShare({ picked: null, all: null });
    expect(screen.queryByText("AI-search titles in rows")).not.toBeInTheDocument();
  });

  it("is hidden on a run recorded before the figure existed", () => {
    render(<RunStatTiles run={makeTilesRun()} />);
    expect(screen.queryByText("AI-search titles in rows")).not.toBeInTheDocument();
  });
});
