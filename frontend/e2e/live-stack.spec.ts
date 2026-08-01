import { expect, test } from "@playwright/test";

test.use({ baseURL: "http://localhost:5173" });
test.skip(!process.env.LINEAGEGUARD_LIVE_E2E, "Explicit live DataHub opt-in required");

test("live DataHub cache remains visible and workflow survives reload", async ({ page }) => {
  test.setTimeout(150_000);

  await page.goto("/#/cartographie", { waitUntil: "domcontentloaded" });
  const graph = page.getByTestId("catalog-graph");
  await expect(graph).toBeVisible({ timeout: 20_000 });
  await expect.poll(
    async () => Number(await graph.getAttribute("data-node-count")),
    { timeout: 60_000, message: "server-owned catalog cache should become usable" },
  ).toBeGreaterThan(0);
  const initialCount = Number(await graph.getAttribute("data-node-count"));

  await page.getByRole("button", { name: "Refresh from DataHub" }).click();
  await expect(page.getByTestId("catalog-cache-state")).toContainText("REFRESHING");
  expect(Number(await graph.getAttribute("data-node-count"))).toBe(initialCount);

  await page.goto("/#/analyse", { waitUntil: "domcontentloaded" });
  await page.getByRole("textbox", { name: "New column name" }).fill(`lineageguard_live_e2e_${Date.now()}`);
  await page.getByRole("button", { name: "Analyze impact", exact: false }).click();
  const report = page.getByTestId("analysis-report");
  await expect(report).toBeVisible({ timeout: 90_000 });
  const runId = await report.getAttribute("data-analysis-run-id");
  expect(runId).toMatch(/^[0-9a-f-]{36}$/i);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("analysis-report")).toHaveAttribute("data-analysis-run-id", runId!);
  await expect(page.getByTestId("workflow-restore-status")).toContainText("Judge and approval authority were reset");
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(["lineageguard-analysis-run-v1"]);
});
