export const STRENGTH_STORAGE_KEY = "liveWorkout.strengthSession.v1";
export const PLAN_TRACKING_KEY = "liveWorkout.planTracking.v1";

export const MUSCLE_LABELS = {
  chest: "Klatka piersiowa",
  lats: "Najszerszy grzbietu",
  upper_back: "Górna część pleców",
  front_delts: "Przedni akton barku",
  lateral_delts: "Boczny akton barku",
  rear_delts: "Tylny akton barku",
  biceps: "Biceps",
  triceps: "Triceps",
  forearms: "Przedramiona",
  quads: "Czworogłowe uda",
  hamstrings: "Dwugłowe uda",
  glutes: "Pośladki",
  erector_spinae: "Prostowniki grzbietu",
  rectus_abdominis: "Mięsień prosty brzucha",
  obliques: "Mięśnie skośne brzucha",
  deep_core: "Głęboki core / TVA i stabilizatory",
};

export const CORE_FUNCTION_LABELS = {
  flexion: "Zgięcie tułowia",
  posterior_pelvic_tilt: "Tyłopochylenie miednicy",
  anti_extension: "Anti-extension",
  anti_rotation: "Anti-rotation",
  anti_lateral_flexion: "Anti-lateral flexion",
  bracing: "Brace 360°",
};

export const STRENGTH_GLOSSARY = {
  REP: "Jedno pełne powtórzenie ćwiczenia.",
  SERIA: "Grupa powtórzeń wykonywana przed odpoczynkiem.",
  RIR: "Reps In Reserve: ile poprawnych powtórzeń zostało jeszcze w zapasie. RIR 3 oznacza około 3 dalsze poprawne powtórzenia.",
  RPE: "Subiektywna trudność całej sesji w skali 1–10.",
  TEMPO: "Kolejno: sekundy opuszczania, pauzy i podnoszenia. 3-1-1 oznacza 3 s w dół, 1 s pauzy i 1 s w górę.",
  ROM: "Range of Motion, czyli kontrolowany zakres ruchu.",
  BRACE: "Napięcie tułowia 360°, a nie samo wciągnięcie brzucha.",
  "ANTI-ROTATION": "Tułów przeciwdziała rotacji zamiast ją wykonywać.",
  "ANTI-EXTENSION": "Core zapobiega nadmiernemu przeprostowi odcinka lędźwiowego.",
};

export const HOME_STRENGTH_EQUIPMENT = {
  dumbbells: {
    type: "spin-lock-adjustable",
    handles: 2,
    handleLengthCm: 36,
    diameterMm: 28,
    estimatedHandleWeightKg: 2.5,
    plates: [
      { weightKg: 2.5, count: 8 },
      { weightKg: 1.25, count: 4 },
    ],
  },
  mat: { available: true },
  bench: { available: false },
  cableMachine: { available: false },
  resistanceBands: { available: false },
};

export const DUMBBELL_LOADOUTS = {
  2.5: { platesPerSide: [], label: "sam gryf" },
  5: { platesPerSide: [1.25], label: "1.25 kg z każdej strony" },
  7.5: { platesPerSide: [2.5], label: "2.5 kg z każdej strony" },
  10: { platesPerSide: [2.5, 1.25], label: "2.5 + 1.25 kg z każdej strony" },
  12.5: { platesPerSide: [2.5, 2.5], label: "2 × 2.5 kg z każdej strony" },
  15: { platesPerSide: [2.5, 2.5, 1.25], label: "2 × 2.5 + 1.25 kg z każdej strony" },
};

export const STRENGTH_TUTORIALS = {
  "march-in-place": { videoId: "5OeMNRcjQQU", title: "Dynamic Warm Up - March in Place", source: "Special Olympics", tutorialMatch: "exact", fallbackQuery: "Special Olympics march in place warm up" },
  "cat-cow": { videoId: "PGDnZ-sCC_o", title: "Cat Cow Explained", source: "Doctor O'Donovan + physiotherapist", tutorialMatch: "exact", fallbackQuery: "cat cow proper technique physiotherapist" },
  "quadruped-thoracic-rotation": { videoId: "snzLuyYgbVI", title: "Thoracic Rotation in Quadruped", source: "AskDoctorJo", tutorialMatch: "exact", fallbackQuery: "AskDoctorJo thoracic rotation quadruped" },
  "bodyweight-hip-hinge": { videoId: "2W_gXhut5S8", title: "Hip Hinge", source: "Hinge Health", tutorialMatch: "exact", fallbackQuery: "Hinge Health hip hinge" },
  "bodyweight-squat": { videoId: "Ul2idJKmpAc", title: "Bodyweight Squats - Proper Form & Technique", source: "FITTR", tutorialMatch: "exact", fallbackQuery: "FITTR bodyweight squat proper form" },
  "scapular-push-up": { videoId: "S9NhochxIhY", title: "Scapular Push-Up", source: "Physical Therapy First", tutorialMatch: "exact", fallbackQuery: "scapular push up physical therapy technique" },
  "dead-bug-breathing": { videoId: "bxn9FBrt4-A", title: "How to do a Dead Bug", source: "NASM", tutorialMatch: "technique", appSpecificNote: "W naszej wersji utrzymaj lędźwie przy podłożu i wykonuj powolny wydech 4–6 s podczas prostowania kończyn.", fallbackQuery: "NASM dead bug proper form" },
  "dumbbell-floor-press": { videoId: "uUGDRwge4F8", title: "How To: Dumbbell Floor Press", source: "ScottHermanFitness", tutorialMatch: "exact", fallbackQuery: "Scott Herman dumbbell floor press" },
  "bent-over-dumbbell-row": { videoId: "DJfQN6xJL28", title: "How to do a Dumbbell Bent Over Row", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM dumbbell bent over row" },
  "goblet-squat": { videoId: "nfX7IFK9UNI", title: "Goblet Squat", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM goblet squat" },
  "dumbbell-lateral-raise": { videoId: "XPPfnSEATJA", title: "How to do a Dumbbell Lateral Raise", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM dumbbell lateral raise" },
  "hammer-curl": { videoId: "zC3nLlEvin4", title: "How To: Dumbbell Hammer Curl", source: "ScottHermanFitness", tutorialMatch: "exact", fallbackQuery: "Scott Herman dumbbell hammer curl" },
  "overhead-dumbbell-triceps-extension": { videoId: "-Vyt2QdsR7E", title: "Standing Dumbbell Triceps Extension", source: "ScottHermanFitness", tutorialMatch: "exact", fallbackQuery: "Scott Herman standing dumbbell triceps extension" },
  "reverse-crunch": { videoId: "XY8KzdDcMFg", title: "Reverse Crunch", source: "PureGym", tutorialMatch: "exact", appSpecificNote: "Akcentuj posterior pelvic tilt. Nie zamieniaj ruchu w wymachiwanie nogami.", fallbackQuery: "reverse crunch proper technique posterior pelvic tilt" },
  "dead-bug": { videoId: "bxn9FBrt4-A", title: "How to do a Dead Bug", source: "NASM", tutorialMatch: "exact", appSpecificNote: "W naszej wersji wydech trwa około 4–6 s podczas wyprostu.", fallbackQuery: "NASM dead bug" },
  "plank-shoulder-tap": { videoId: "jgQ49dXfznk", title: "Plank with Shoulder Taps", source: "Penn State Health", tutorialMatch: "exact", fallbackQuery: "Penn State plank shoulder taps" },
  "push-up": { videoId: "WDIpL0pjun0", title: "How to do a Push-Up - Proper Form & Technique", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM push up proper form" },
  "dumbbell-romanian-deadlift": { videoId: "aa57T45iFSE", title: "How to do a Dumbbell Romanian Deadlift", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM dumbbell Romanian deadlift" },
  "standing-dumbbell-overhead-press": { videoId: "bmy7tIopNt4", title: "Standing Dumbbell Shoulder Press - Tutorial + Tips", source: "Team Evolve", tutorialMatch: "exact", appSpecificNote: "Brace, napięte pośladki i żebra nad miednicą; bez odchylania tułowia.", fallbackQuery: "standing dumbbell shoulder press tutorial" },
  "dumbbell-pullover-floor": { videoId: "lBS8lJpfShc", secondaryVideoId: "tM-RjVia9AY", title: "Dumbbell Pullover on Floor", source: "FITTR", tutorialMatch: "exact", appSpecificNote: "Nasz wariant wykonuj na podłodze. Kontroluj żebra i lędźwie.", fallbackQuery: "dumbbell pullover on floor tutorial" },
  "supinating-dumbbell-curl": { videoId: "2TiEnyiDwfM", title: "Supinating Dumbbell Curl", source: "Catalyst Athletics", tutorialMatch: "exact", fallbackQuery: "Catalyst Athletics supinating dumbbell curl" },
  "bent-over-reverse-fly": { videoId: "3MKmYlhxgOo", title: "Reverse Fly Tutorial - Proper Form and Technique", source: "", tutorialMatch: "exact", fallbackQuery: "reverse fly dumbbell proper form technique" },
  "lying-dumbbell-triceps-extension": { videoId: "k05Cd02Tm8g", secondaryVideoId: "ir5PsbniVSc", title: "Dumbbell Skull Crusher / Lying Dumbbell Triceps Extension", source: "", tutorialMatch: "exact", appSpecificNote: "Nasz wariant jest wykonywany na podłodze, nie na ławce.", fallbackQuery: "dumbbell skull crusher floor lying triceps extension" },
  "weighted-crunch": { videoId: "TM_oL0UPgGM", title: "Weighted Crunch", source: "", tutorialMatch: "exact", appSpecificNote: "Trzymaj jeden hantel przy klatce. Wykonuj krótki crunch, nie pełny sit-up.", fallbackQuery: "dumbbell weighted crunch proper form" },
  "side-plank": { videoId: "44ND4bOB-T0", title: "Side Plank", source: "NASM", tutorialMatch: "exact", fallbackQuery: "NASM side plank" },
  "long-lever-plank": { videoId: "XM96fe7jAXE", title: "Long-Lever PPT Plank", source: "", tutorialMatch: "exact", appSpecificNote: "Łokcie ustaw dalej przed barkami. Utrzymaj tyłopochylenie miednicy i napięte pośladki.", fallbackQuery: "long lever posterior pelvic tilt plank" },
};

function exercise(id, config) {
  return Object.freeze({
    id,
    aliases: [],
    category: "strength",
    primaryMuscles: [],
    secondaryMuscles: [],
    equipment: [],
    weightPerDumbbellKg: null,
    dumbbellCount: 0,
    defaultSets: 1,
    repMin: null,
    repMax: null,
    durationMin: null,
    durationMax: null,
    restMin: 60,
    restMax: 60,
    rirTarget: null,
    tempo: null,
    surface: "standing",
    loadType: "bodyweight",
    executionMode: "reps",
    instructions: [],
    cues: [],
    commonMistakes: [],
    breathingInstructions: "Oddychaj swobodnie i nie wstrzymuj oddechu.",
    progressionNotes: "Progresuj dopiero przy zachowaniu dobrej techniki.",
    isCore: false,
    coreFunction: [],
    difficulty: "beginner",
    tutorial: STRENGTH_TUTORIALS[id] || null,
    ...config,
  });
}

export const EXERCISE_LIBRARY = Object.freeze({
  "march-in-place": exercise("march-in-place", { namePl: "Marsz w miejscu", nameEn: "March in Place", category: "warmup", durationMin: 60, durationMax: 60, restMin: 0, restMax: 0, executionMode: "timed", instructions: ["Stań wysoko i maszeruj w spokojnym rytmie.", "Pracuj naprzemiennie rękami i kolanami."], cues: ["WYSOKA SYLWETKA", "MIĘKKIE KROKI", "RÓWNY ODDECH"], commonMistakes: ["Kołysanie tułowiem", "Wstrzymywanie oddechu"] }),
  "bodyweight-hip-hinge": exercise("bodyweight-hip-hinge", { namePl: "Skłon biodrowy bez ciężaru", nameEn: "Bodyweight Hip Hinge", category: "warmup", repMin: 8, repMax: 8, restMin: 0, restMax: 0, instructions: ["Stań stabilnie, zmiękcz kolana.", "Cofnij biodra, utrzymując neutralne plecy.", "Wróć przez napięcie pośladków."], cues: ["BIODRA W TYŁ", "PLECY NEUTRALNE", "BRACE 360°"], commonMistakes: ["Przysiad zamiast hinge", "Zaokrąglanie lędźwi"] }),
  "bodyweight-squat": exercise("bodyweight-squat", { namePl: "Przysiad bez ciężaru", nameEn: "Bodyweight Squat", category: "warmup", primaryMuscles: ["quads", "glutes"], repMin: 8, repMax: 8, restMin: 0, restMax: 0, instructions: ["Ustaw stopy stabilnie.", "Usiądź między biodrami w kontrolowanym zakresie.", "Wróć bez zapadania kolan."], cues: ["CAŁA STOPA NA PODŁODZE", "KOLANA ŚLEDZĄ PALCE", "KONTROLOWANY DÓŁ"], commonMistakes: ["Odrywanie pięt", "Zapadanie kolan"] }),
  "cat-cow": exercise("cat-cow", { namePl: "Koci grzbiet i krowa", nameEn: "Cat-Cow", category: "warmup", repMin: 6, repMax: 6, restMin: 0, restMax: 0, surface: "mat", instructions: ["Ustaw dłonie pod barkami i kolana pod biodrami.", "Powoli zaokrąglaj i prostuj kręgosłup bez forsowania zakresu."], cues: ["RUCH KRĄG PO KRĘGU", "BEZ BÓLU", "ODDECH PROWADZI RUCH"], commonMistakes: ["Szarpanie szyją", "Forsowanie lędźwi"] }),
  "quadruped-thoracic-rotation": exercise("quadruped-thoracic-rotation", { namePl: "Rotacja piersiowa w klęku", nameEn: "Quadruped Thoracic Rotation", category: "warmup", repMin: 5, repMax: 5, restMin: 0, restMax: 0, surface: "mat", executionMode: "reps-per-side", instructions: ["Z klęku podpartego połóż jedną dłoń za głową.", "Obróć łokieć ku górze z odcinka piersiowego.", "Powtórz na obie strony."], cues: ["BIODRA SPOKOJNE", "ROTACJA Z GÓRY PLECÓW", "BEZ POŚPIECHU"], commonMistakes: ["Skręcanie bioder", "Ciągnięcie szyi"] }),
  "scapular-push-up": exercise("scapular-push-up", { namePl: "Pompka łopatkowa", nameEn: "Scapular Push-Up", category: "warmup", primaryMuscles: ["upper_back"], repMin: 8, repMax: 10, restMin: 0, restMax: 0, surface: "mat", instructions: ["Przyjmij podpór z prostymi łokciami.", "Zbliż łopatki, a następnie aktywnie odepchnij podłogę."], cues: ["ŁOKCIE PROSTE", "TYLKO ŁOPATKI", "BRZUCH NAPIĘTY"], commonMistakes: ["Uginanie łokci", "Zapadanie lędźwi"] }),
  "dead-bug-breathing": exercise("dead-bug-breathing", { namePl: "Dead bug z oddechem", nameEn: "Dead Bug Breathing", category: "warmup", primaryMuscles: ["deep_core"], repMin: 4, repMax: 4, restMin: 0, restMax: 0, surface: "mat", executionMode: "reps-per-side", instructions: ["Dociśnij lędźwie do maty.", "Prostuj przeciwległą rękę i nogę.", "Wydychaj powietrze 4–6 sekund podczas wyprostu."], cues: ["LĘDŹWIE PRZY MACIE", "WYDECH 4–6 S", "MAŁY KONTROLOWANY ZAKRES"], commonMistakes: ["Odrywanie lędźwi", "Zbyt szybki wydech"], breathingInstructions: "Długi 4–6 sekundowy wydech podczas każdego wyprostu." }),

  "dumbbell-floor-press": exercise("dumbbell-floor-press", { namePl: "Wyciskanie hantli na podłodze", nameEn: "Dumbbell Floor Press", primaryMuscles: ["chest", "triceps"], secondaryMuscles: ["front_delts"], equipment: ["dumbbells", "mat"], weightPerDumbbellKg: 7.5, dumbbellCount: 2, defaultSets: 2, repMin: 8, repMax: 12, restMin: 90, restMax: 120, rirTarget: "3", tempo: "3-0-1", surface: "mat", loadType: "two-dumbbells", instructions: ["Połóż się z ugiętymi nogami i ustaw hantle nad klatką.", "Stabilizuj łopatki i opuszczaj hantle przez 3 sekundy.", "Delikatnie dotknij tricepsem podłogi i wyciśnij bez zderzania hantli."], cues: ["ŁOPATKI STABILNE", "ŁOKCIE 30–60°", "OPUSZCZAJ 3 SEKUNDY"], commonMistakes: ["Łokcie pod kątem 90°", "Odbijanie ramion od podłogi", "Zderzanie hantli"], breathingInstructions: "Wdech w dół, wydech podczas wyciskania." }),
  "bent-over-dumbbell-row": exercise("bent-over-dumbbell-row", { namePl: "Wiosłowanie hantlami w opadzie", nameEn: "Bent-Over Dumbbell Row", primaryMuscles: ["lats", "upper_back"], secondaryMuscles: ["biceps", "rear_delts"], equipment: ["dumbbells"], weightPerDumbbellKg: 7.5, dumbbellCount: 2, defaultSets: 2, repMin: 8, repMax: 12, restMin: 90, restMax: 120, rirTarget: "3", tempo: "2-1-2", loadType: "two-dumbbells", instructions: ["Cofnij biodra do stabilnego hip hinge.", "Przyciągnij oba hantle w stronę bioder.", "Zatrzymaj ruch na sekundę i opuść bez utraty pozycji."], cues: ["BIODRA W TYŁ", "ŁOKCIE DO BIODER", "BEZ SZARPANIA"], commonMistakes: ["Zaokrąglone plecy", "Kołysanie tułowiem", "Wzruszanie barkami"], breathingInstructions: "Wydech przy przyciąganiu, spokojny wdech przy opuszczaniu." }),
  "goblet-squat": exercise("goblet-squat", { namePl: "Przysiad goblet", nameEn: "Goblet Squat", primaryMuscles: ["quads", "glutes"], secondaryMuscles: ["deep_core"], equipment: ["dumbbell"], weightPerDumbbellKg: 7.5, dumbbellCount: 1, defaultSets: 2, repMin: 8, repMax: 10, restMin: 120, restMax: 120, rirTarget: "3–4", tempo: "3-1-1", loadType: "one-dumbbell", instructions: ["Trzymaj jeden hantel przy klatce.", "Schodź przez 3 sekundy w kontrolowanym zakresie.", "Zatrzymaj się na sekundę i wstań, utrzymując całą stopę na podłodze."], cues: ["HANTEL PRZY KLATCE", "KOLANA ŚLEDZĄ PALCE", "NIE FORSUJ NÓG"], commonMistakes: ["Odrywanie pięt", "Zapadanie kolan", "Zbyt szybkie zejście"], progressionNotes: "Ze względu na cycling nie zwiększaj agresywnie objętości nóg." }),
  "dumbbell-lateral-raise": exercise("dumbbell-lateral-raise", { namePl: "Unoszenie hantli bokiem", nameEn: "Dumbbell Lateral Raise", primaryMuscles: ["lateral_delts"], secondaryMuscles: ["front_delts"], equipment: ["dumbbells"], weightPerDumbbellKg: 2.5, dumbbellCount: 2, defaultSets: 2, repMin: 12, repMax: 20, restMin: 60, restMax: 75, rirTarget: "2–3", loadType: "two-dumbbells", instructions: ["Stań stabilnie z lekko ugiętymi łokciami.", "Unieś hantle bokiem bez wzruszania barkami.", "Opuść powoli do pełnej kontroli."], cues: ["PROWADŹ ŁOKCIAMI", "BARKI DALEKO OD USZU", "BEZ ZAMACHU"], commonMistakes: ["Kołysanie tułowiem", "Wzruszanie barkami"], progressionNotes: "Skok 2.5→5 kg jest duży. Najpierw dodawaj powtórzenia, kontrolę, pauzę lub wolniejszą ekscentrykę." }),
  "hammer-curl": exercise("hammer-curl", { namePl: "Uginanie młotkowe", nameEn: "Hammer Curl", primaryMuscles: ["biceps", "forearms"], equipment: ["dumbbells"], weightPerDumbbellKg: 5, dumbbellCount: 2, defaultSets: 2, repMin: 10, repMax: 15, restMin: 60, restMax: 75, rirTarget: "2–3", loadType: "two-dumbbells", instructions: ["Trzymaj dłonie neutralnie.", "Ugnij łokcie bez przesuwania ramion do przodu.", "Opuść hantle pod kontrolą."], cues: ["ŁOKCIE PRZY TUŁOWIU", "NADGARSTKI NEUTRALNE", "BEZ KOŁYSANIA"], commonMistakes: ["Zarzucanie ciężaru", "Uciekanie łokci"] }),
  "overhead-dumbbell-triceps-extension": exercise("overhead-dumbbell-triceps-extension", { namePl: "Prostowanie hantla nad głową", nameEn: "Overhead Dumbbell Triceps Extension", primaryMuscles: ["triceps"], equipment: ["dumbbell"], weightPerDumbbellKg: 5, dumbbellCount: 1, defaultSets: 2, repMin: 10, repMax: 15, restMin: 60, restMax: 75, rirTarget: "2–3", loadType: "one-dumbbell", instructions: ["Obejmij jeden hantel obiema dłońmi nad głową.", "Ugnij łokcie bez rozsuwania ich na boki.", "Wyprostuj ramiona bez przeprostu lędźwi."], cues: ["ŻEBRA NAD MIEDNICĄ", "ŁOKCIE WĄSKO", "BRACE"], commonMistakes: ["Wyginanie lędźwi", "Rozsuwanie łokci"] }),
  "reverse-crunch": exercise("reverse-crunch", { namePl: "Odwrotny crunch", nameEn: "Reverse Crunch", category: "core", primaryMuscles: ["rectus_abdominis"], secondaryMuscles: ["deep_core"], defaultSets: 3, repMin: 8, repMax: 15, restMin: 60, restMax: 60, surface: "mat", isCore: true, coreFunction: ["flexion", "posterior_pelvic_tilt"], instructions: ["Połóż się na macie z biodrami i kolanami zgiętymi.", "Z wydechem skieruj żebra w dół i podwiń miednicę.", "Unieś kość krzyżową bez zamachu nogami."], cues: ["ŻEBRA W DÓŁ", "PODWIŃ MIEDNICĘ", "BEZ WYMACHU"], commonMistakes: ["Kołysanie nogami", "Zbyt duży zakres"], breathingInstructions: "Wydech → żebra w dół → tyłopochylenie miednicy → delikatne uniesienie kości krzyżowej." }),
  "dead-bug": exercise("dead-bug", { namePl: "Dead bug", nameEn: "Dead Bug", category: "core", primaryMuscles: ["deep_core"], defaultSets: 2, repMin: 6, repMax: 10, restMin: 45, restMax: 60, surface: "mat", executionMode: "reps-per-side", isCore: true, coreFunction: ["anti_extension", "bracing"], instructions: ["Dociśnij lędźwie do maty.", "Prostuj przeciwległą rękę i nogę tylko tak daleko, jak utrzymasz pozycję.", "Wróć i zmień stronę."], cues: ["LĘDŹWIE PRZY MACIE", "WYDECH 4–6 S", "ŻEBRA W DÓŁ"], commonMistakes: ["Odrywanie lędźwi", "Za duży zakres"], breathingInstructions: "Wydychaj 4–6 sekund podczas każdego wyprostu." }),
  "plank-shoulder-tap": exercise("plank-shoulder-tap", { namePl: "Plank z dotknięciem barku", nameEn: "Plank Shoulder Tap", category: "core", primaryMuscles: ["deep_core", "obliques"], defaultSets: 2, repMin: 6, repMax: 10, restMin: 60, restMax: 60, surface: "mat", executionMode: "reps-per-side", isCore: true, coreFunction: ["anti_rotation", "anti_extension"], instructions: ["Przyjmij szeroki, stabilny podpór.", "Oderwij jedną dłoń i dotknij przeciwnego barku.", "Utrzymaj miednicę możliwie nieruchomo."], cues: ["MIEDNICA SPOKOJNA", "ODPYCHAJ PODŁOGĘ", "WOLNE ZMIANY STRON"], commonMistakes: ["Kołysanie biodrami", "Zapadanie lędźwi"] }),

  "push-up": exercise("push-up", { namePl: "Pompka", nameEn: "Push-Up", primaryMuscles: ["chest", "triceps"], secondaryMuscles: ["front_delts", "deep_core"], defaultSets: 2, repMin: 8, repMax: 15, restMin: 90, restMax: 90, rirTarget: "2–3", tempo: "3-1-1 opcjonalnie", surface: "mat", instructions: ["Ustaw ciało w jednej linii.", "Zejdź klatką między dłonie z łokciami pod kontrolą.", "Odepchnij podłogę bez utraty brace."], cues: ["CIAŁO W JEDNEJ LINII", "ŁOKCIE 30–60°", "BRACE"], commonMistakes: ["Opadanie bioder", "Rozstawianie łokci"] }),
  "dumbbell-romanian-deadlift": exercise("dumbbell-romanian-deadlift", { namePl: "Martwy ciąg rumuński z hantlami", nameEn: "Dumbbell Romanian Deadlift", primaryMuscles: ["hamstrings", "glutes"], secondaryMuscles: ["erector_spinae", "forearms"], equipment: ["dumbbells"], weightPerDumbbellKg: 7.5, dumbbellCount: 2, defaultSets: 2, repMin: 8, repMax: 12, restMin: 120, restMax: 120, rirTarget: "3–4", loadType: "two-dumbbells", instructions: ["Zmiękcz kolana i cofnij biodra.", "Prowadź hantle blisko nóg z neutralnym kręgosłupem.", "Zatrzymaj ruch, gdy kończy się kontrolowany zakres biodra."], cues: ["BIODRA W TYŁ", "HANTLE BLISKO NÓG", "NEUTRALNE PLECY"], commonMistakes: ["Przysiad zamiast hinge", "Schodzenie poniżej kontrolowanego zakresu"], progressionNotes: "W wariancie LIGHT wykonaj 1–2 serie po 8 powtórzeń przy RIR 4." }),
  "standing-dumbbell-overhead-press": exercise("standing-dumbbell-overhead-press", { namePl: "Wyciskanie hantli nad głowę stojąc", nameEn: "Standing Dumbbell Overhead Press", primaryMuscles: ["front_delts", "triceps"], equipment: ["dumbbells"], weightPerDumbbellKg: 5, dumbbellCount: 2, defaultSets: 2, repMin: 8, repMax: 12, restMin: 90, restMax: 90, rirTarget: "3", loadType: "two-dumbbells", instructions: ["Stań stabilnie z hantlami przy barkach.", "Napnij pośladki i tułów.", "Wyciśnij nad głowę bez odchylania tułowia."], cues: ["ŻEBRA NAD MIEDNICĄ", "POŚLADKI NAPIĘTE", "BEZ ODCHYLANIA"], commonMistakes: ["Przeprost lędźwi", "Uciekanie żeber"] }),
  "dumbbell-pullover-floor": exercise("dumbbell-pullover-floor", { namePl: "Pullover hantlem na podłodze", nameEn: "Dumbbell Pullover on Floor", primaryMuscles: ["lats", "chest"], secondaryMuscles: ["triceps", "deep_core"], equipment: ["dumbbell", "mat"], weightPerDumbbellKg: 5, dumbbellCount: 1, defaultSets: 2, repMin: 10, repMax: 15, restMin: 90, restMax: 90, rirTarget: "3", surface: "mat", loadType: "one-dumbbell", instructions: ["Połóż się na podłodze i trzymaj jeden hantel nad klatką.", "Przenieś go za głowę tylko w kontrolowanym zakresie.", "Wróć, utrzymując żebra i lędźwie stabilnie."], cues: ["WARIANT NA PODŁODZE", "ŻEBRA W DÓŁ", "ŁOKCIE LEKKO UGIĘTE"], commonMistakes: ["Przeprost lędźwi", "Forsowanie zakresu barków"] }),
  "supinating-dumbbell-curl": exercise("supinating-dumbbell-curl", { namePl: "Uginanie hantli z supinacją", nameEn: "Supinating Dumbbell Curl", primaryMuscles: ["biceps"], secondaryMuscles: ["forearms"], equipment: ["dumbbells"], weightPerDumbbellKg: 5, dumbbellCount: 2, defaultSets: 2, repMin: 10, repMax: 15, restMin: 60, restMax: 75, rirTarget: "2–3", loadType: "two-dumbbells", executionMode: "alternating-reps", instructions: ["Zacznij z neutralnym chwytem.", "Podczas uginania obróć dłoń ku górze.", "Opuść bez kołysania tułowiem."], cues: ["ŁOKCIE SPOKOJNE", "OBRÓĆ DŁOŃ", "PEŁNA KONTROLA"], commonMistakes: ["Zarzucanie ciężaru", "Przesuwanie ramion"] }),
  "bent-over-reverse-fly": exercise("bent-over-reverse-fly", { namePl: "Odwrotne rozpiętki w opadzie", nameEn: "Bent-Over Reverse Fly", primaryMuscles: ["rear_delts", "upper_back"], equipment: ["dumbbells"], weightPerDumbbellKg: 2.5, dumbbellCount: 2, defaultSets: 2, repMin: 12, repMax: 20, restMin: 60, restMax: 75, rirTarget: "2–3", loadType: "two-dumbbells", instructions: ["Ustaw stabilny hip hinge.", "Unieś ramiona na boki, prowadząc łokciami.", "Opuść bez utraty pozycji tułowia."], cues: ["LEKKI CIĘŻAR", "PROWADŹ ŁOKCIAMI", "BEZ ZAMACHU"], commonMistakes: ["Wzruszanie barkami", "Kołysanie tułowiem"], progressionNotes: "Przed skokiem z 2.5 do 5 kg wykorzystaj zakres powtórzeń, tempo i pauzę." }),
  "lying-dumbbell-triceps-extension": exercise("lying-dumbbell-triceps-extension", { namePl: "Prostowanie hantli leżąc", nameEn: "Lying Dumbbell Triceps Extension", primaryMuscles: ["triceps"], equipment: ["dumbbells", "mat"], weightPerDumbbellKg: 2.5, dumbbellCount: 2, defaultSets: 2, repMin: 10, repMax: 15, restMin: 60, restMax: 75, rirTarget: "2–3", surface: "mat", loadType: "two-dumbbells", instructions: ["Połóż się na podłodze z hantlami nad barkami.", "Uginaj wyłącznie łokcie i opuszczaj hantle obok głowy.", "Wyprostuj ramiona bez przesuwania barków."], cues: ["WARIANT NA PODŁODZE", "RAMIONA STABILNE", "ŁOKCIE WĄSKO"], commonMistakes: ["Ruch całym ramieniem", "Rozsuwanie łokci"] }),
  "weighted-crunch": exercise("weighted-crunch", { namePl: "Crunch z obciążeniem", nameEn: "Weighted Crunch", category: "core", primaryMuscles: ["rectus_abdominis"], equipment: ["dumbbell", "mat"], weightPerDumbbellKg: 2.5, dumbbellCount: 1, defaultSets: 2, repMin: 10, repMax: 15, restMin: 60, restMax: 60, surface: "mat", loadType: "one-dumbbell", isCore: true, coreFunction: ["flexion"], instructions: ["Trzymaj jeden hantel przy klatce.", "Z wydechem oderwij łopatki od maty.", "Wróć powoli; nie wykonuj pełnego sit-upu."], cues: ["KRÓTKI CRUNCH", "ŻEBRA DO MIEDNICY", "NIE SIADAJ"], commonMistakes: ["Pełny sit-up", "Ciągnięcie szyi"] }),
  "side-plank": exercise("side-plank", { namePl: "Deska bokiem", nameEn: "Side Plank", category: "core", primaryMuscles: ["obliques", "deep_core"], defaultSets: 2, durationMin: 20, durationMax: 40, restMin: 45, restMax: 60, surface: "mat", executionMode: "timed-per-side", isCore: true, coreFunction: ["anti_lateral_flexion"], instructions: ["Ustaw łokieć pod barkiem i zbuduj prostą linię ciała.", "Unieś biodra i utrzymaj aktywny bok tułowia.", "Wykonaj obie strony osobno."], cues: ["ŁOKIEĆ POD BARKIEM", "BIODRA WYSOKO", "CIAŁO W LINII"], commonMistakes: ["Opadanie bioder", "Zapadanie barku"] }),
  "long-lever-plank": exercise("long-lever-plank", { namePl: "Deska z długą dźwignią", nameEn: "Long-Lever Plank", category: "core", primaryMuscles: ["deep_core", "rectus_abdominis"], defaultSets: 2, durationMin: 15, durationMax: 30, restMin: 60, restMax: 60, surface: "mat", executionMode: "timed", isCore: true, coreFunction: ["anti_extension", "bracing"], instructions: ["Ustaw łokcie nieco przed barkami.", "Podwiń miednicę i napnij pośladki.", "Utrzymaj żebra w dół bez zapadania lędźwi."], cues: ["ŁOKCIE PRZED BARKAMI", "PODWIŃ MIEDNICĘ", "POŚLADKI NAPIĘTE"], commonMistakes: ["Przeprost lędźwi", "Zbyt długa seria kosztem pozycji"] }),
});

export const WARMUP_V1 = Object.freeze([
  "march-in-place",
  "bodyweight-hip-hinge",
  "bodyweight-squat",
  "cat-cow",
  "quadruped-thoracic-rotation",
  "scapular-push-up",
  "dead-bug-breathing",
]);

export const STRENGTH_WORKOUTS = Object.freeze({
  A: {
    id: "strength-a",
    label: "Workout A",
    phase: "adaptation",
    warmupId: "warmup-v1",
    estimatedDurationMin: 45,
    estimatedDurationMax: 55,
    exerciseIds: ["dumbbell-floor-press", "bent-over-dumbbell-row", "goblet-squat", "dumbbell-lateral-raise", "hammer-curl", "overhead-dumbbell-triceps-extension", "reverse-crunch", "dead-bug", "plank-shoulder-tap"],
  },
  B: {
    id: "strength-b",
    label: "Workout B",
    phase: "adaptation",
    warmupId: "warmup-v1",
    estimatedDurationMin: 45,
    estimatedDurationMax: 55,
    exerciseIds: ["push-up", "dumbbell-romanian-deadlift", "standing-dumbbell-overhead-press", "dumbbell-pullover-floor", "supinating-dumbbell-curl", "bent-over-reverse-fly", "lying-dumbbell-triceps-extension", "weighted-crunch", "side-plank", "long-lever-plank"],
  },
});

export const STRENGTH_PLAN_SEED = Object.freeze([
  { id: "strength-adaptation-2026-09-05-a", date: "2026-09-05", workoutType: "strength", workoutId: "A", workoutVariant: "STANDARD", phase: "adaptation", status: "planned" },
  { id: "strength-adaptation-2026-09-07-b-light", date: "2026-09-07", workoutType: "strength", workoutId: "B", workoutVariant: "LIGHT", phase: "adaptation", status: "planned" },
  { id: "strength-adaptation-2026-09-12-a", date: "2026-09-12", workoutType: "strength", workoutId: "A", workoutVariant: "STANDARD", phase: "adaptation", status: "planned" },
  { id: "strength-adaptation-2026-09-14-b", date: "2026-09-14", workoutType: "strength", workoutId: "B", workoutVariant: "STANDARD", phase: "adaptation", status: "planned" },
]);

export function cloneStrengthPlan() {
  return STRENGTH_PLAN_SEED.map((item) => ({ ...item }));
}

export function isStrengthPlanEnabled(tracking) {
  return tracking?.strengthPlanEnabled !== false;
}

export function normalizeStrengthPlan(value) {
  const source = Array.isArray(value) ? value : cloneStrengthPlan();
  const seen = new Set();
  return source.filter((item) => item && !seen.has(String(item.id)) && /^\d{4}-\d{2}-\d{2}$/.test(String(item.date || ""))).map((item) => {
    seen.add(String(item.id));
    return {
      id: String(item.id),
      date: String(item.date),
      workoutType: "strength",
      workoutId: item.workoutId === "B" ? "B" : "A",
      workoutVariant: item.workoutVariant === "LIGHT" ? "LIGHT" : "STANDARD",
      phase: item.phase === "build" ? "build" : "adaptation",
      status: ["planned", "completed", "partial", "skipped"].includes(item.status) ? item.status : "planned",
    };
  });
}

export function workoutExercises(workoutId = "A", variant = "STANDARD") {
  const workout = STRENGTH_WORKOUTS[workoutId] || STRENGTH_WORKOUTS.A;
  return workout.exerciseIds.map((id) => {
    const base = EXERCISE_LIBRARY[id];
    if (variant === "LIGHT" && id === "dumbbell-romanian-deadlift") {
      return { ...base, defaultSets: 1, repMin: 8, repMax: 8, rirTarget: "4" };
    }
    return base;
  });
}

export function formatDumbbellLoad(weightPerDumbbellKg, dumbbellCount) {
  const weight = Number(weightPerDumbbellKg);
  const count = Number(dumbbellCount);
  if (!count || !Number.isFinite(weight)) return "Masa ciała";
  return `${count} × ${weight.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} kg`;
}

export function loadoutForWeight(weightPerDumbbellKg, equipment = HOME_STRENGTH_EQUIPMENT) {
  const nominal = Number(weightPerDumbbellKg);
  const preset = DUMBBELL_LOADOUTS[nominal] || DUMBBELL_LOADOUTS[2.5];
  const handleWeight = Number(equipment?.dumbbells?.estimatedHandleWeightKg ?? 2.5);
  const actualWeight = handleWeight + 2 * preset.platesPerSide.reduce((sum, plate) => sum + Number(plate), 0);
  return { ...preset, nominalWeight: nominal, handleWeight, actualWeight: Math.round(actualWeight * 100) / 100 };
}

export function classifyCalibrationSet({ actualRir, actualReps, repMin, targetRir }) {
  const rir = Number(actualRir);
  if (rir >= 5) return "TOO_LIGHT";
  if (rir <= 1 || Number(actualReps) < Number(repMin)) return "TOO_HEAVY";
  const target = Number(String(targetRir ?? "3").match(/\d+/)?.[0] || 3);
  return Math.abs(rir - target) <= 1 ? "GOOD" : rir > target ? "TOO_LIGHT" : "TOO_HEAVY";
}

export function getProgressionSuggestion(exercise, executions = []) {
  const completed = executions.filter((set) => !set.skipped);
  if (!exercise || completed.length < Number(exercise.defaultSets || 1)) return null;
  const reachedTop = completed.every((set) => Number(set.actualReps || 0) >= Number(exercise.repMax || Infinity));
  const rirOkay = completed.every((set) => Number(set.actualRir || 0) >= 2);
  if (!reachedTop || !rirOkay) return null;
  if (["dumbbell-lateral-raise", "bent-over-reverse-fly", "lying-dumbbell-triceps-extension"].includes(exercise.id) && Number(exercise.weightPerDumbbellKg) === 2.5) {
    return { kind: "technique", label: "Zachowaj 2.5 kg i najpierw dodaj wolniejszą ekscentrykę, pauzę albo dokładniejszy ROM." };
  }
  const loads = Object.keys(DUMBBELL_LOADOUTS).map(Number).sort((a, b) => a - b);
  const next = loads.find((value) => value > Number(exercise.weightPerDumbbellKg));
  return next ? { kind: "weight", nextWeightKg: next, label: `Następnym razem spróbować ${formatDumbbellLoad(next, exercise.dumbbellCount)}?` } : null;
}
