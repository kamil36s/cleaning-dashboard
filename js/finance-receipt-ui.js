export function receiptProcessingLabel(receipt = {}) {
  const labels = {
    parsed: "Odczytany",
    ocr_required: "Wymaga OCR",
    ocr_unavailable: "OCR niedostępny",
    ocr_failed: "OCR nie powiódł się",
    needs_review: "Wymaga przeglądu",
    source_received: "Źródło zapisane",
  };
  return labels[receipt.processingState] || receipt.processingState || "Stan nieznany";
}

export function receiptTotalLabel(receipt, formatMoney) {
  return receipt?.total == null ? "Kwota nierozpoznana" : formatMoney(receipt.total, receipt.currency);
}

export function receiptProcessingExplanation(receipt = {}) {
  if (receipt.processingState === "ocr_unavailable") return "Paragon został zapisany, ale OCR nie jest dostępny na komputerze.";
  if (receipt.processingState === "ocr_failed") return "OCR uruchomił się, ale nie odczytał użytecznego tekstu z paragonu.";
  if (receipt.processingState === "ocr_required") return "Źródło zawiera obraz i wymaga rozpoznania tekstu.";
  return receipt.processingMessage || "";
}

export function receiptMatchLabel(receipt = {}) {
  if (receipt.transactionId) return receipt.matchState === "manual" ? "Dopasowano ręcznie" : "Dopasowano";
  if (receipt.matchState === "ambiguous") return "Wybierz transakcję";
  return "Bez dopasowania";
}
