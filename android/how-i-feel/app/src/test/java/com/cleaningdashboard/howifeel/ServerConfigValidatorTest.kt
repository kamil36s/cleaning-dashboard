package com.cleaningdashboard.howifeel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerConfigValidatorTest {
    @Test fun normalizesDashboardUrl() {
        assertEquals("http://192.168.1.20:8000", ServerConfigValidator.normalizeBaseUrl(" http://192.168.1.20:8000/ "))
    }

    @Test fun rejectsUrlWithoutHttpScheme() {
        assertThrows(IllegalArgumentException::class.java) { ServerConfigValidator.normalizeBaseUrl("192.168.1.20:8000") }
    }
}
