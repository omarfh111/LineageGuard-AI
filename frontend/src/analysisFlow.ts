export type ChangeType =
  | "ADD_COLUMN"
  | "RENAME_COLUMN"
  | "CHANGE_COLUMN_TYPE"
  | "DROP_COLUMN";

export type AnalysisDraft = {
  assetUrn: string;
  changeType: ChangeType;
  columnName: string;
  newValue: string;
  reason: string;
  depth: number;
  columnNullable: boolean;
  typeChangeCompatible: boolean | null;
};

export type VerifiedTarget = {
  urn: string;
  label: string;
  entity_type: string;
  platform_urn?: string | null;
};

export type ChatAnalysisHandoff = {
  handoffId: string;
  expiresAt: string;
  target: VerifiedTarget;
  changeType: ChangeType | null;
};

export type ChangeRequestPayload = {
  asset_urn: string;
  change_type: ChangeType;
  column_name: string;
  new_value?: string;
  reason: string;
  environment: "PRODUCTION";
  lineage_depth: number;
  column_nullable?: boolean;
  type_change_compatible?: boolean;
};

export function buildChangeRequest(draft: AnalysisDraft): ChangeRequestPayload {
  const errors = validateDraft(draft);
  if (errors.length > 0) throw new Error(errors[0]);
  const needsNewValue =
    draft.changeType === "RENAME_COLUMN"
    || draft.changeType === "CHANGE_COLUMN_TYPE";
  return {
    asset_urn: draft.assetUrn.trim(),
    change_type: draft.changeType,
    column_name: draft.columnName.trim(),
    new_value: needsNewValue ? draft.newValue.trim() : undefined,
    reason: draft.reason.trim(),
    environment: "PRODUCTION",
    lineage_depth: draft.depth,
    column_nullable:
      draft.changeType === "ADD_COLUMN" ? draft.columnNullable : undefined,
    type_change_compatible:
      draft.changeType === "CHANGE_COLUMN_TYPE"
        ? draft.typeChangeCompatible ?? undefined
        : undefined,
  };
}

export function validateDraft(draft: AnalysisDraft): string[] {
  const errors: string[] = [];
  if (!draft.assetUrn.trim().startsWith("urn:li:")) {
    errors.push("Select a valid DataHub asset URN.");
  }
  if (!draft.columnName.trim()) {
    errors.push("Column name is required for every change type.");
  }
  if (draft.reason.trim().length < 5) {
    errors.push("Provide a reason of at least five characters.");
  }
  if (!Number.isInteger(draft.depth) || draft.depth < 1 || draft.depth > 5) {
    errors.push("Lineage depth must be between 1 and 5.");
  }
  if (
    (draft.changeType === "RENAME_COLUMN"
      || draft.changeType === "CHANGE_COLUMN_TYPE")
    && !draft.newValue.trim()
  ) {
    errors.push(
      draft.changeType === "RENAME_COLUMN"
        ? "The new column name is required."
        : "The proposed data type is required.",
    );
  }
  if (
    draft.changeType === "RENAME_COLUMN"
    && draft.columnName.trim().toLocaleLowerCase()
      === draft.newValue.trim().toLocaleLowerCase()
  ) {
    errors.push("The old and new column names must be different.");
  }
  return errors;
}

export function requestFingerprint(payload: ChangeRequestPayload): string {
  return JSON.stringify(payload);
}

export function hasRevisionChange(
  baselineFingerprint: string | null,
  payload: ChangeRequestPayload | null,
): boolean {
  return baselineFingerprint === null
    || (payload !== null && requestFingerprint(payload) !== baselineFingerprint);
}

export function draftFromRequest(
  request: ChangeRequestPayload,
): AnalysisDraft {
  return {
    assetUrn: request.asset_urn,
    changeType: request.change_type,
    columnName: request.column_name,
    newValue: request.new_value ?? "",
    reason: request.reason,
    depth: request.lineage_depth,
    columnNullable: request.column_nullable ?? true,
    typeChangeCompatible: request.type_change_compatible ?? null,
  };
}

export function createChatHandoff(input: {
  action: string;
  resolution?: {
    status: string;
    targets: VerifiedTarget[];
  } | null;
  handoffId?: string | null;
  expiresAt?: string | null;
  changeType?: ChangeType | null;
}): ChatAnalysisHandoff | null {
  if (
    input.action !== "ANALYZE_IMPACT"
    || input.resolution?.status !== "RESOLVED"
    || input.resolution.targets.length !== 1
    || !input.resolution.targets[0].urn.startsWith("urn:li:")
    || !input.handoffId
    || !input.expiresAt
  ) {
    return null;
  }
  return {
    handoffId: input.handoffId,
    expiresAt: input.expiresAt,
    target: input.resolution.targets[0],
    changeType: input.changeType ?? null,
  };
}

export function isHandoffUsable(
  handoff: ChatAnalysisHandoff | null,
  now = Date.now(),
): handoff is ChatAnalysisHandoff {
  return handoff !== null && Date.parse(handoff.expiresAt) > now;
}
