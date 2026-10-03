plugins {
    id("com.android.application")
}

android {
    namespace = "com.cleaningdashboard.stepssync"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.cleaningdashboard.stepssync"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.health.connect:connect-client:1.1.0-alpha12")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
}
