import { describe, expect, it } from "vitest";
import {
  buildChangeRequest,
  createChatHandoff,
  draftFromRequest,
  hasRevisionChange,
  isHandoffUsable,
  requestFingerprint,
  type AnalysisDraft,
  type ChangeType,
} from "../src/analysisFlow";

const base: AnalysisDraft = {
  assetUrn: "urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)",
  changeType: "ADD_COLUMN",
  columnName: "lineageguard_note",
  newValue: "",
  reason: "Controlled contract review.",
  depth: 2,
  columnNullable: true,
  typeChangeCompatible: null,
};

describe("analysis request construction", () => {
  it.each<[
    ChangeType,
    Partial<AnalysisDraft>,
    Record<string, unknown>,
  ]>([
    ["ADD_COLUMN", {}, { column_nullable: true, new_value: undefined }],
    [
      "RENAME_COLUMN",
      { newValue: "order_state" },
      { new_value: "order_state", column_nullable: undefined },
    ],
    [
      "CHANGE_COLUMN_TYPE",
      { newValue: "BIGINT", typeChangeCompatible: false },
      { new_value: "BIGINT", type_change_compatible: false },
    ],
    ["DROP_COLUMN", {}, { new_value: undefined, column_nullable: undefined }],
  ])("supports %s without leaking fields from another type", (changeType, patch, expected) => {
    const payload = buildChangeRequest({ ...base, ...patch, changeType });
    expect(payload).toMatchObject(expected);
  });

  it("requires a column for ADD_COLUMN too", () => {
    expect(() => buildChangeRequest({ ...base, columnName: " " })).toThrow(
      "Column name is required",
    );
  });

  it("rejects a rename to the same name", () => {
    expect(() =>
      buildChangeRequest({
        ...base,
        changeType: "RENAME_COLUMN",
        newValue: base.columnName.toUpperCase(),
      }),
    ).toThrow("must be different");
  });

  it("changes fingerprint whenever the reviewed draft changes", () => {
    const first = buildChangeRequest(base);
    const second = buildChangeRequest({ ...base, reason: "A revised reason." });
    expect(requestFingerprint(first)).not.toBe(requestFingerprint(second));
  });

  it("canonicalizes server null optionals before reload comparison", () => {
    const serverRequest = {
      ...buildChangeRequest(base),
      new_value: null,
      type_change_compatible: null,
    } as unknown as Parameters<typeof requestFingerprint>[0];
    const restored = draftFromRequest(serverRequest);
    expect(requestFingerprint(buildChangeRequest(restored))).toBe(
      requestFingerprint(buildChangeRequest(base)),
    );
  });

  it("blocks an unchanged revision and accepts a changed request", () => {
    const reviewed = buildChangeRequest(base);
    const baseline = requestFingerprint(reviewed);
    expect(hasRevisionChange(baseline, reviewed)).toBe(false);
    expect(
      hasRevisionChange(
        baseline,
        buildChangeRequest({ ...base, reason: "Reviewer-requested update." }),
      ),
    ).toBe(true);
  });
});

describe("verified chat handoff", () => {
  const target = {
    urn: base.assetUrn,
    label: "orders",
    entity_type: "DATASET",
  };

  it("requires one resolved target plus a server handoff", () => {
    expect(
      createChatHandoff({
        action: "ANALYZE_IMPACT",
        resolution: { status: "RESOLVED", targets: [target] },
        handoffId: "handoff-123456789",
        expiresAt: "2030-01-01T00:00:00Z",
        changeType: "DROP_COLUMN",
      }),
    ).toMatchObject({ target, changeType: "DROP_COLUMN" });
  });

  it("rejects ambiguous or tokenless handoffs", () => {
    expect(
      createChatHandoff({
        action: "ANALYZE_IMPACT",
        resolution: { status: "AMBIGUOUS", targets: [target, target] },
        handoffId: null,
        expiresAt: null,
      }),
    ).toBeNull();
  });

  it("expires locally before the analysis call", () => {
    const handoff = createChatHandoff({
      action: "ANALYZE_IMPACT",
      resolution: { status: "RESOLVED", targets: [target] },
      handoffId: "handoff-123456789",
      expiresAt: "2029-01-01T00:00:00Z",
    });
    expect(isHandoffUsable(handoff, Date.parse("2030-01-01T00:00:00Z"))).toBe(false);
  });
});
