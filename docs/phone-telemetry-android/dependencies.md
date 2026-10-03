# Suggested Dependencies

Use current stable versions in Android Studio rather than copying stale version numbers from this document.

## Core

- `androidx.core:core-ktx`
- `androidx.activity:activity-compose`
- `androidx.lifecycle:lifecycle-runtime-ktx`

## UI

- Compose BOM
- `androidx.compose.ui:ui`
- `androidx.compose.material3:material3`
- `androidx.compose.ui:ui-tooling-preview`

## Background work

- `androidx.work:work-runtime-ktx`

## Local storage

- `androidx.room:room-runtime`
- `androidx.room:room-ktx`
- `androidx.room:room-compiler`

## Serialization

- `org.jetbrains.kotlinx:kotlinx-serialization-json`

## Optional but useful later

- `androidx.datastore:datastore-preferences` for privacy settings
- `androidx.lifecycle:lifecycle-viewmodel-compose` if the permission screen grows
