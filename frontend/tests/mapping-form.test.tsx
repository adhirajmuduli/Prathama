import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MappingForm } from "@/components/upload/mapping-form";
import { columnMappingSchema, type Probe } from "@/lib/contracts/ingest";

function makeProbe(): Probe {
  const probe = {
    upload_id: "upl_" + "a".repeat(32),
    filename: "obs.csv",
    extension: ".csv",
    file_format: "csv",
    content_type: "text/csv",
    encoding: "utf-8",
    delimiter: ",",
    has_header: true,
    fields: ["station", "sampled_at", "parameter", "value", "unit", "notes"],
    decimal_style: "point",
    layout: "long",
    layout_confidence: 0.9,
    layout_evidence: ["time column detected"],
    layout_warnings: [],
    sniff_warnings: [],
    sheet_names: [],
    numeric_fields: ["value"],
    date_fields: ["sampled_at"],
    proposed_mapping: {
      schema_version: "1.0.0",
      layout: "long",
      wide_axis: null,
      columns: [
        { column: "station", role: "station" },
        { column: "sampled_at", role: "timestamp" },
        { column: "parameter", role: "parameter" },
        { column: "value", role: "value" },
        { column: "unit", role: "unit" },
        { column: "notes", role: "ignored" },
      ],
      default_parameter: null,
      default_unit: null,
      source_crs: null,
      date_order: "day_first",
      timezone_policy: "assume_utc",
      timezone_name: null,
      duplicate_policy: "flag_all",
    },
    proposal_warnings: [],
  };
  return probe as Probe;
}

describe("MappingForm", () => {
  it("renders one role select per column from the probe", () => {
    render(<MappingForm probe={makeProbe()} onSubmit={() => undefined} />);
    expect(screen.getByLabelText("Role for station")).toBeInTheDocument();
    expect(screen.getByLabelText("Role for notes")).toBeInTheDocument();
    expect(screen.getAllByRole("option").length).toBeGreaterThan(6);
  });

  it("submits the proposed mapping unchanged when confirmed", () => {
    const onSubmit = vi.fn();
    render(<MappingForm probe={makeProbe()} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: /confirm mapping/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submitted = onSubmit.mock.calls[0]?.[0];
    expect(columnMappingSchema.parse(submitted).columns).toHaveLength(6);
  });

  it("reflects a role change in the submitted mapping", () => {
    const onSubmit = vi.fn();
    render(<MappingForm probe={makeProbe()} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Role for notes"), {
      target: { value: "value" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm mapping/i }));
    const submitted = onSubmit.mock.calls[0]?.[0];
    const notes = submitted.columns.find(
      (item: { column: string }) => item.column === "notes",
    );
    expect(notes?.role).toBe("value");
  });

  it("blocks submission when the mapping is structurally invalid", () => {
    const onSubmit = vi.fn();
    const probe = makeProbe();
    probe.proposed_mapping.columns = [];
    render(<MappingForm probe={probe} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: /confirm mapping/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
