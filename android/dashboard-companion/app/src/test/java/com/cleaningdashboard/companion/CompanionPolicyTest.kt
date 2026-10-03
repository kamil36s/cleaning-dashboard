package com.cleaningdashboard.companion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionPolicyTest {
    @Test fun supportedReceiptTypesAreExplicit() {
        assertTrue(ReceiptTypePolicy.isSupported("application/pdf"))
        assertTrue(ReceiptTypePolicy.isSupported("application/json"))
        assertTrue(ReceiptTypePolicy.isSupported("image/webp"))
        assertFalse(ReceiptTypePolicy.isSupported("application/zip"))
    }

    @Test fun queueTransitionsPreserveUploadedTerminalState() {
        assertTrue(QueueStateMachine.canTransition(UploadState.PENDING, UploadState.UPLOADING))
        assertTrue(QueueStateMachine.canTransition(UploadState.UPLOADING, UploadState.FAILED))
        assertTrue(QueueStateMachine.canTransition(UploadState.FAILED, UploadState.PENDING))
        assertFalse(QueueStateMachine.canTransition(UploadState.UPLOADED, UploadState.PENDING))
    }

    @Test fun serverAddressHasNoPrivateDefaultAndRequiresHttpScheme() {
        assertTrue(ServerConfigValidator.normalizeBaseUrl("").isEmpty())
        assertTrue(ServerConfigValidator.normalizeBaseUrl("http://dashboard.local:8000/") == "http://dashboard.local:8000")
    }

    @Test fun scannerPlanUsesOrderedJpegsAndKeepsPdfAsArchive() {
        val plan = ScanBundlePolicy.plan(pageCount = 3, hasPdf = true)
        assertEquals(listOf(1, 2, 3), plan.filter { it.sourceRole == "page" }.map { it.pageNumber })
        assertTrue(plan.first().isPrimary)
        assertEquals("archive", plan.last().sourceRole)
        assertFalse(plan.last().isPrimary)
    }

    @Test fun pdfOnlyScanStillHasOnePrimarySource() {
        val plan = ScanBundlePolicy.plan(pageCount = 0, hasPdf = true)
        assertEquals(1, plan.size)
        assertEquals("archive", plan.single().sourceRole)
        assertTrue(plan.single().isPrimary)
    }

    @Test fun uploadResultSummaryReportsParsingItemsAndMatch() {
        val result = UploadResult(
            receiptId = "receipt-1", duplicate = false, validationState = "valid",
            processingState = "parsed", matchState = "strong", itemCount = 7,
            processingMessage = null,
        )
        assertTrue(result.summary().contains("7"))
        assertTrue(result.summary().contains("dopasowany"))
    }

    @Test fun uploadResultSummaryReportsOcrAndMatchFollowUp() {
        val missingOcr = UploadResult(
            "receipt-2", false, "needs_review", "ocr_unavailable", "none", 0,
            "Tesseract OCR is not installed or configured.",
        )
        assertTrue(missingOcr.summary().contains("OCR"))
        assertTrue(missingOcr.summary().contains("bez dopasowania"))

        val needsChoice = UploadResult(
            "receipt-3", false, "valid", "parsed", "ambiguous", 4, null,
        )
        assertTrue(needsChoice.summary().contains("4"))
        assertTrue(needsChoice.summary().contains("wyboru transakcji"))
    }
}
