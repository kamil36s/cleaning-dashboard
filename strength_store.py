import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")

DEFAULT_XP_CONFIG = {
    "qualitySet": 10,
    "overTargetSet": 2,
    "microWorkout": 20,
    "repPr": 25,
    "totalRepPr": 25,
    "weightPr": 50,
    "absWeeklyMinimum": 50,
    "allMinimum": 100,
    "weeklyTarget": 150,
}

LEGACY_EXERCISE_MAP = {
    "dumbbell-floor-press": "dumbbell-floor-press-v2",
    "bent-over-dumbbell-row": "bent-over-dumbbell-row-v2",
    "goblet-squat": "goblet-squat-v2",
    "dumbbell-lateral-raise": "dumbbell-lateral-raise-v2",
    "hammer-curl": "hammer-curl-v2",
    "overhead-dumbbell-triceps-extension": "overhead-triceps-extension-v2",
    "reverse-crunch": "reverse-crunch-v2",
    "dead-bug": "dead-bug-v2",
    "push-up": "push-up-v2",
    "dumbbell-romanian-deadlift": "dumbbell-rdl-v2",
    "standing-dumbbell-overhead-press": "standing-dumbbell-press-v2",
    "dumbbell-pullover-floor": "dumbbell-pullover-floor-v2",
    "lying-dumbbell-triceps-extension": "lying-triceps-extension-v2",
    "weighted-crunch": "weighted-dumbbell-crunch",
    "side-plank": "side-plank-v2",
    "supinating-dumbbell-curl": "supinating-dumbbell-curl-v2",
    "bent-over-reverse-fly": "bent-over-reverse-fly-v2",
    "plank-shoulder-tap": "plank-shoulder-tap-v2",
    "long-lever-plank": "long-lever-plank-v2",
}

LEGACY_PRIMARY_MUSCLES = {
    "supinating-dumbbell-curl": "biceps",
    "bent-over-reverse-fly": "shoulders",
    "plank-shoulder-tap": "abs",
    "long-lever-plank": "abs",
}


class StrengthError(ValueError):
    def __init__(self, message, code="invalid_strength_request", status=400):
        super().__init__(message)
        self.code = code
        self.status = status

    def as_payload(self):
        return {"error": str(self), "code": self.code}


MUSCLE_GROUPS = (
    {"id": "abs", "label": "ABS / Core", "minimum": 6, "target": 10, "maximum": 14, "priority": 100},
    {"id": "chest", "label": "Chest", "minimum": 4, "target": 8, "maximum": 12, "priority": 60},
    {"id": "back", "label": "Back", "minimum": 4, "target": 8, "maximum": 12, "priority": 65},
    {"id": "legs", "label": "Legs", "minimum": 4, "target": 8, "maximum": 12, "priority": 55},
    {"id": "shoulders", "label": "Shoulders", "minimum": 4, "target": 8, "maximum": 12, "priority": 50},
    {"id": "biceps", "label": "Biceps", "minimum": 4, "target": 8, "maximum": 12, "priority": 45},
    {"id": "triceps", "label": "Triceps", "minimum": 4, "target": 8, "maximum": 12, "priority": 45},
)


EXERCISES = (
    {
        "id": "ab-wheel-kneeling", "name": "Ab Wheel Rollout from knees", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["ab-wheel"], "repMin": 5, "repMax": 12,
        "defaultSets": 3, "restSeconds": 90, "executionMode": "reps", "focus": "anti-extension",
        "techniqueVariantId": "ab-wheel-kneeling-controlled",
        "technique": "Zacznij w klęku, napnij pośladki i żebra, wyjedź tylko tak daleko, jak utrzymujesz stabilne lędźwie.",
        "why": "Kontrolowany rollout trenuje opieranie się przeprostowi tułowia i łatwo progresuje zakresem oraz powtórzeniami.",
    },
    {
        "id": "reverse-crunch-v2", "name": "Reverse Crunch", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["mat"], "repMin": 8, "repMax": 20,
        "defaultSets": 3, "restSeconds": 75, "executionMode": "reps", "focus": "trunk/pelvic flexion",
        "techniqueVariantId": "reverse-crunch-posterior-tilt",
        "technique": "Rozpocznij od tyłopochylenia miednicy; unieś kość krzyżową bez wymachu nogami.",
        "why": "To wariant z czytelnym zakresem progresji, który nie wymaga dodatkowego sprzętu.",
    },
    {
        "id": "weighted-dumbbell-crunch", "name": "Weighted Dumbbell Crunch", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["dumbbell", "mat"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 90, "executionMode": "reps", "focus": "loaded trunk flexion",
        "techniqueVariantId": "weighted-crunch-chest-load",
        "technique": "Trzymaj hantel przy klatce, unoś łopatki bez zamiany ruchu w pełny sit-up.",
        "why": "Obciążenie pozwala stosować prostą progresję ciężaru i powtórzeń.",
    },
    {
        "id": "side-plank-v2", "name": "Side Plank", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["mat"], "repMin": 30, "repMax": 60,
        "defaultSets": 2, "restSeconds": 60, "executionMode": "seconds-per-side", "focus": "lateral stability",
        "techniqueVariantId": "side-plank-straight-body",
        "technique": "Utrzymaj prostą linię ciała i wykonaj tę samą pracę na obie strony.",
        "why": "Ćwiczenie rozwija boczną stabilność bez potrzeby dokładania dużej objętości.",
    },
    {
        "id": "suitcase-hold", "name": "Suitcase Hold / March", "primaryMuscle": "abs",
        "secondaryMuscles": ["shoulders"], "equipment": ["dumbbell"], "repMin": 30, "repMax": 60,
        "defaultSets": 2, "restSeconds": 75, "executionMode": "seconds-per-side", "focus": "anti-lateral-flexion",
        "techniqueVariantId": "suitcase-hold-static",
        "technique": "Stań wysoko z ciężarem po jednej stronie i nie pozwól tułowiowi się przechylić.",
        "why": "Jednostronny ciężar trenuje stabilność w bardzo prostym, krótkim formacie.",
    },
    {
        "id": "dead-bug-v2", "name": "Dead Bug", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["mat"], "repMin": 6, "repMax": 12,
        "defaultSets": 2, "restSeconds": 60, "executionMode": "reps-per-side", "focus": "core control",
        "techniqueVariantId": "dead-bug-controlled",
        "technique": "Utrzymuj lędźwie przy macie i ogranicz zakres, gdy tracisz kontrolę.",
        "why": "To spokojny wariant kontroli tułowia, użyteczny również w lżejszy dzień.",
    },
    {
        "id": "standing-alternating-dumbbell-curl", "name": "Standing Alternating Dumbbell Curl", "primaryMuscle": "biceps",
        "secondaryMuscles": [], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 120, "executionMode": "reps", "focus": "elbow flexion",
        "techniqueVariantId": "curl-continuous-alternating",
        "technique": "Jedna ręka podnosi hantel, gdy druga go opuszcza; tułów pozostaje spokojny.",
        "why": "Zakres 8–15 jest wygodny z regulowanymi hantlami i wspiera double progression.",
    },
    {
        "id": "hammer-curl-v2", "name": "Hammer Curl", "primaryMuscle": "biceps",
        "secondaryMuscles": [], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "neutral-grip elbow flexion",
        "techniqueVariantId": "hammer-curl-strict",
        "technique": "Utrzymuj neutralny chwyt i nieruchome ramiona.",
        "why": "Neutralny chwyt daje prostą alternatywę dla klasycznego curl bez zmiany sprzętu.",
    },
    {
        "id": "dumbbell-floor-press-v2", "name": "Dumbbell Floor Press", "primaryMuscle": "chest",
        "secondaryMuscles": ["triceps", "shoulders"], "equipment": ["dumbbells", "mat"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 150, "executionMode": "reps", "focus": "horizontal push",
        "techniqueVariantId": "floor-press-controlled",
        "technique": "Stabilizuj łopatki, opuszczaj pod kontrolą i nie odbijaj ramion od podłogi.",
        "why": "Wariant floor nie wymaga ławki i dobrze pasuje do domowego zestawu.",
    },
    {
        "id": "push-up-v2", "name": "Push-Up", "primaryMuscle": "chest",
        "secondaryMuscles": ["triceps", "shoulders", "abs"], "equipment": ["mat"], "repMin": 6, "repMax": 20,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "horizontal push",
        "techniqueVariantId": "push-up-standard",
        "technique": "Utrzymuj ciało w jednej linii i kontroluj zejście.",
        "why": "Pompka pozwala wykonać wartościową serię natychmiast, bez ustawiania obciążenia.",
    },
    {
        "id": "bent-over-dumbbell-row-v2", "name": "Bent-Over Dumbbell Row", "primaryMuscle": "back",
        "secondaryMuscles": ["biceps", "shoulders"], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 150, "executionMode": "reps", "focus": "horizontal pull",
        "techniqueVariantId": "row-bilateral-strict",
        "technique": "Utrzymuj stabilny skłon biodrowy i prowadź łokcie w stronę bioder.",
        "why": "Wiosłowanie pokrywa główny wzorzec przyciągania dostępnym sprzętem.",
    },
    {
        "id": "dumbbell-pullover-floor-v2", "name": "Dumbbell Pullover on Floor", "primaryMuscle": "back",
        "secondaryMuscles": ["chest", "triceps"], "equipment": ["dumbbell", "mat"], "repMin": 8, "repMax": 15,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "shoulder extension",
        "techniqueVariantId": "pullover-floor-controlled",
        "technique": "Kontroluj żebra i zatrzymaj zakres przed utratą stabilności lędźwi.",
        "why": "Wariant na podłodze uzupełnia przyciąganie bez ławki.",
    },
    {
        "id": "goblet-squat-v2", "name": "Goblet Squat", "primaryMuscle": "legs",
        "secondaryMuscles": ["abs"], "equipment": ["dumbbell"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 150, "executionMode": "reps", "focus": "squat",
        "techniqueVariantId": "goblet-squat-controlled",
        "technique": "Utrzymuj całą stopę na podłodze i kolana w linii palców.",
        "why": "Goblet squat jest prosty do ustawienia i nie wymaga stojaków.",
    },
    {
        "id": "dumbbell-rdl-v2", "name": "Dumbbell Romanian Deadlift", "primaryMuscle": "legs",
        "secondaryMuscles": ["back", "abs"], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 180, "executionMode": "reps", "focus": "hip hinge",
        "techniqueVariantId": "rdl-bilateral-controlled",
        "technique": "Cofaj biodra, utrzymuj hantle blisko nóg i neutralny kręgosłup.",
        "why": "RDL uzupełnia przysiad o wzorzec zawiasowy i progresuje obciążeniem.",
    },
    {
        "id": "standing-dumbbell-press-v2", "name": "Standing Dumbbell Overhead Press", "primaryMuscle": "shoulders",
        "secondaryMuscles": ["triceps", "abs"], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 150, "executionMode": "reps", "focus": "vertical push",
        "techniqueVariantId": "ohp-standing-strict",
        "technique": "Napnij pośladki i brzuch; nie odchylaj tułowia, by dokończyć powtórzenie.",
        "why": "Wyciskanie stojąc buduje siłę barków bez potrzeby ławki.",
    },
    {
        "id": "dumbbell-lateral-raise-v2", "name": "Dumbbell Lateral Raise", "primaryMuscle": "shoulders",
        "secondaryMuscles": [], "equipment": ["dumbbells"], "repMin": 10, "repMax": 20,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "shoulder abduction",
        "techniqueVariantId": "lateral-raise-strict",
        "technique": "Prowadź łokciami bez wzruszania barkami i kołysania tułowiem.",
        "why": "Wyższy zakres powtórzeń pomaga progresować mimo dużych skoków obciążenia hantli.",
    },
    {
        "id": "overhead-triceps-extension-v2", "name": "Overhead Dumbbell Triceps Extension", "primaryMuscle": "triceps",
        "secondaryMuscles": [], "equipment": ["dumbbell"], "repMin": 8, "repMax": 15,
        "defaultSets": 3, "restSeconds": 120, "executionMode": "reps", "focus": "elbow extension",
        "techniqueVariantId": "triceps-extension-standing",
        "technique": "Utrzymuj żebra nad miednicą i łokcie skierowane możliwie w przód.",
        "why": "Jeden hantel wystarcza do prostego, izolowanego ruchu tricepsa.",
    },
    {
        "id": "lying-triceps-extension-v2", "name": "Lying Dumbbell Triceps Extension", "primaryMuscle": "triceps",
        "secondaryMuscles": [], "equipment": ["dumbbells", "mat"], "repMin": 8, "repMax": 15,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "elbow extension",
        "techniqueVariantId": "triceps-extension-floor",
        "technique": "Utrzymuj ramiona stabilnie i opuszczaj hantle bez rozsuwania łokci.",
        "why": "Wariant na podłodze oferuje alternatywę bez ławki.",
    },
    {
        "id": "supinating-dumbbell-curl-v2", "name": "Supinating Dumbbell Curl", "primaryMuscle": "biceps",
        "secondaryMuscles": [], "equipment": ["dumbbells"], "repMin": 8, "repMax": 15,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "supinating elbow flexion",
        "techniqueVariantId": "supinating-curl-strict",
        "technique": "Zacznij neutralnie, obracaj dłoń podczas uginania i nie kołysz tułowiem.",
        "why": "Osobny wariant techniczny zachowuje własną, porównywalną historię progresji.",
    },
    {
        "id": "bent-over-reverse-fly-v2", "name": "Bent-Over Reverse Fly", "primaryMuscle": "shoulders",
        "secondaryMuscles": ["back"], "equipment": ["dumbbells"], "repMin": 10, "repMax": 20,
        "defaultSets": 2, "restSeconds": 120, "executionMode": "reps", "focus": "rear delts / upper back",
        "techniqueVariantId": "reverse-fly-strict",
        "technique": "Utrzymuj stabilny hip hinge, lekki ciężar i prowadź ruch łokciami bez zamachu.",
        "why": "Wysoki zakres powtórzeń ułatwia progresję przy ograniczonych skokach obciążenia.",
    },
    {
        "id": "plank-shoulder-tap-v2", "name": "Plank Shoulder Tap", "primaryMuscle": "abs",
        "secondaryMuscles": ["shoulders"], "equipment": ["mat"], "repMin": 6, "repMax": 12,
        "defaultSets": 2, "restSeconds": 60, "executionMode": "reps-per-side", "focus": "anti-rotation",
        "techniqueVariantId": "plank-shoulder-tap-controlled",
        "technique": "Utrzymuj szeroki podpór i nieruchomą miednicę podczas zmian dłoni.",
        "why": "To krótki wariant anti-rotation, który nie wymaga dodatkowego sprzętu.",
    },
    {
        "id": "long-lever-plank-v2", "name": "Long-Lever Plank", "primaryMuscle": "abs",
        "secondaryMuscles": [], "equipment": ["mat"], "repMin": 15, "repMax": 45,
        "defaultSets": 2, "restSeconds": 75, "executionMode": "seconds", "focus": "anti-extension",
        "techniqueVariantId": "long-lever-plank-ppt",
        "technique": "Ustaw łokcie przed barkami, podwiń miednicę i zakończ serię przed utratą pozycji.",
        "why": "Dłuższa dźwignia pozwala progresować trudność bez dokładania ciężaru.",
    },
)


TECHNIQUE_VARIANTS = (
    ("curl-continuous-alternating", "standing-alternating-dumbbell-curl", "Continuous alternating", "curl-continuous-alternating", "Jedna ręka unosi, gdy druga opuszcza."),
    ("curl-full-rep-alternating", "standing-alternating-dumbbell-curl", "Full rep right, then left", "curl-full-rep-alternating", "Pełne powtórzenie jednej ręki, potem drugiej."),
)


class StrengthStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS strength_exercises (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        primary_muscle TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS strength_technique_variants (
                        id TEXT PRIMARY KEY,
                        exercise_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        comparable_key TEXT NOT NULL,
                        description TEXT,
                        FOREIGN KEY(exercise_id) REFERENCES strength_exercises(id)
                    );
                    CREATE TABLE IF NOT EXISTS strength_sessions (
                        id TEXT PRIMARY KEY,
                        started_at INTEGER NOT NULL,
                        ended_at INTEGER,
                        mode TEXT NOT NULL,
                        planned_duration_minutes INTEGER,
                        completed INTEGER NOT NULL DEFAULT 0,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE TABLE IF NOT EXISTS strength_sets (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        exercise_id TEXT NOT NULL,
                        technique_variant_id TEXT NOT NULL,
                        completed_at INTEGER NOT NULL,
                        reps INTEGER,
                        duration_seconds INTEGER,
                        load_kg REAL,
                        plates_weight_kg REAL,
                        load_label TEXT NOT NULL,
                        load_status TEXT NOT NULL,
                        rir INTEGER,
                        effort TEXT,
                        set_type TEXT NOT NULL,
                        quality INTEGER NOT NULL,
                        technique_accepted INTEGER NOT NULL DEFAULT 1,
                        stop_reason TEXT,
                        rest_seconds INTEGER,
                        notes TEXT,
                        FOREIGN KEY(session_id) REFERENCES strength_sessions(id),
                        FOREIGN KEY(exercise_id) REFERENCES strength_exercises(id),
                        FOREIGN KEY(technique_variant_id) REFERENCES strength_technique_variants(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_strength_sets_completed ON strength_sets(completed_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_strength_sets_exercise ON strength_sets(exercise_id, technique_variant_id, completed_at DESC);
                    CREATE TABLE IF NOT EXISTS strength_weekly_targets (
                        muscle_group TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        minimum_sets INTEGER NOT NULL,
                        target_sets INTEGER NOT NULL,
                        maximum_sets INTEGER NOT NULL,
                        priority INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS strength_equipment_items (
                        id TEXT PRIMARY KEY,
                        item_type TEXT NOT NULL,
                        name TEXT NOT NULL,
                        quantity INTEGER NOT NULL,
                        measured_weight_kg REAL,
                        nominal_weight_kg REAL,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE TABLE IF NOT EXISTS strength_personal_records (
                        id TEXT PRIMARY KEY,
                        set_id TEXT NOT NULL,
                        exercise_id TEXT NOT NULL,
                        technique_variant_id TEXT NOT NULL,
                        record_type TEXT NOT NULL,
                        value REAL NOT NULL,
                        created_at INTEGER NOT NULL,
                        UNIQUE(set_id, record_type),
                        FOREIGN KEY(set_id) REFERENCES strength_sets(id)
                    );
                    CREATE TABLE IF NOT EXISTS strength_xp_events (
                        id TEXT PRIMARY KEY,
                        set_id TEXT,
                        session_id TEXT,
                        event_type TEXT NOT NULL,
                        points INTEGER NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS strength_recovery_reports (
                        id TEXT PRIMARY KEY,
                        muscle_group TEXT NOT NULL,
                        soreness INTEGER NOT NULL,
                        reported_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS strength_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );
                    """
                )
                for item in MUSCLE_GROUPS:
                    connection.execute(
                        """INSERT INTO strength_weekly_targets
                           (muscle_group, label, minimum_sets, target_sets, maximum_sets, priority)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(muscle_group) DO NOTHING""",
                        (item["id"], item["label"], item["minimum"], item["target"], item["maximum"], item["priority"]),
                    )
                for exercise in EXERCISES:
                    connection.execute(
                        """INSERT INTO strength_exercises (id, name, primary_muscle, payload_json)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                           primary_muscle=excluded.primary_muscle, payload_json=excluded.payload_json""",
                        (exercise["id"], exercise["name"], exercise["primaryMuscle"], json.dumps(exercise, ensure_ascii=False)),
                    )
                    variant = exercise["techniqueVariantId"]
                    connection.execute(
                        """INSERT INTO strength_technique_variants
                           (id, exercise_id, name, comparable_key, description)
                           VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                        (variant, exercise["id"], "Standard", variant, exercise["technique"]),
                    )
                for variant in TECHNIQUE_VARIANTS:
                    connection.execute(
                        """INSERT INTO strength_technique_variants
                           (id, exercise_id, name, comparable_key, description)
                           VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                           name=excluded.name, comparable_key=excluded.comparable_key,
                           description=excluded.description""",
                        variant,
                    )
                # A canonical exercise may be added after an earlier legacy import. Re-link the
                # preserved sets instead of leaving a duplicate card in the exercise library.
                for legacy_id, canonical_id in LEGACY_EXERCISE_MAP.items():
                    canonical = next((item for item in EXERCISES if item["id"] == canonical_id), None)
                    if not canonical:
                        continue
                    connection.execute(
                        "UPDATE strength_sets SET exercise_id=?, technique_variant_id=? WHERE exercise_id=?",
                        (canonical_id, canonical["techniqueVariantId"], f"legacy-{legacy_id}"),
                    )
                    connection.execute("UPDATE strength_exercises SET active=0 WHERE id=?", (f"legacy-{legacy_id}",))
                equipment = (
                    ("handle-a", "dumbbell_handle", "Handle A", 1, None, None, {"calibrated": False}),
                    ("handle-b", "dumbbell_handle", "Handle B", 1, None, None, {"calibrated": False}),
                    ("plate-2-5", "plate", "Plate 2.5 kg", 8, None, 2.5, {}),
                    ("plate-1-25", "plate", "Plate 1.25 kg", 4, None, 1.25, {}),
                    ("collars", "collar", "Collars / nuts", 4, None, None, {"calibrated": False}),
                    ("ab-wheel", "ab_wheel", "Ab Wheel", 1, None, None, {}),
                    ("mat", "mat", "Exercise mat", 1, None, None, {}),
                )
                for row in equipment:
                    connection.execute(
                        """INSERT INTO strength_equipment_items
                           (id, item_type, name, quantity, measured_weight_kg, nominal_weight_kg, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                        (*row[:-1], json.dumps(row[-1], ensure_ascii=False)),
                    )
                connection.execute(
                    "INSERT INTO strength_settings (key, value_json) VALUES ('xp_config', ?) ON CONFLICT(key) DO NOTHING",
                    (json.dumps(DEFAULT_XP_CONFIG),),
                )
                self._seed_baseline(connection)
                connection.commit()
            self._initialized = True

    def _seed_baseline(self, connection):
        session_id = "baseline-biceps-2026-09-10"
        timestamp = int(datetime(2026, 9, 10, 12, 0, tzinfo=WARSAW).timestamp() * 1000)
        connection.execute(
            """INSERT INTO strength_sessions
               (id, started_at, ended_at, mode, planned_duration_minutes, completed, metadata_json)
               VALUES (?, ?, ?, 'baseline_import', NULL, 1, ?)
               ON CONFLICT(id) DO NOTHING""",
            (session_id, timestamp, timestamp + 8 * 60 * 1000, json.dumps({"source": "manual baseline from 2026-09-10"})),
        )
        baseline = ((14, 1, None), (6, 2, "discomfort"), (6, 1, None))
        for index, (reps, rir, stop_reason) in enumerate(baseline, start=1):
            connection.execute(
                """INSERT INTO strength_sets
                   (id, session_id, exercise_id, technique_variant_id, completed_at, reps,
                    duration_seconds, load_kg, plates_weight_kg, load_label, load_status, rir,
                    effort, set_type, quality, technique_accepted, stop_reason, rest_seconds, notes)
                   VALUES (?, ?, 'standing-alternating-dumbbell-curl', 'curl-continuous-alternating',
                           ?, ?, NULL, NULL, 7.5, '7.5 kg plates + uncalibrated hardware',
                           'partial', ?, NULL, 'quality', 1, 1, ?, 90, ?)
                   ON CONFLICT(id) DO NOTHING""",
                (f"baseline-curl-set-{index}", session_id, timestamp + index * 2 * 60 * 1000, reps, rir, stop_reason, "Imported baseline"),
            )

    @staticmethod
    def _now_ms():
        return int(datetime.now(tz=WARSAW).timestamp() * 1000)

    @staticmethod
    def _week_bounds(reference=None):
        if reference:
            try:
                day = datetime.fromisoformat(str(reference)[:10]).date()
            except ValueError as exc:
                raise StrengthError("Invalid week date", "invalid_week") from exc
        else:
            day = datetime.now(tz=WARSAW).date()
        start_day = day - timedelta(days=day.weekday())
        end_day = start_day + timedelta(days=7)
        start = int(datetime.combine(start_day, datetime.min.time(), tzinfo=WARSAW).timestamp() * 1000)
        end = int(datetime.combine(end_day, datetime.min.time(), tzinfo=WARSAW).timestamp() * 1000)
        return start_day.isoformat(), start, end

    @staticmethod
    def _decode_json(value, fallback):
        try:
            return json.loads(value) if value else fallback
        except json.JSONDecodeError:
            return fallback

    def exercises(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM strength_exercises WHERE active=1 ORDER BY CASE primary_muscle WHEN 'abs' THEN 0 ELSE 1 END, name"
            ).fetchall()
            variants = connection.execute(
                "SELECT id, exercise_id, name, comparable_key, description FROM strength_technique_variants ORDER BY name"
            ).fetchall()
        by_exercise = {}
        for row in variants:
            item = dict(row)
            by_exercise.setdefault(item.pop("exercise_id"), []).append(item)
        result = []
        for row in rows:
            item = self._decode_json(row["payload_json"], {})
            item["techniqueVariants"] = by_exercise.get(item["id"], [])
            result.append(item)
        return result

    def start_session(self, payload):
        self.initialize()
        data = payload if isinstance(payload, dict) else {}
        session_id = str(data.get("id") or f"strength-{uuid.uuid4().hex}")
        started_at = int(data.get("startedAt") or self._now_ms())
        mode = str(data.get("mode") or "freestyle")[:40]
        duration = data.get("plannedDurationMinutes")
        duration = max(1, min(180, int(duration))) if duration not in (None, "") else None
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO strength_sessions
                   (id, started_at, mode, planned_duration_minutes, metadata_json)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                (session_id, started_at, mode, duration, json.dumps(metadata, ensure_ascii=False)),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM strength_sessions WHERE id=?", (session_id,)).fetchone()
        return self._session_payload(row)

    def complete_session(self, session_id, payload=None):
        self.initialize()
        safe_id = str(session_id or "").strip()
        if not safe_id:
            raise StrengthError("Session id is required", "missing_session")
        ended_at = int((payload or {}).get("endedAt") or self._now_ms())
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM strength_sessions WHERE id=?", (safe_id,)).fetchone()
            if not row:
                raise StrengthError("Strength session not found", "session_not_found", 404)
            connection.execute("UPDATE strength_sessions SET ended_at=?, completed=1 WHERE id=?", (ended_at, safe_id))
            quality_sets = connection.execute(
                "SELECT COUNT(*) AS count FROM strength_sets WHERE session_id=? AND quality=1", (safe_id,)
            ).fetchone()["count"]
            if quality_sets:
                points = self._xp_config(connection)["microWorkout"]
                event_id = f"session:{safe_id}:complete"
                connection.execute(
                    """INSERT OR IGNORE INTO strength_xp_events
                       (id, session_id, event_type, points, created_at) VALUES (?, ?, 'micro_workout', ?, ?)""",
                    (event_id, safe_id, points, ended_at),
                )
            connection.commit()
            row = connection.execute("SELECT * FROM strength_sessions WHERE id=?", (safe_id,)).fetchone()
        return self._session_payload(row)

    @staticmethod
    def _session_payload(row):
        if not row:
            return None
        payload = dict(row)
        payload["completed"] = bool(payload["completed"])
        payload["metadata"] = StrengthStore._decode_json(payload.pop("metadata_json"), {})
        return payload

    def save_set(self, payload):
        self.initialize()
        data = payload if isinstance(payload, dict) else {}
        set_id = str(data.get("id") or f"set-{uuid.uuid4().hex}")
        exercise_id = str(data.get("exerciseId") or "").strip()
        if not exercise_id:
            raise StrengthError("Exercise is required", "missing_exercise")
        completed_at = int(data.get("completedAt") or self._now_ms())
        reps = data.get("reps")
        duration = data.get("durationSeconds")
        reps = None if reps in (None, "") else max(0, min(9999, int(reps)))
        duration = None if duration in (None, "") else max(0, min(86400, int(duration)))
        if not (reps or duration):
            raise StrengthError("A completed set needs reps or duration", "empty_set")
        rir = data.get("rir")
        rir = None if rir in (None, "") else max(0, min(10, int(rir)))
        set_type = "warmup" if data.get("setType") == "warmup" else "quality"
        technique_accepted = data.get("techniqueAccepted") is not False
        quality = set_type == "quality" and technique_accepted
        load_status = str(data.get("loadStatus") or ("exact" if data.get("loadKg") not in (None, "") else "bodyweight"))
        if load_status not in {"exact", "partial", "bodyweight"}:
            raise StrengthError("Invalid load status", "invalid_load")
        load_kg = data.get("loadKg")
        load_kg = None if load_kg in (None, "") else round(max(0, float(load_kg)), 3)
        if load_status != "exact":
            load_kg = None
        plates = data.get("platesWeightKg")
        plates = None if plates in (None, "") else round(max(0, float(plates)), 3)
        technique_id = str(data.get("techniqueVariantId") or "").strip()
        session_id = str(data.get("sessionId") or "").strip() or None
        stop_reason = str(data.get("stopReason") or "").strip()[:80] or None
        now = self._now_ms()
        with self._lock, self._connect() as connection:
            exercise = connection.execute("SELECT payload_json FROM strength_exercises WHERE id=?", (exercise_id,)).fetchone()
            if not exercise:
                raise StrengthError("Exercise not found", "exercise_not_found", 404)
            exercise_data = self._decode_json(exercise["payload_json"], {})
            technique_id = technique_id or exercise_data.get("techniqueVariantId")
            variant = connection.execute(
                "SELECT comparable_key FROM strength_technique_variants WHERE id=? AND exercise_id=?",
                (technique_id, exercise_id),
            ).fetchone()
            if not variant:
                raise StrengthError("Technique variant does not match exercise", "invalid_technique")
            if session_id and not connection.execute("SELECT 1 FROM strength_sessions WHERE id=?", (session_id,)).fetchone():
                raise StrengthError("Strength session not found", "session_not_found", 404)
            existing = connection.execute("SELECT * FROM strength_sets WHERE id=?", (set_id,)).fetchone()
            if existing:
                return self._set_response(connection, existing, duplicate=True)
            load_label = str(data.get("loadLabel") or (f"{load_kg:g} kg" if load_kg is not None else "Bodyweight"))[:120]
            effort = str(data.get("effort") or "").strip()[:30] or None
            rest_seconds = data.get("restSeconds")
            rest_seconds = None if rest_seconds in (None, "") else max(0, min(3600, int(rest_seconds)))
            connection.execute(
                """INSERT INTO strength_sets
                   (id, session_id, exercise_id, technique_variant_id, completed_at, reps,
                    duration_seconds, load_kg, plates_weight_kg, load_label, load_status, rir,
                    effort, set_type, quality, technique_accepted, stop_reason, rest_seconds, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (set_id, session_id, exercise_id, technique_id, completed_at, reps, duration,
                 load_kg, plates, load_label, load_status, rir, effort, set_type, int(quality),
                 int(technique_accepted), stop_reason, rest_seconds, str(data.get("notes") or "").strip()[:1000] or None),
            )
            config = self._xp_config(connection)
            self._award_set_xp(connection, set_id, exercise_data["primaryMuscle"], completed_at, quality, config)
            self._detect_records(connection, set_id, exercise_id, technique_id, session_id, completed_at,
                                 reps, load_kg, load_label, load_status, quality, stop_reason, config)
            self._award_weekly_xp(connection, completed_at, config)
            connection.commit()
            row = connection.execute("SELECT * FROM strength_sets WHERE id=?", (set_id,)).fetchone()
            return self._set_response(connection, row)

    def _xp_config(self, connection):
        row = connection.execute("SELECT value_json FROM strength_settings WHERE key='xp_config'").fetchone()
        stored = self._decode_json(row["value_json"], {}) if row else {}
        return {key: max(0, min(1000, int(stored.get(key, value)))) for key, value in DEFAULT_XP_CONFIG.items()}

    def _award_set_xp(self, connection, set_id, muscle, completed_at, quality, config):
        if not quality:
            return
        _, week_start, week_end = self._week_bounds(datetime.fromtimestamp(completed_at / 1000, WARSAW).date().isoformat())
        target = connection.execute(
            "SELECT target_sets FROM strength_weekly_targets WHERE muscle_group=?", (muscle,)
        ).fetchone()
        previous_count = connection.execute(
            """SELECT COUNT(*) AS count FROM strength_sets s
               JOIN strength_exercises e ON e.id=s.exercise_id
               WHERE s.quality=1 AND e.primary_muscle=? AND s.completed_at>=? AND s.completed_at<?""",
            (muscle, week_start, week_end),
        ).fetchone()["count"]
        points = config["qualitySet"] if previous_count <= int(target["target_sets"] if target else 8) else config["overTargetSet"]
        connection.execute(
            """INSERT OR IGNORE INTO strength_xp_events
               (id, set_id, event_type, points, created_at) VALUES (?, ?, 'quality_set', ?, ?)""",
            (f"set:{set_id}:quality", set_id, points, completed_at),
        )

    @staticmethod
    def _load_identity(load_kg, load_label, load_status):
        return f"kg:{load_kg:.3f}" if load_status == "exact" and load_kg is not None else f"label:{load_label.strip().lower()}"

    def _detect_records(self, connection, set_id, exercise_id, technique_id, session_id, completed_at,
                        reps, load_kg, load_label, load_status, quality, stop_reason, config):
        if not quality or stop_reason == "pain":
            return
        prior = connection.execute(
            """SELECT * FROM strength_sets WHERE exercise_id=? AND technique_variant_id=?
               AND id<>? AND quality=1 AND completed_at<=? ORDER BY completed_at""",
            (exercise_id, technique_id, set_id, completed_at),
        ).fetchall()
        if not prior:
            return
        load_identity = self._load_identity(load_kg, load_label, load_status)
        comparable_load = [row for row in prior if self._load_identity(row["load_kg"], row["load_label"], row["load_status"]) == load_identity]
        records = []
        if reps is not None and comparable_load and reps > max(int(row["reps"] or 0) for row in comparable_load):
            records.append(("rep_pr", reps, config["repPr"]))
        if load_status == "exact" and load_kg is not None:
            exact = [float(row["load_kg"]) for row in prior if row["load_status"] == "exact" and row["load_kg"] is not None]
            if exact and load_kg > max(exact):
                records.append(("weight_pr", load_kg, config["weightPr"]))
            if reps is not None:
                volume = reps * load_kg
                previous_volumes = [float(row["load_kg"]) * int(row["reps"] or 0) for row in prior if row["load_status"] == "exact" and row["load_kg"] is not None]
                if previous_volumes and volume > max(previous_volumes):
                    records.append(("volume_pr", volume, 0))
        if session_id and reps is not None:
            current_total = connection.execute(
                """SELECT COALESCE(SUM(reps), 0) AS total FROM strength_sets
                   WHERE session_id=? AND exercise_id=? AND technique_variant_id=? AND quality=1
                   AND ((load_status='exact' AND load_kg=?) OR (load_status<>'exact' AND lower(load_label)=lower(?)))""",
                (session_id, exercise_id, technique_id, load_kg, load_label),
            ).fetchone()["total"]
            previous_totals = connection.execute(
                """SELECT COALESCE(SUM(reps), 0) AS total FROM strength_sets
                   WHERE session_id IS NOT NULL AND session_id<>? AND exercise_id=? AND technique_variant_id=? AND quality=1
                   AND ((load_status='exact' AND load_kg=?) OR (load_status<>'exact' AND lower(load_label)=lower(?)))
                   GROUP BY session_id""",
                (session_id, exercise_id, technique_id, load_kg, load_label),
            ).fetchall()
            if previous_totals and current_total > max(int(row["total"] or 0) for row in previous_totals):
                records.append(("total_rep_pr", current_total, config["totalRepPr"]))
        for record_type, value, points in records:
            connection.execute(
                """INSERT OR IGNORE INTO strength_personal_records
                   (id, set_id, exercise_id, technique_variant_id, record_type, value, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"pr:{set_id}:{record_type}", set_id, exercise_id, technique_id, record_type, value, completed_at),
            )
            if points:
                connection.execute(
                    """INSERT OR IGNORE INTO strength_xp_events
                       (id, set_id, event_type, points, created_at) VALUES (?, ?, ?, ?, ?)""",
                    (f"set:{set_id}:{record_type}", set_id, record_type, points, completed_at),
                )

    def _award_weekly_xp(self, connection, completed_at, config):
        week, start, end = self._week_bounds(datetime.fromtimestamp(completed_at / 1000, WARSAW).date().isoformat())
        rows = connection.execute(
            """SELECT t.muscle_group, t.minimum_sets, t.target_sets, COUNT(s.id) AS sets
               FROM strength_weekly_targets t
               LEFT JOIN strength_exercises e ON e.primary_muscle=t.muscle_group
               LEFT JOIN strength_sets s ON s.exercise_id=e.id AND s.quality=1
                    AND s.completed_at>=? AND s.completed_at<?
               GROUP BY t.muscle_group""", (start, end)
        ).fetchall()
        by_group = {row["muscle_group"]: row for row in rows}
        events = []
        if int(by_group.get("abs", {"sets": 0})["sets"]) >= int(by_group.get("abs", {"minimum_sets": 99})["minimum_sets"]):
            events.append(("abs_minimum", config["absWeeklyMinimum"]))
        if rows and all(int(row["sets"]) >= int(row["minimum_sets"]) for row in rows):
            events.append(("all_minimum", config["allMinimum"]))
        if rows and all(int(row["sets"]) >= int(row["target_sets"]) for row in rows):
            events.append(("weekly_target", config["weeklyTarget"]))
        for event_type, points in events:
            connection.execute(
                """INSERT OR IGNORE INTO strength_xp_events
                   (id, event_type, points, created_at) VALUES (?, ?, ?, ?)""",
                (f"week:{week}:{event_type}", event_type, points, completed_at),
            )

    def _set_response(self, connection, row, duplicate=False):
        item = dict(row)
        for key in ("quality", "technique_accepted"):
            item[key] = bool(item[key])
        records = [dict(record) for record in connection.execute(
            "SELECT record_type, value FROM strength_personal_records WHERE set_id=? ORDER BY record_type", (item["id"],)
        ).fetchall()]
        xp = connection.execute("SELECT COALESCE(SUM(points), 0) AS points FROM strength_xp_events WHERE set_id=?", (item["id"],)).fetchone()["points"]
        return {"set": item, "records": records, "xpAwarded": int(xp), "duplicate": duplicate}

    def weekly_scoreboard(self, reference=None):
        self.initialize()
        week, start, end = self._week_bounds(reference)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT t.*, COALESCE(COUNT(s.id), 0) AS completed_sets,
                          MAX(s.completed_at) AS last_trained
                   FROM strength_weekly_targets t
                   LEFT JOIN strength_exercises e ON e.primary_muscle=t.muscle_group
                   LEFT JOIN strength_sets s ON s.exercise_id=e.id AND s.quality=1
                        AND s.completed_at>=? AND s.completed_at<?
                   GROUP BY t.muscle_group ORDER BY t.priority DESC""",
                (start, end),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            count = int(item.pop("completed_sets"))
            item.update({
                "sets": count,
                "toMinimum": max(0, int(item["minimum_sets"]) - count),
                "toTarget": max(0, int(item["target_sets"]) - count),
                "progress": min(1.25, count / max(1, int(item["target_sets"]))),
            })
            result.append(item)
        return {"week": week, "groups": result}

    def _recovery(self, connection, now):
        result = []
        for group in MUSCLE_GROUPS:
            rows = connection.execute(
                """SELECT s.completed_at, s.rir FROM strength_sets s JOIN strength_exercises e ON e.id=s.exercise_id
                   WHERE e.primary_muscle=? AND s.quality=1 AND s.completed_at>=? ORDER BY s.completed_at DESC""",
                (group["id"], now - 48 * 60 * 60 * 1000),
            ).fetchall()
            sets24 = sum(1 for row in rows if row["completed_at"] >= now - 24 * 60 * 60 * 1000)
            failure = sum(1 for row in rows if row["rir"] is not None and int(row["rir"]) <= 1)
            report = connection.execute(
                "SELECT soreness FROM strength_recovery_reports WHERE muscle_group=? ORDER BY reported_at DESC LIMIT 1",
                (group["id"],),
            ).fetchone()
            soreness = int(report["soreness"]) if report else None
            if (sets24 >= 6 and failure >= 2) or (soreness is not None and soreness >= 4):
                status = "red"
            elif rows or (soreness is not None and soreness >= 2):
                status = "yellow"
            else:
                status = "green"
            result.append({
                "muscleGroup": group["id"], "label": group["label"], "status": status,
                "sets24h": sets24, "sets48h": len(rows), "recentRirZeroOrOne": failure,
                "soreness": soreness, "manualSelectionAllowed": True,
                "lastTrained": rows[0]["completed_at"] if rows else None,
            })
        return result

    def history(self, limit=100):
        self.initialize()
        safe_limit = max(1, min(1000, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT s.*, e.name AS exercise_name, e.primary_muscle, v.name AS technique_name
                   FROM strength_sets s JOIN strength_exercises e ON e.id=s.exercise_id
                   JOIN strength_technique_variants v ON v.id=s.technique_variant_id
                   ORDER BY s.completed_at DESC LIMIT ?""", (safe_limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def equipment(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM strength_equipment_items ORDER BY item_type, name").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._decode_json(item.pop("metadata_json"), {})
            result.append(item)
        return result

    def update_equipment(self, payload):
        self.initialize()
        items = (payload or {}).get("items")
        if not isinstance(items, list):
            raise StrengthError("Equipment items are required", "missing_equipment")
        with self._lock, self._connect() as connection:
            for item in items:
                item_id = str(item.get("id") or "")
                if not connection.execute("SELECT 1 FROM strength_equipment_items WHERE id=?", (item_id,)).fetchone():
                    raise StrengthError("Equipment item not found", "equipment_not_found", 404)
                measured = item.get("measuredWeightKg")
                measured = None if measured in (None, "") else round(max(0, float(measured)), 3)
                nominal = item.get("nominalWeightKg")
                nominal = None if nominal in (None, "") else round(max(0, float(nominal)), 3)
                quantity = max(0, min(100, int(item.get("quantity", 1))))
                connection.execute(
                    """UPDATE strength_equipment_items SET measured_weight_kg=?, nominal_weight_kg=?, quantity=? WHERE id=?""",
                    (measured, nominal, quantity, item_id),
                )
            connection.commit()
        return self.equipment()

    def report_recovery(self, payload):
        self.initialize()
        muscle = str((payload or {}).get("muscleGroup") or "")
        if muscle not in {item["id"] for item in MUSCLE_GROUPS}:
            raise StrengthError("Unknown muscle group", "invalid_muscle")
        soreness = max(0, min(5, int((payload or {}).get("soreness", 0))))
        reported_at = int((payload or {}).get("reportedAt") or self._now_ms())
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO strength_recovery_reports (id, muscle_group, soreness, reported_at) VALUES (?, ?, ?, ?)",
                (f"recovery-{uuid.uuid4().hex}", muscle, soreness, reported_at),
            )
            connection.commit()
        return {"muscleGroup": muscle, "soreness": soreness, "reportedAt": reported_at}

    def settings(self):
        self.initialize()
        with self._connect() as connection:
            return {"xp": self._xp_config(connection)}

    def update_settings(self, payload):
        self.initialize()
        supplied = (payload or {}).get("xp")
        if not isinstance(supplied, dict):
            raise StrengthError("XP settings are required", "missing_xp_settings")
        config = {key: max(0, min(1000, int(supplied.get(key, value)))) for key, value in DEFAULT_XP_CONFIG.items()}
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO strength_settings (key, value_json) VALUES ('xp_config', ?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json""",
                (json.dumps(config),),
            )
            connection.commit()
        return {"xp": config}

    def export_data(self):
        self.initialize()
        tables = {
            "sessions": "strength_sessions",
            "sets": "strength_sets",
            "targets": "strength_weekly_targets",
            "equipment": "strength_equipment_items",
            "records": "strength_personal_records",
            "xpEvents": "strength_xp_events",
            "recoveryReports": "strength_recovery_reports",
            "settings": "strength_settings",
        }
        with self._connect() as connection:
            return {
                "schemaVersion": 1,
                **{key: [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()]
                   for key, table in tables.items()},
            }

    def import_data(self, payload):
        self.initialize()
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise StrengthError("Unsupported Strength backup", "invalid_strength_backup")
        tables = (
            ("sessions", "strength_sessions"),
            ("sets", "strength_sets"),
            ("targets", "strength_weekly_targets"),
            ("equipment", "strength_equipment_items"),
            ("records", "strength_personal_records"),
            ("xpEvents", "strength_xp_events"),
            ("recoveryReports", "strength_recovery_reports"),
            ("settings", "strength_settings"),
        )
        counts = {}
        with self._lock, self._connect() as connection:
            for key, table in tables:
                allowed = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
                imported = 0
                for raw in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                    if not isinstance(raw, dict):
                        continue
                    row = {column: raw[column] for column in raw.keys() & allowed}
                    if not row:
                        continue
                    columns = list(row)
                    placeholders = ",".join("?" for _ in columns)
                    before = connection.total_changes
                    connection.execute(
                        f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                        tuple(row[column] for column in columns),
                    )
                    imported += connection.total_changes - before
                counts[key] = imported
            connection.commit()
        return counts

    def migrate_live_workout_history(self, workouts):
        """Copy legacy completed Strength executions without changing/deleting Live Workout data."""
        self.initialize()
        migrated_sessions = 0
        migrated_sets = 0
        with self._lock, self._connect() as connection:
            for workout in workouts or []:
                if not isinstance(workout, dict) or workout.get("workout_type") != "strength":
                    continue
                strength_data = workout.get("strength_data")
                if not isinstance(strength_data, dict):
                    continue
                raw_id = "".join(character for character in str(workout.get("id") or uuid.uuid4().hex) if character.isalnum() or character == "-")
                session_id = f"legacy-{raw_id}"
                started_at = int(workout.get("started_at") or self._now_ms())
                ended_at = workout.get("ended_at")
                if ended_at is None and workout.get("duration_seconds") is not None:
                    ended_at = started_at + int(float(workout.get("duration_seconds") or 0) * 1000)
                before = connection.total_changes
                connection.execute(
                    """INSERT OR IGNORE INTO strength_sessions
                       (id, started_at, ended_at, mode, planned_duration_minutes, completed, metadata_json)
                       VALUES (?, ?, ?, 'legacy_fbw', ?, ?, ?)""",
                    (session_id, started_at, ended_at, workout.get("planned_duration_minutes"),
                     int(workout.get("status") == "finished"), json.dumps({"liveWorkoutSessionId": workout.get("id")}, ensure_ascii=False)),
                )
                migrated_sessions += connection.total_changes - before
                sequence_index = 0
                for group in strength_data.get("exercises", []) if isinstance(strength_data.get("exercises"), list) else []:
                    if not isinstance(group, dict):
                        continue
                    legacy_id = str(group.get("exerciseId") or "legacy-exercise")
                    exercise_id = LEGACY_EXERCISE_MAP.get(legacy_id, f"legacy-{legacy_id}")
                    exercise_row = connection.execute("SELECT payload_json FROM strength_exercises WHERE id=?", (exercise_id,)).fetchone()
                    if not exercise_row:
                        primary = LEGACY_PRIMARY_MUSCLES.get(legacy_id, "abs" if group.get("section") == "core" else "back")
                        payload = {
                            "id": exercise_id, "name": legacy_id.replace("-", " ").title(), "primaryMuscle": primary,
                            "secondaryMuscles": [], "equipment": [], "repMin": 1, "repMax": 30,
                            "defaultSets": max(1, int(group.get("plannedSets") or 1)), "restSeconds": 90,
                            "executionMode": "reps", "focus": "legacy import", "techniqueVariantId": f"{exercise_id}-legacy",
                            "technique": "Wariant zachowany z wcześniejszego planu FBW.",
                            "why": "Historyczny wariant zachowany bez utraty wykonanych serii.",
                        }
                        connection.execute(
                            "INSERT OR IGNORE INTO strength_exercises (id, name, primary_muscle, payload_json) VALUES (?, ?, ?, ?)",
                            (exercise_id, payload["name"], primary, json.dumps(payload, ensure_ascii=False)),
                        )
                    exercise_payload = self._decode_json(
                        connection.execute("SELECT payload_json FROM strength_exercises WHERE id=?", (exercise_id,)).fetchone()["payload_json"], {}
                    )
                    technique_id = f"{exercise_id}-legacy" if exercise_id.startswith("legacy-") else exercise_payload.get("techniqueVariantId")
                    connection.execute(
                        """INSERT OR IGNORE INTO strength_technique_variants
                           (id, exercise_id, name, comparable_key, description) VALUES (?, ?, 'Legacy FBW', ?, ?)""",
                        (technique_id, exercise_id, technique_id, "Imported from the previous A/B trainer"),
                    )
                    sets = group.get("sets") if isinstance(group.get("sets"), list) else []
                    for set_index, item in enumerate(sets, start=1):
                        if not isinstance(item, dict) or item.get("skipped"):
                            continue
                        reps = item.get("actualReps")
                        duration = item.get("actualDuration")
                        if reps in (None, 0) and duration in (None, 0):
                            continue
                        sequence_index += 1
                        load = item.get("actualWeightPerDumbbellKg")
                        load_label = f"{load:g} kg per dumbbell · legacy estimate" if isinstance(load, (int, float)) else "Bodyweight"
                        load_status = "partial" if isinstance(load, (int, float)) else "bodyweight"
                        record_id = f"legacy-set-{raw_id}-{legacy_id}-{item.get('setNumber') or set_index}"
                        before = connection.total_changes
                        connection.execute(
                            """INSERT OR IGNORE INTO strength_sets
                               (id, session_id, exercise_id, technique_variant_id, completed_at, reps,
                                duration_seconds, load_kg, plates_weight_kg, load_label, load_status, rir,
                                effort, set_type, quality, technique_accepted, stop_reason, rest_seconds, notes)
                               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, 'quality', ?, ?, NULL, ?, ?)""",
                            (record_id, session_id, exercise_id, technique_id, started_at + sequence_index * 1000,
                             reps, duration, load_label, load_status, item.get("actualRir"),
                             int(item.get("techniqueAccepted") is not False), int(item.get("techniqueAccepted") is not False),
                             item.get("actualRest") or item.get("plannedRest"), "Migrated from legacy FBW; original record retained."),
                        )
                        migrated_sets += connection.total_changes - before
            connection.commit()
        return {"sessions": migrated_sessions, "sets": migrated_sets}

    def dashboard(self, reference=None):
        self.initialize()
        scoreboard = self.weekly_scoreboard(reference)
        now = self._now_ms()
        with self._connect() as connection:
            total_xp = int(connection.execute("SELECT COALESCE(SUM(points), 0) AS xp FROM strength_xp_events").fetchone()["xp"])
            quality_sets = int(connection.execute("SELECT COUNT(*) AS count FROM strength_sets WHERE quality=1").fetchone()["count"])
            recent_records = [dict(row) for row in connection.execute(
                """SELECT p.record_type, p.value, p.created_at, e.name AS exercise_name
                   FROM strength_personal_records p JOIN strength_exercises e ON e.id=p.exercise_id
                   ORDER BY p.created_at DESC LIMIT 6"""
            ).fetchall()]
            recovery = self._recovery(connection, now)
            history = self.history(30)
            xp_config = self._xp_config(connection)
            completed_sessions = int(connection.execute("SELECT COUNT(*) AS count FROM strength_sessions WHERE completed=1 AND mode<>'baseline_import'").fetchone()["count"])
            abs_sets = int(connection.execute(
                """SELECT COUNT(*) AS count FROM strength_sets s JOIN strength_exercises e ON e.id=s.exercise_id
                   WHERE s.quality=1 AND e.primary_muscle='abs'"""
            ).fetchone()["count"])
            event_types = {row["event_type"] for row in connection.execute("SELECT DISTINCT event_type FROM strength_xp_events").fetchall()}
        level_size = 250
        level = total_xp // level_size + 1
        group_by_id = {item["muscle_group"]: item for item in scoreboard["groups"]}
        recovery_by_id = {item["muscleGroup"]: item for item in recovery}
        candidates = sorted(
            scoreboard["groups"],
            key=lambda item: (
                recovery_by_id[item["muscle_group"]]["status"] == "red",
                item["toMinimum"] == 0,
                -int(item["priority"]),
                int(item["sets"]),
            ),
        )
        recommended_group = next((item for item in candidates if recovery_by_id[item["muscle_group"]]["status"] != "red"), candidates[0])
        exercises = self.exercises()
        group_exercises = [item for item in exercises if item["primaryMuscle"] == recommended_group["muscle_group"]]
        last_by_exercise = {}
        for item in history:
            last_by_exercise.setdefault(item["exercise_id"], item["completed_at"])
        recommended_exercise = min(group_exercises, key=lambda item: last_by_exercise.get(item["id"], 0))
        last_for_exercise = [item for item in history if item["exercise_id"] == recommended_exercise["id"]]
        previous_total = 0
        if last_for_exercise:
            latest_session = last_for_exercise[0]["session_id"]
            previous_total = sum(int(item["reps"] or 0) for item in last_for_exercise if item["session_id"] == latest_session)
        equipment_items = self.equipment()
        handle_weights = [
            item["measured_weight_kg"] for item in equipment_items
            if item["item_type"] == "dumbbell_handle"
        ]
        collars = [item for item in equipment_items if item["item_type"] == "collar"]
        equipment_calibrated = (
            len(handle_weights) >= 2
            and all(value is not None for value in handle_weights)
            and len({round(float(value), 3) for value in handle_weights}) == 1
            and bool(collars)
            and all(item["measured_weight_kg"] is not None for item in collars)
        )
        return {
            "week": scoreboard["week"], "scoreboard": scoreboard["groups"], "recovery": recovery,
            "xp": {"total": total_xp, "level": level, "current": total_xp % level_size, "next": level_size},
            "lifetimeQualitySets": quality_sets, "recentRecords": recent_records, "recentSets": history[:12],
            "quest": {
                "kind": "weekly_gap" if recommended_group["toMinimum"] else "progression",
                "muscleGroup": recommended_group["muscle_group"], "exerciseId": recommended_exercise["id"],
                "title": f"{recommended_group['label']} quest",
                "description": (f"Do minimum brakuje {recommended_group['toMinimum']} jakościowych serii."
                                if recommended_group["toMinimum"] else
                                (f"Spróbuj pobić ostatnie {previous_total} łącznych powtórzeń."
                                 if previous_total else "Zapisz jedną jakościową serię.")),
                "manualSelectionAllowed": True,
            },
            "equipmentCalibrated": equipment_calibrated,
            "targets": group_by_id,
            "xpConfig": xp_config,
            "achievements": [
                {"id": "first-set", "label": "FIRST SET", "unlocked": quality_sets >= 1},
                {"id": "first-micro", "label": "FIRST MICRO", "unlocked": completed_sessions >= 1},
                {"id": "abs-start", "label": "ABS START", "unlocked": abs_sets >= 10},
                {"id": "rep-hunter", "label": "REP HUNTER", "unlocked": bool({"rep_pr", "total_rep_pr"} & event_types)},
                {"id": "level-up", "label": "LEVEL UP", "unlocked": "weight_pr" in event_types},
                {"id": "consistency", "label": "CONSISTENCY", "unlocked": "all_minimum" in event_types},
                {"id": "100-sets", "label": "100 SETS", "unlocked": quality_sets >= 100},
            ],
        }
