package com.cleaningdashboard.phonetracker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AccessBudgetTest {
    @Test fun bonusDoesNotBypassSessionLimit() {
        assertEquals("Session limit reached",accessBlockReason(false,false,15.0,15,31.0,46.0))
        assertEquals("Session cooldown",accessBlockReason(false,true,0.0,15,31.0,46.0))
        assertNull(accessBlockReason(false,false,0.0,15,31.0,46.0))
        assertEquals("Daily access used up",accessBlockReason(false,false,0.0,15,46.0,46.0))
    }
}
