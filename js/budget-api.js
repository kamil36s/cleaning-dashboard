import { normalizeBudgetData } from "./budget.js";

const BUDGET_API_URL = "/api/budget";

async function readJsonResponse(response) {
  const payload = typeof response?.json === "function"
    ? await response.json().catch(() => ({}))
    : {};
  if (!response?.ok || payload?.ok === false) {
    throw new Error(payload?.error || response?.statusText || "Budget API error");
  }
  return payload;
}

export async function fetchBudgetServerData() {
  const response = await fetch(BUDGET_API_URL, { cache: "no-store" });
  const payload = await readJsonResponse(response);
  return normalizeBudgetData(payload.data || payload);
}

export async function saveBudgetServerData(data) {
  void data;
  throw new Error("Pełny zapis budżetu jest wyłączony. Użyj operacji adnotacji lub importu.");
}

async function postBudget(path, body) {
  const response = await fetch(`${BUDGET_API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJsonResponse(response);
}

async function getBudget(path, query = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const suffix = params.size ? `?${params}` : "";
  const response = await fetch(`${BUDGET_API_URL}${path}${suffix}`, { cache: "no-store" });
  return readJsonResponse(response);
}

export async function updateBudgetAnnotations(updates) {
  return postBudget("/annotations", { updates });
}

export async function updateBudgetSettings(settings) {
  return postBudget("/settings", { settings });
}

export async function migrateLegacyBudgetData(data) {
  const payload = await postBudget("/migrate-legacy", { data: normalizeBudgetData(data) });
  return normalizeBudgetData(payload.data || {});
}

export async function fetchBudgetImportHistory() {
  const response = await fetch(`${BUDGET_API_URL}/imports`, { cache: "no-store" });
  const payload = await readJsonResponse(response);
  return Array.isArray(payload.imports) ? payload.imports : [];
}

export async function rollbackBudgetImport(batchId) {
  return postBudget("/imports/rollback", { batchId });
}

export async function previewBudgetImportRollback(batchId) {
  return getBudget(`/imports/${encodeURIComponent(batchId)}/rollback-preview`);
}

export async function importBudgetCsvToServer(file) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  const response = await fetch(`${BUDGET_API_URL}/import-csv`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      contentBase64: btoa(binary),
    }),
  });
  const payload = await readJsonResponse(response);
  return normalizeBudgetData(payload.data || {});
}

async function fileBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export async function importFinanceReceipt(file) {
  const payload = await postBudget("/receipts/import", {
    filename: file.name,
    mimeType: file.type || "application/octet-stream",
    contentBase64: await fileBase64(file),
  });
  return payload.receipt;
}

export async function fetchFinanceReceipts(query = {}) {
  const payload = await getBudget("/receipts", query);
  return payload.receipts || [];
}

export async function fetchFinanceReceipt(receiptId) {
  const payload = await getBudget(`/receipts/${encodeURIComponent(receiptId)}`);
  return payload.receipt;
}

export async function fetchFinanceReceiptSources(receiptId) {
  const payload = await getBudget(`/receipts/${encodeURIComponent(receiptId)}/sources`);
  return payload.sources || [];
}

export async function fetchReceiptProcessingHealth() {
  const payload = await getBudget("/receipts/processing-health");
  return payload.health || {};
}

export async function reprocessFinanceReceipt(receiptId) {
  const payload = await postBudget(`/receipts/${encodeURIComponent(receiptId)}/reprocess`, {});
  return payload.receipt;
}

export async function deleteFinanceReceipt(receiptId) {
  const payload = await postBudget(`/receipts/${encodeURIComponent(receiptId)}/delete`, {});
  return payload.delete;
}

export async function reprocessFinanceReceiptsNeedingOcr() {
  const payload = await postBudget("/receipts/reprocess-needing-ocr", {});
  return payload.reprocess;
}

export async function updateFinanceReceiptMetadata(receiptId, metadata) {
  const payload = await postBudget(`/receipts/${encodeURIComponent(receiptId)}/metadata`, metadata);
  return payload.receipt;
}

export async function applyFinanceReceiptParseReview(receiptId, decision) {
  const payload = await postBudget(`/receipts/${encodeURIComponent(receiptId)}/parse-review`, decision);
  return payload.receipt;
}

export async function matchFinanceReceipt(receiptId, transactionId = null) {
  const payload = await postBudget(`/receipts/${encodeURIComponent(receiptId)}/match`, { transactionId });
  return payload.match;
}

export async function fetchReceiptItemReviewGroups() {
  const payload = await getBudget("/receipt-items/review/groups");
  return payload.groups || [];
}

export async function previewReceiptItemGroup(groupId, classification) {
  const payload = await postBudget(`/receipt-items/review/groups/${encodeURIComponent(groupId)}/preview`, classification);
  return payload.preview;
}

export async function applyReceiptItemGroup(groupId, classification) {
  const payload = await postBudget(`/receipt-items/review/groups/${encodeURIComponent(groupId)}/apply`, classification);
  return payload.apply;
}

export async function undoLatestReceiptItemGroup() {
  const payload = await postBudget("/receipt-items/review/undo-latest", {});
  return payload.undo;
}

export async function fetchReceiptProductCategories() {
  const payload = await getBudget("/product-categories");
  return payload.categories || [];
}

export async function fetchReceiptProduct(productId) {
  const payload = await getBudget(`/products/${encodeURIComponent(productId)}`);
  return payload.product;
}

export async function lookupReceiptBarcode(barcode) {
  return getBudget(`/products/barcode/${encodeURIComponent(barcode)}`);
}

export async function fetchBudgetTransactions(query = {}) {
  return getBudget("/transactions", query);
}

export async function fetchBudgetCategories() {
  const payload = await getBudget("/categories");
  return payload.categories || [];
}

export async function createBudgetCategory(category) {
  return postBudget("/categories", category);
}

export async function fetchBudgetMerchants() {
  const payload = await getBudget("/merchants");
  return payload.merchants || [];
}

export async function createBudgetMerchant(merchant) {
  const payload = await postBudget("/merchants", merchant);
  return payload.merchant;
}

export async function fetchBudgetMerchantTypes() {
  const payload = await getBudget("/merchant-types");
  return payload.merchantTypes || [];
}

export async function fetchBudgetRules() {
  const payload = await getBudget("/rules");
  return payload.rules || [];
}

export async function createBudgetRule(rule) {
  return postBudget("/rules", rule);
}

export async function previewBudgetRule(ruleId, options = {}) {
  return postBudget(`/rules/${encodeURIComponent(ruleId)}/preview`, options);
}

export async function applyBudgetRule(ruleId, options = {}) {
  return postBudget(`/rules/${encodeURIComponent(ruleId)}/apply`, options);
}

export async function updateBudgetRule(ruleId, patch) {
  const response = await fetch(`${BUDGET_API_URL}/rules/${encodeURIComponent(ruleId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  });
  return readJsonResponse(response);
}

export async function deleteBudgetRule(ruleId) {
  const response = await fetch(`${BUDGET_API_URL}/rules/${encodeURIComponent(ruleId)}?confirm=delete`, { method: "DELETE" });
  return readJsonResponse(response);
}

export async function fetchBudgetReview(status = "open") {
  const payload = await getBudget("/review", { status });
  return payload.items || [];
}

export async function fetchBudgetReviewGroups(query = {}) {
  const payload = await getBudget("/review/groups", query);
  return payload.data;
}

export async function previewBudgetReviewGroup(groupId, payload = {}) {
  const response = await postBudget(`/review/groups/${encodeURIComponent(groupId)}/preview`, payload);
  return response.preview;
}

export async function fetchBudgetReviewGroupTransactions(groupId) {
  const payload = await getBudget(`/review/groups/${encodeURIComponent(groupId)}/transactions`);
  return payload.transactions || [];
}

export async function applyBudgetReviewGroup(groupId, payload = {}) {
  const response = await postBudget(`/review/groups/${encodeURIComponent(groupId)}/apply`, payload);
  return response.apply;
}

export async function undoLatestBudgetReviewGroup() {
  const response = await postBudget("/review/groups/undo-latest", {});
  return response.undo;
}

export async function updateBudgetReview(transactionId, issueType, status) {
  return postBudget(`/review/${encodeURIComponent(transactionId)}/status`, { issueType, status });
}

export async function correctBudgetReview(transactionId, payload) {
  return postBudget(`/review/${encodeURIComponent(transactionId)}/correct`, payload);
}

export async function classifyBudgetTransaction(transactionId, classification) {
  return postBudget(`/transactions/${encodeURIComponent(transactionId)}/classification`, classification);
}

export async function fetchBudgetClassification(transactionId) {
  return getBudget(`/transactions/${encodeURIComponent(transactionId)}/classification`);
}

export async function fetchBudgetPeriod(period, options = {}) {
  return getBudget("/periods", { period, ...options });
}

export async function fetchBudgetAnalytics(resource = "summary", query = {}) {
  return getBudget(`/analytics/${resource}`, query);
}

export async function fetchFinanceResource(resource, query = {}) {
  const payload = await getBudget(`/${resource}`, query);
  return payload.data;
}

export async function mutateFinanceResource(resource, data = {}) {
  const payload = await postBudget(`/${resource}`, data);
  return payload.data;
}

export const fetchFinanceOverview = (query = {}) => fetchFinanceResource("overview", query);
export const fetchFinanceObligations = (query = {}) => fetchFinanceResource("obligations", query);
export const fetchFinanceBills = (query = {}) => fetchFinanceResource("bills", query);
export const fetchFinanceBudgets = (query = {}) => fetchFinanceResource("budgets", query);
export const fetchFinanceGoals = (query = {}) => fetchFinanceResource("goals", query);
export const fetchFinanceReport = (query = {}) => fetchFinanceResource("report", query);
export const fetchFinanceForecast = (query = {}) => fetchFinanceResource("forecast", query);
export const fetchFinanceDataQuality = () => fetchFinanceResource("data-quality");
