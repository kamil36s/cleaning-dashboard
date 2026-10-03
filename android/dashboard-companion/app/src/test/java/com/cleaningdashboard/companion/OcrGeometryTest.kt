package com.cleaningdashboard.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OcrGeometryTest {
    @Test
    fun normalizesLineBoxAgainstImageDimensions() {
        val box = requireNotNull(OcrGeometry.normalizedBox(100, 200, 500, 300, 1000, 2000))
        assertEquals(0.1, box.x, 0.0001)
        assertEquals(0.1, box.y, 0.0001)
        assertEquals(0.4, box.width, 0.0001)
        assertEquals(0.05, box.height, 0.0001)
    }

    @Test
    fun rejectsEmptyOrInvalidBoxes() {
        assertNull(OcrGeometry.normalizedBox(5, 5, 5, 9, 100, 100))
        assertNull(OcrGeometry.normalizedBox(1, 1, 2, 2, 0, 100))
    }
}
