import { describe, expect, it } from "vitest";

import { parseSchemaFields } from "../src/AssistantAnswer";

describe("assistant answer presentation", () => {
  it("turns evidence-backed schema rows into readable field data", () => {
    const answer = [
      "DataHub schema lookup returned 2 fields [E-schema-orders].",
      "- column=order_id, type=NUMBER(38,0) [E-schema-orders].",
      "- column=order_status, type=VARCHAR(16777216) [E-schema-orders].",
    ].join("\n");

    expect(parseSchemaFields(answer)).toEqual([
      { name: "order_id", dataType: "NUMBER(38,0)" },
      { name: "order_status", dataType: "VARCHAR(16777216)" },
    ]);
  });

  it("does not reinterpret ordinary prose as a schema", () => {
    expect(parseSchemaFields("orders has downstream dashboards.")).toEqual([]);
  });
});
