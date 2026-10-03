package com.cleaningdashboard.phonetracker

import org.junit.Assert.*
import org.junit.Test

class RewardDecisionTest {
    @Test fun gainsAreFullMinutesAndDuplicateSyncsAreSilent() {
        assertEquals(5,rewardDecision(20,25,50,1,listOf(25,50,75,100),0.5)?.newMinutes)
        assertNull(rewardDecision(25,25,50,1,listOf(25,50,75,100),0.5))
        assertNull(rewardDecision(25,20,50,1,listOf(25,50,75,100),0.4))
    }

    @Test fun milestoneCombinesWithGain() {
        val decision = rewardDecision(24,25,50,5,listOf(25,50,75,100),0.5)
        assertEquals(50,decision?.milestone)
        assertEquals(1,decision?.newMinutes)
        assertFalse(decision?.fullyUnlocked ?: true)
    }

    @Test fun fullUnlockStillHasBaselineCap() {
        val decision = rewardDecision(45,50,50,1,listOf(25,50,75,100),1.0)
        assertTrue(decision?.fullyUnlocked ?: false)
        assertEquals(5,decision?.newMinutes)
    }

    @Test fun extraReadingSyncCombinesBlocksAndRollbackDoesNotRepeat() {
        assertEquals(4.0,bonusDelta(0.0,4.0) ?: -1.0,0.001)
        assertNull(bonusDelta(4.0,4.0))
        assertNull(bonusDelta(4.0,2.0))
        assertNull(bonusDelta(4.0,4.0))
        assertEquals(2.0,bonusDelta(4.0,6.0) ?: -1.0,0.001)
    }
}
