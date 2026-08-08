/**
 * Shared platform palette.
 *
 * The 3D field colours nodes by DataHub platform. The Cartography legend has to
 * use exactly the same mapping, but it must not pull Three.js into the shell
 * chunk — so the palette lives here and `lineage-field.ts` re-exports it.
 */

export const PLATFORM_COLORS: Record<string, number> = {
  kafka: 0x7c5cff,
  postgres: 0x4c8dff,
  mysql: 0x4c8dff,
  s3: 0x8ea3c8,
  hdfs: 0x8ea3c8,
  dbt: 0x46d6ff,
  airflow: 0x46d6ff,
  snowflake: 0x34d399,
  bigquery: 0x34d399,
  redshift: 0x34d399,
  looker: 0xffc46b,
  tableau: 0xffc46b,
  superset: 0xffc46b,
  powerbi: 0xffc46b,
};

export const FALLBACK_COLORS = [0x7c5cff, 0x4c8dff, 0x46d6ff, 0x34d399, 0xffc46b, 0x8ea3c8];

export function platformKey(urnOrName?: string | null): string {
  if (!urnOrName) return "unknown";
  return urnOrName.replace("urn:li:dataPlatform:", "").toLowerCase();
}

export function colorForPlatform(key: string): number {
  const known = PLATFORM_COLORS[key];
  if (known !== undefined) return known;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}

/** `0x4c8dff` -> `#4c8dff`, for DOM styling of the legend dots. */
export function platformCss(key: string): string {
  return `#${colorForPlatform(key).toString(16).padStart(6, "0")}`;
}
