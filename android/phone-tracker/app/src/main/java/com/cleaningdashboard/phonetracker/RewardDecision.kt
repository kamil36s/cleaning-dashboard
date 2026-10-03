package com.cleaningdashboard.phonetracker

data class RewardDecision(val newMinutes: Int, val milestone: Int?, val fullyUnlocked: Boolean)

fun bonusDelta(highestNotified: Double, currentBonus: Double): Double? =
    (currentBonus-highestNotified).takeIf { it > 0.001 }

fun rewardDecision(sent: Int, unlocked: Int, baseline: Int, minimumIncrease: Int,
                   milestones: List<Int>, progress: Double): RewardDecision? {
    val safeBaseline = baseline.coerceAtLeast(1)
    val gain = unlocked - sent
    if (gain <= 0) return null
    val crossed = milestones.filter { mark ->
        sent * 100 / safeBaseline < mark && unlocked * 100 / safeBaseline >= mark
    }.maxOrNull()
    if (gain < minimumIncrease && crossed == null) return null
    return RewardDecision(gain,crossed,unlocked >= safeBaseline && progress >= 1.0)
}
