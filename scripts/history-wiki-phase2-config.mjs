// Human-reviewed Phase 2 editorial decisions. This file contains no raw archive text.
// Every decision is applied by build-history-wiki-normalized.mjs to the canonical
// ChatGPT/processed/batches/data + batch_000..031 source only.

export const projectPrivacy = {
  P001: ["private", "Personal routines, task state and executive-function support."],
  P002: ["private", "Career history, work state and job-search material."],
  P003: ["private", "Personal travel plans and budgets."],
  P004: ["private", "Diet and daily-routine history."],
  P005: ["private", "Personal learning history and progress."],
  P006: ["third_party_sensitive", "Teaching materials can contain student or colleague context."],
  P007: ["private", "Personal reading history and annotations."],
  P008: ["private", "Personal media taste and listening history."],
  P009: ["private", "Personal extraction sources and archive workflows."],
  P010: ["private", "Reviewed conservatively because the legacy project mixed personal source material."],
  P011: ["private", "Personal creative work and fictional-world development."],
  P012: ["private", "Reflective tarot use and personal interpretation history."],
};

export const conversationCorrections = {
  "68401e15-cce0-8008-9827-4506f4b7d0c4": {
    summary: "Two image-only user messages in ‘Money Laundering Risks’; exported user text is unavailable.",
    review_decision: "summary_restored_conservatively",
    evidence_message_ids: ["bbb21e0d-2a16-481c-9d05-c8efbf31656e", "bbb21e95-575c-4432-bc2b-d5c0b5999ae1"],
  },
  "6a345c9a-5590-83eb-9fe9-95a14123ec91": {
    summary: "Assistant-only automated World Cup briefing; no user-authored message is present in the export.",
    review_decision: "assistant_only_exception_recorded",
    evidence_message_ids: [],
  },
  "6aace93a-7e80-83eb-b9bb-5ebce6edff4e": {
    summary: "Two image-only troubleshooting requests in ‘Naprawa cache VS Code’; exported user text is unavailable.",
    review_decision: "summary_restored_conservatively",
    evidence_message_ids: ["049fd0f0-d7b6-4781-b743-94a4390ccc84", "41f58ea2-af60-4111-8463-6eb667e45c48"],
  },
  "9eee38eb-ee2e-42c0-b050-9088d9762464": {
    project_ids: [], topic_ids: ["T011"], kind: "reference",
    review_decision: "topic_only_transient_creative_request",
  },
  "8eee5aaf-124c-4266-9b37-27bf0f436b3f": {
    project_ids: ["P017"], topic_ids: ["T019.1"], privacy_level: "third_party_sensitive", kind: "project",
    review_decision: "relationship_history_classified_and_privacy_escalated",
    evidence_message_ids: ["aaa25193-cd67-4c71-b25e-1b368e3c4dff", "aaa257fe-b8db-44b6-8bf7-7a72129c2b02"],
  },
  "0a00f463-653c-44f9-999f-a1200496d058": {
    project_ids: [], topic_ids: ["T018"], kind: "reference",
    review_decision: "topic_only_translation_request",
  },
  "d8e947e2-c3b3-4114-ab6d-780f86c40663": {
    project_ids: [], topic_ids: ["T001.4", "T009.1"], kind: "reference",
    review_decision: "topic_only_vinted_workflow",
  },
  "4cf4c431-02f2-4087-b6a1-344302eded49": { topic_ids: ["T012"], review_decision: "high_value_topic_added" },
  "25de93c2-058b-4684-9449-c821cfcd4d88": { topic_ids: ["T006.1", "T006.2"], review_decision: "high_value_topics_added" },
  "e77639b6-6d1f-4cba-bad3-3ccd314acedb": { topic_ids: ["T001.1", "T002.1"], review_decision: "high_value_topics_added" },
  "156631b9-015d-4ec2-8f39-cab7c089b3c8": { topic_ids: ["T007.2"], review_decision: "high_value_topic_added" },
  "f41fe8eb-5708-47b6-9bc2-355c22ee7b08": { topic_ids: ["T005.2"], review_decision: "high_value_topic_added" },
  "997ab600-2967-4e89-b796-851bb3a890a7": { topic_ids: ["T001.1"], review_decision: "high_value_topic_added" },
  "abcf5723-b491-4b01-a573-c3d0192b954f": { topic_ids: ["T006.2", "T006.3"], review_decision: "high_value_topics_added" },
  "458ae8cb-8204-484c-adc9-5e4c1e524567": { topic_ids: ["T007.2"], review_decision: "high_value_topic_added" },
  "b602e619-7da6-441b-90e1-dbefd77a0691": { topic_ids: ["T007.1"], review_decision: "high_value_topic_added" },
  "67f7d132-130c-8008-adc6-968d2ce2e155": { review_decision: "reviewed_and_retained_topic_only" },
  "68095616-673c-8008-947e-360c74756035": { project_ids: ["P025"], topic_ids: ["T025", "T025.3"], review_decision: "project_and_specific_topic_added" },
};

export const mergeDecisions = [
  ["M001", ["T001.5", "T026"], "do_not_merge", "T001.5 is a reusable method/tag; T026 is a concrete household application.", "related_to", "T001.5", "T026"],
  ["M002", ["P001", "P027"], "do_not_merge", "Personal Dashboard is an implementation descendant of the broader Personal Operating System.", "implemented_as", "P001", "P027"],
  ["M003", ["P007", "P034"], "do_not_merge", "SynchroBook is a specialized descendant of the reading-companion work.", "specialized_as", "P007", "P034"],
  ["M004", ["P008", "P027"], "do_not_merge", "Black Metal 365 has one feature identity but two valid parent contexts: cultural project and dashboard representation.", "shared_feature_identity", "P008", "P027"],
  ["M005", ["P017", "P019"], "do_not_merge", "Relationship history and a specific family/legal case have distinct scope and privacy boundaries.", "related_to", "P017", "P019"],
  ["M006", ["P002", "P035"], "do_not_merge", "P035 is an alternative manual/work-abroad career branch, not the same linear career project.", "branched_into", "P002", "P035"],
].map(([decision_id, candidate_ids, status, rationale, relation_type, from_id, to_id]) => ({
  decision_id, candidate_ids, status, retained_ids: candidate_ids, rationale, relation_type, from_id, to_id,
  reviewed_at: "2026-09-23", reviewer: "human_confirmed_phase2",
}));

export const aliases = [
  { alias_id: "A001", alias: "Personal Dashboard", canonical_id: "P027", related_id: "P001", alias_type: "descendant_name" },
  { alias_id: "A002", alias: "SynchroBook", canonical_id: "P034", related_id: "P007", alias_type: "specialized_descendant_name" },
  { alias_id: "A003", alias: "Black Metal 365", canonical_id: "F001", alias_type: "shared_feature_identity", contexts: [{ project_id: "P008", role: "cultural_project" }, { project_id: "P027", role: "dashboard_representation" }] },
  { alias_id: "A004", alias: "BM365", canonical_id: "F001", alias_type: "short_name" },
  { alias_id: "A005", alias: "Household gamification", canonical_id: "T026", related_id: "T001.5", alias_type: "application_of_method" },
];

export const forcedTopicRoles = {
  "T001.5": "tag", T020: "topic", T026: "topic", T029: "topic", T031: "topic", T032: "topic", T033: "topic", T034: "topic", T035: "topic",
};

export const genealogyEdges = [
  ["G001", "P001", "P027", "implemented_as", ["EV0093"], ["68f6d20f-98d0-832d-8e96-756717df96b0", "68f740e9-7138-8326-b5aa-924246375ae3"], "The general operating-system idea becomes a concrete umbrella dashboard."],
  ["G002", "P007", "P028", "operationalized_as", ["EV0128"], [], "Reading work gains a dedicated operational app before later specialization."],
  ["G003", "P007", "P034", "specialized_as", ["EV0174"], ["6a91cb37-c4a0-83eb-adfb-a9c7cff6dd00"], "SynchroBook specializes the reading-companion lineage around synchronized text and audio."],
  ["G004", "P002", "P035", "branched_into", ["EV0165"], ["6a4d2099-1c40-83ed-a629-152fa57161ba", "6aabead8-c96c-83eb-bae8-4847acbde723"], "A separate manual/work-abroad route branches from the earlier QA career line."],
  ["G005", "P001", "P026", "specialized_as", ["EV0037", "EV0069"], [], "The operating-system pattern becomes a specialized cleaning system."],
  ["G006", "P026", "P027", "integrated_into", ["EV0091", "EV0093"], ["68f6d20f-98d0-832d-8e96-756717df96b0"], "Cleaning becomes one component and summary surface inside the dashboard."],
  ["G007", "P002", "P027", "implemented_as_dashboard_domain", ["EV0192"], ["6aabead8-c96c-83eb-bae8-4847acbde723"], "Job-search state becomes a dedicated dashboard domain without replacing the career project."],
  ["G008", "P024", "P027", "implemented_as_dashboard_domain", ["EV0161"], [], "Great Timeline becomes a dashboard-linked historical interface."],
  ["G009", "P005", "P027", "implemented_as_dashboard_domain", ["EV0188"], ["6aa68a86-4108-83eb-9cc5-705d9f3e7260"], "Language learning becomes a durable dashboard domain."],
  ["G010", "P008", "P027", "surfaced_as_dashboard_interfaces", ["EV0121", "EV0182"], [], "Media projects, including BM365, gain dashboard representations while retaining their domain identity."],
  ["G011", "P021", "P030", "specialized_tracking_branch", ["EV0124", "EV0171"], [], "General health tracking develops a more specialized live-workout branch."],
  ["G012", "P021", "P027", "implemented_as_dashboard_domain", ["EV0124"], [], "Health state becomes a dashboard domain."],
  ["G013", "P030", "P027", "implemented_as_dashboard_domain", ["EV0171"], [], "Live training becomes a specialized dashboard surface."],
].map(([edge_id, from_project_id, to_project_id, relation_type, event_ids, conversation_ids, rationale]) => ({ edge_id, from_project_id, to_project_id, relation_type, event_ids, conversation_ids, rationale, confidence: "high", reviewed_at: "2026-09-23" }));

export const archaeologySeeds = [
  ["I0011", "early_live_cleaning_assistant"], ["I0142", "gamified_cleaning"], ["I0165", "retrospective_daily_diary"],
  ["I0178", "job_search_crm"], ["I0179", "cleaning_recency_tracker"], ["I0186", "ai_cleaning_advice"],
  ["I0187", "personal_dashboard"], ["I0191", "medication_and_habit_visualization"], ["I0193", "reading_widget"],
  ["I0195", "relational_cleaning_model"], ["I0215", "bm365_challenge"], ["I0217", "bm365_widget"],
  ["I0218", "journal_module"], ["I0222", "job_hunt_widget"], ["I0224", "network_tracker"],
  ["I0248", "developer_docs_page"], ["I0249", "spare_laptop_server"], ["I0254", "great_timeline"],
  ["I0257", "journal_emotion_visualization"], ["I0266", "intellectual_autobiography"], ["I0278", "local_read_only_llm"],
  ["I0279", "synchrobook_commentary"], ["I0297", "runtime_isolation"], ["I0299", "hands_free_cleaning"],
];

export const unfinishedThreads = [
  { thread_id: "U001", title: "Pełna rekonstrukcja Journalu", status: "open", project_ids: ["P001", "P027"], idea_ids: ["I0165", "I0218"], evidence_message_ids: ["bbb216e7-cb48-47aa-9e32-71c12c971283"], next_question: "Czy styl pilota jest wystarczająco wierny, by rozszerzyć go na wszystkie dni?" },
  { thread_id: "U002", title: "Regularna higiena i aktualizacja archiwum rozmów", status: "open", project_ids: ["P001"], idea_ids: [], evidence_message_ids: ["bbb2153a-9287-4e8e-8e20-0ded403f7f94"], next_question: "Jaki rytm eksportów i rebuildów ma być trwałą procedurą?" },
  { thread_id: "U003", title: "Kermit — lokalny, tylko do odczytu interfejs nad dashboardem", status: "active", project_ids: ["P027"], idea_ids: ["I0278"], evidence_message_ids: ["a27743aa-c912-42fe-9e65-b209c4e01565", "099647a7-251b-48e7-98ce-703c3a548b86"], next_question: "Jak zbudować bezpieczny pakiet dokumentacji i danych bez prawa zapisu?" },
  { thread_id: "U004", title: "Równoległe ścieżki kariery", status: "active", project_ids: ["P002", "P035"], idea_ids: ["I0178", "I0222"], evidence_message_ids: ["43113993-bf60-47ca-bf99-362a3e511d68"], next_question: "Jak porównywać QA, prace dorywcze i Norwegię bez udawania jednej osi kariery?" },
  { thread_id: "U005", title: "Uzupełnienie dawnych dzienników 2016–2021", status: "open", project_ids: [], idea_ids: ["I0266"], evidence_message_ids: ["a4bde76b-1125-4e95-b91c-884d873fbfad"], next_question: "Które lata i źródła nadal nie zostały przepisane?" },
  { thread_id: "U006", title: "SynchroBook — komentarz, audio i specjalizacja czytania", status: "active", project_ids: ["P007", "P034"], idea_ids: ["I0279"], evidence_message_ids: ["8abd02b8-5bef-495b-8ce1-7038eda9c39e"], next_question: "Które elementy linii czytelniczej należą do SynchroBooka, a które zostają ogólne?" },
];

export const erasDraft = [
  { era_id: "ER01", start_date: "2023-01-10", end_date: "2024-07-16", title: "Restart i wynoszenie planów na zewnątrz", description: "Pierwsze rozmowy pokazują próby zamiany lęku, chaosu i planów zawodowych w konkretne listy, rutyny i system wsparcia.", turning_point_event_ids: [], project_ids: ["P001", "P002", "P003"], confidence: "medium", privacy_level: "sensitive" },
  { era_id: "ER02", start_date: "2024-07-17", end_date: "2025-03-23", title: "Projekty stają się powtarzalnymi systemami", description: "Listy pracy, nauka języków, czytanie i sprzątanie zaczynają działać jako powtarzalne procedury zamiast jednorazowych próśb.", turning_point_event_ids: ["EV0001", "EV0002", "EV0032"], project_ids: ["P001", "P002", "P005", "P007", "P026"], confidence: "high", privacy_level: "private" },
  { era_id: "ER03", start_date: "2025-03-24", end_date: "2025-10-20", title: "Rozszerzanie systemu życia i narzędzi", description: "Pomysły obejmują coraz więcej codziennych domen, podróży i własnych narzędzi, ale pozostają jeszcze rozproszone.", turning_point_event_ids: ["EV0036", "EV0054", "EV0064", "EV0080"], project_ids: ["P001", "P003", "P008", "P021", "P026"], confidence: "medium", privacy_level: "private" },
  { era_id: "ER04", start_date: "2025-10-21", end_date: "2026-05-08", title: "Personal Dashboard staje się parasolem", description: "Dashboard zaczyna łączyć wcześniejsze projekty w jeden interfejs, zachowując ich oddzielne źródła i specjalizacje.", turning_point_event_ids: ["EV0093", "EV0124", "EV0128"], project_ids: ["P001", "P027", "P026", "P021", "P028"], confidence: "high", privacy_level: "private" },
  { era_id: "ER05", start_date: "2026-05-09", end_date: "2026-07-27", title: "Nowe otoczenie, praca dodatkowa i potoki archiwalne", description: "Codzienna logistyka, nowe źródła zarobku oraz historia osobista są coraz częściej przetwarzane przez własne aplikacje i archiwa.", turning_point_event_ids: ["EV0142", "EV0149", "EV0161", "EV0164"], project_ids: ["P003", "P024", "P027", "P035"], confidence: "medium", privacy_level: "sensitive" },
  { era_id: "ER06", start_date: "2026-07-28", end_date: null, title: "Rozgałęzianie kariery i wyspecjalizowane systemy", description: "Zamiast jednej linearnej historii pojawiają się równoległe ścieżki zawodowe i wyspecjalizowane aplikacje połączone przez dashboard.", turning_point_event_ids: ["EV0165", "EV0169", "EV0174", "EV0188", "EV0192"], project_ids: ["P002", "P005", "P007", "P027", "P034", "P035"], confidence: "high", privacy_level: "private" },
];

const C = (claim_id, local_date, claim_text, privacy_level, supporting_message_ids, claim_type = "paraphrase", confidence = "high") => ({ claim_id, local_date, claim_text, claim_type, confidence, privacy_level, supporting_message_ids });

export const journalClaimSeeds = [
  C("JC001", "2023-01-10", "Szukałem praktycznego wsparcia w planowaniu i ruszaniu z zadaniami przy ADHD i lęku.", "sensitive", ["7ebfffa5-fad1-4713-b626-556d78e04152"]),
  C("JC002", "2023-01-10", "Chciałem znaleźć nową pracę w QA, ale utknąłem na CV i wysyłaniu aplikacji.", "private", ["71b2fb1a-ca4c-41da-8780-8fecfe7e8040"]),
  C("JC003", "2023-01-10", "Miałem rok doświadczenia jako Test Analyst i myślałem o wejściu w automatyzację.", "private", ["6998eed5-cb6c-4eed-9232-3fba3f1c3910"]),
  C("JC004", "2023-01-10", "Od razu chciałem też systemu do śledzenia firm, wysłanych CV, kontaktów i kolejnych kroków.", "private", ["6d187019-6292-411a-946b-438a89d13a6d"]),

  C("JC005", "2023-01-24", "Planowałem przeprowadzkę w następnym miesiącu i potrzebowałem rozpiski pakowania oraz transportu.", "private", ["3827855b-41f2-491d-b0f7-9147afd49e95"]),
  C("JC006", "2023-01-24", "Pytałem o prostą zdrową rutynę dnia.", "private", ["856d104d-a534-4d97-a96f-f41acd8a24b1"]),
  C("JC007", "2023-01-24", "Układałem tydzień łatwych śniadań i listę zakupów.", "normal", ["baef7c60-c2ec-4a57-a2ce-356f6df0b660"]),
  C("JC008", "2023-01-24", "Na koniec chciałem wiedzieć, jak zrobić smoothie z masłem orzechowym i bananem.", "normal", ["198c92af-80ef-4cac-b9cd-551bc98272b5"]),

  C("JC009", "2023-02-20", "Było mi smutno, a pod koniec miesiąca czekała mnie przeprowadzka.", "sensitive", ["c3e374e7-d805-49c1-bd44-601de86f1ba7", "4473feb4-e08a-42ff-9456-4f79263c48a1"]),
  C("JC010", "2023-02-20", "Skończył się trzynastoletni związek.", "third_party_sensitive", ["4ca80ae8-3889-43b1-af00-877924dd0c8b"]),
  C("JC011", "2023-02-20", "Nie widziałem sensu życia ani niczego szczególnie ekscytującego, choć nie opisywałem tego po prostu jako nieszczęścia.", "sensitive", ["ecacf6d9-cd2a-4732-a617-ec26d374fe1e"]),
  C("JC012", "2023-02-20", "Myślałem o lepszych zarobkach i długiej, dwuletniej podróży z oszczędności.", "private", ["be7eb38a-6d85-4bbd-98fa-c2c0a82079dd"]),
  C("JC013", "2023-02-20", "Wkurwiłem się, gdy rozmowa zaczęła powtarzać te same przykłady.", "normal", ["87b9342e-51b7-40a3-a309-2e5467a13072"]),

  C("JC014", "2024-07-21", "Chciałem przeznaczyć dwie–trzy godziny na uporządkowanie priorytetów do skryptu.", "private", ["aaa2cb58-06ec-45cd-8b33-1a9cac93682c", "aaa2944f-02dd-4360-91b3-85a6efd1dfe8"]),
  C("JC015", "2024-07-21", "Wkurwiłem się, bo asystent zmyślił Contract Law zamiast najpierw zapytać, czym się zajmuję.", "normal", ["aaa2ada6-1407-4ad7-bc75-afa5abccade3"]),
  C("JC016", "2024-07-21", "Pracowałem nad materiałami do Primal Fear i ćwiczeniem z reported speech.", "private", ["aaa271dd-240e-4fd6-95e4-6f0c9e4d2560", "aaa22321-bc6b-45a6-b9e8-ce07485ff09f"]),
  C("JC017", "2024-07-21", "Po pracy siedziałem w parku, czytałem książkę i cieszyłem się, że drugi rozdział poszedł łatwiej.", "normal", ["afd6ec4d-ac21-41d8-8740-5e7b4c2ebedc", "1c0b9c45-0fcc-464b-832b-73c50fa92487"]),

  C("JC018", "2024-07-24", "W pracy zamknąłem raport i ustawiłem wznowione rozmowy UAT, a przy innych defektach czekałem na kilka osób.", "third_party_sensitive", ["aaa20dd9-0278-42c8-898d-cddf74563743", "aaa27136-eca1-49b8-bbfb-e62c4c94ee62"]),
  C("JC019", "2024-07-24", "Eskalowałem naprawę komunikacji dla Juniper Costa Rica mailem i na Teamsach.", "third_party_sensitive", ["aaa2af7c-632e-495f-8ad3-8c09ddcf161b"]),
  C("JC020", "2024-07-24", "Chciałem lepiej słuchać partnerki, ale bałem się przeciążenia i własnego unikania.", "third_party_sensitive", ["aaa25193-cd67-4c71-b25e-1b368e3c4dff", "aaa257fe-b8db-44b6-8bf7-7a72129c2b02"]),
  C("JC021", "2024-07-24", "Po wymianie RAM-u komputer nie startował; z jedną nową kością działał, z dwiema nie.", "normal", ["bbb21cfe-cde7-469e-9bdd-7e2d8cef0b43", "bbb210e9-b3a4-4a1f-9a88-e5bce5535358"]),

  C("JC022", "2024-07-29", "Układałem jedną dużą listę życia: Vinted, skrypt, nauka, sprzątanie i inne zaległości.", "private", ["aaa24178-f86d-4f7b-a7ed-0652a7b00502"]),
  C("JC023", "2024-07-29", "Dopisałem szukanie nowej pracy w QA i wysyłanie CV.", "private", ["aaa2a56b-7748-460e-af02-5cd80b9f2710"]),
  C("JC024", "2024-07-29", "Czytałem Inferno canto po canto: miałem za sobą I, a potem odnotowałem także II.", "normal", ["aaa28fad-f0a0-4253-9c82-d5da602e01f3", "aaa288ea-dbc6-4c10-9000-fe8bf52cb0a7"]),
  C("JC025", "2024-07-29", "Budowałem rumuńskie historyjki wyłącznie z listy frekwencyjnej, z tłumaczeniem, komentarzem i pomysłem na audio.", "normal", ["aaa2ab2b-0cb7-4830-a7ee-b7d055da7fcf", "aaa2c8d2-07af-4d5c-9978-f190226065dc", "aaa2830b-15b5-4b41-ab68-163e7fddbf69"]),

  C("JC026", "2025-02-03", "Sprawdzałem, co oznacza napis „Sterling A” na bransoletce.", "normal", ["bbb218c1-41a5-4b8c-be38-f88b0daf3eb2"]),
  C("JC027", "2025-02-03", "Byłem kurewsko przeciążony i chciałem po prostu skończyć jedno zadanie.", "sensitive", ["1a66ffde-da76-418c-ae92-e057eb5aa208"]),
  C("JC028", "2025-02-03", "Tym zadaniem było wysłanie klientowi EE IDs.", "private", ["a71399eb-823f-43ab-a6f1-867d95b6ebb9"]),
  C("JC029", "2025-02-03", "Problem w tym, że najpierw musiałem te identyfikatory utworzyć.", "private", ["898176da-aa0f-49e2-a566-3d605e0069e4"]),

  C("JC030", "2025-03-16", "Rano chciałem rozbić sprzątanie każdego pomieszczenia na małe kroki i zrobić z tego checklistę do grywalizacji.", "private", ["963311b7-34d1-4397-b558-be60a27941a7"]),
  C("JC031", "2025-03-16", "Ogarniałem też zakupy z Biedronki Express i pytałem, jak zrobić owsiankę.", "private", ["89121d17-4246-4828-81bf-02e7d72dc0b5", "659c62c1-c262-4f59-9132-3cf0793d5e97"]),
  C("JC032", "2025-03-16", "Później napisałem wprost, że chcę się zabić, jestem sam i nic nie daje mi radości ani ulgi.", "sensitive", ["bbb21e6b-4a3d-42df-91be-07731565843f", "bbb2197f-a6b5-4171-93d4-15b0196ace25", "bbb21978-7e84-48ba-a806-b237bfbf2a58"]),
  C("JC033", "2025-03-16", "Napięcie w relacji rozwaliło mi próbę zaplanowania dnia; poprzedni dzień spędziłem, chcąc umrzeć.", "third_party_sensitive", ["bbb2103d-74c9-4c93-ad84-a23687d37208"]),
  C("JC034", "2025-03-16", "Wieczorem pojawiło się jeszcze zwykłe pytanie o gry piłką i frisbee dla dwóch dorosłych i ośmiolatki.", "third_party_sensitive", ["bbb21a14-dc16-4658-9e05-deddfe1966b1"]),

  C("JC035", "2025-08-11", "Planowałem pełny dzień i wieczór w Tiranie, łącznie z jedzeniem, a potem dopytałem o Prisztinę.", "private", ["bbb21ce4-1bce-464e-b8a1-47de4ec14aeb", "bbb21f78-0971-4d13-b13c-33c5985dbb98"]),
  C("JC036", "2025-08-11", "W Turcji chciałem jeździć wygodnymi pociągami i ograniczyć odcinki do maksymalnie pięciu godzin.", "private", ["bbb21e83-b962-4632-b83c-b152c8e2d9e8", "bbb21ac5-64e1-4c88-b0af-d30fcc6e0729"]),
  C("JC037", "2025-08-11", "Sprawdzałem autobus z Konyi do Göreme oraz ceny tatuaży i oldschoolowe studia w Tiranie.", "private", ["bbb21d30-42aa-48a3-9d02-93360cef79cc", "bbb2184e-5f85-4cb1-b08b-09857b413e19", "bbb211d7-0ff5-47df-bd01-74fabeca9018"]),
  C("JC038", "2025-08-11", "Musiałem ustalić legalność i przewóz metylofenidatu, wortioksetyny, duloksetyny i pregabaliny przez Albanię, Kosowo i Turcję.", "sensitive", ["bbb212bb-b212-4295-99d4-563eaba92c6d", "bbb211fe-1cdc-4987-b020-dbbfc501406d", "bbb21e75-ed07-42f5-8057-2a94dd9ba1c2"]),

  C("JC039", "2025-10-21", "W nocy próbowałem zrobić pierwszy push cleaning-dashboardu na GitHuba, walcząc z nazwą brancha i uwierzytelnianiem.", "private", ["d5814b56-2bd7-4672-8f3e-e3337843015f", "d2ac5e06-3cc0-46fe-bfa9-415e0ccdaccd", "27eec38f-9ea8-488f-9d19-5ced2ae6440b"]),
  C("JC040", "2025-10-21", "Po pushu chciałem opublikować całość przez GitHub Pages.", "private", ["f4fe9b18-0238-4534-9ec7-d47fdeb71261"]),
  C("JC041", "2025-10-21", "Tego dnia Personal Dashboard dostał konkretny zestaw komponentów: czas, pogodę, powietrze, sprzątanie, nawyki, wydarzenia, zdrowie i czytanie.", "private", ["bbb211ad-9135-443f-bbc2-5db54f3a3826", "bbb21d76-a710-4727-b756-27223f5028c0"]),
  C("JC042", "2025-10-21", "Chciałem też przerobić istniejącą apkę na importowalny komponent oraz zbudować bota do tanich książek.", "private", ["bbb21669-fe64-46ef-ba54-1e8a30c95ef9", "bbb217b5-b47f-42a0-849c-7c7229ce65c0"]),
  C("JC043", "2025-10-21", "Planowałem wykres dwóch lat alkoholu, papierosów i leków.", "sensitive", ["bbb2141e-ad19-4e81-a756-8895c86a7058"]),

  C("JC044", "2026-05-09", "Po północy próbowałem policzyć noc z whisky sour, piwem, czekoladą, pizzą i waflami ryżowymi.", "sensitive", ["f337b0ac-354c-48bb-b034-3fbef8a91e04"]),
  C("JC045", "2026-05-09", "Patrząc na ten bilans, napisałem: „ja pierdolę, co tu się odjebało” i bałem się, że zawsze będę gruby.", "sensitive", ["f60c019d-81f6-469b-a388-0b262003fbb1"], "direct"),
  C("JC046", "2026-05-09", "Od razu przekułem to w pomysł integracji dashboardu z Open Food Facts.", "private", ["e3a1e9a2-a2a8-4565-95ff-12941a8e308a"]),
  C("JC047", "2026-05-09", "Później byłem we Wrocławiu: stary cmentarz żydowski, goth/creepy miejsca, tramwaj i pociąg do Krakowa o 20:57.", "private", ["bbb21924-0304-4548-b545-3207a3bbfa66", "bbb21281-cac4-4404-9934-1a6fa6baaf3c", "bbb21283-c54c-4e8a-bda0-da17ff5676ec"]),
  C("JC048", "2026-05-09", "Sprawdzałem też rejestrację i aplikacje do pracy kurierskiej w Krakowie.", "private", ["bbb2188a-78d2-4d8e-8b8a-e2ff7b145ecc", "bbb213ed-79e2-4b17-b999-566468f73042"]),

  C("JC049", "2026-07-07", "Próbowałem rozpisać życie długoterminowo przed lipcowym urlopem, wyjazdem do Włoch i koncertem MCR.", "private", ["ce93e73d-a49c-4fd3-a77b-20c22f202e94"]),
  C("JC050", "2026-07-07", "Byłem skrajnie wypalony pracą i myślałem o odejściu, ale ciążył mi trzymiesięczny okres wypowiedzenia i finanse.", "sensitive", ["ce93e73d-a49c-4fd3-a77b-20c22f202e94"]),
  C("JC051", "2026-07-07", "W tym samym opisie wróciły depresja i myśli samobójcze związane z pracą.", "sensitive", ["ce93e73d-a49c-4fd3-a77b-20c22f202e94"]),
  C("JC052", "2026-07-07", "Obok tego ciężaru chciałem absurdalnego obrazka: ludzkiej wielkości wiewiórki jedzącej orzecha na fotelu.", "normal", ["bfef4120-c38f-4e2a-a046-d5e3c826437f"]),

  C("JC053", "2026-08-17", "Chciałem z dawnych wpisów odtworzyć ewolucję młodego mnie i wynikającą z nich osobistą filozofię.", "private", ["9c25f9e4-0c8f-4328-a96a-3dba9e6051ce", "c26debe9-e0f9-4684-91ff-22948be39a78"]),
  C("JC054", "2026-08-17", "Notatki z lat 2016–2021 nadal przepisywałem; nie miałem jeszcze całości.", "private", ["a4bde76b-1125-4e95-b91c-884d873fbfad"]),
  C("JC055", "2026-08-17", "Dodałem komplet wpisów z 2016 oraz własne wiersze i chciałem zbadać korelacje między poezją a dziennikiem.", "private", ["2e5955fd-c929-4447-8c03-44eb515cf31f", "190bc5a2-7e28-4d52-b7ef-7acd51a0b311"]),
  C("JC056", "2026-08-17", "Równolegle zacząłem budować własne drzewo genealogiczne, mając niewiele danych o rodzinie.", "third_party_sensitive", ["e38960de-348f-4d7d-b210-c6c66f428ca3", "0f6e641e-3096-42dc-9a7a-66da85f081d1"]),

  C("JC057", "2026-09-17", "Przez cały dzień rozwijałem Finance: audyt, rachunki, paragony, produkty i finansowego Akinatora.", "private", ["52089f6a-0f61-4170-97fb-dec13eb9a4b3", "6553a1bf-fecc-4d03-a016-a4817c8d9b56", "e10afd6c-84b8-4076-9fe0-a473fabbb297", "31e589c1-ea84-4a73-a40e-89f5f4789864"]),
  C("JC058", "2026-09-17", "Job Hunt rozdzieliłem na nieporównywalne wprost ścieżki: QA w Krakowie, prace dorywcze i pracę fizyczną w Norwegii.", "private", ["43113993-bf60-47ca-bf99-362a3e511d68"]),
  C("JC059", "2026-09-17", "Myślałem o lokalnym Kermicie: czatbocie, który zna dokumentację systemu, ale ma pozostać tylko do odczytu.", "private", ["a27743aa-c912-42fe-9e65-b209c4e01565", "099647a7-251b-48e7-98ce-703c3a548b86"]),
  C("JC060", "2026-09-17", "Uruchomiłem też projekt katalogowania całej historii rozmów i pytałem o regularne dalsze kroki oraz eksport przed wyjazdem.", "private", ["bbb216e7-cb48-47aa-9e32-71c12c971283", "bbb2153a-9287-4e8e-8e20-0ded403f7f94", "bbb21ec5-f741-4021-8067-a9ed3a961048"]),
];

const E = (local_date, title, sections) => ({ journal_entry_id: `J-${local_date}`, local_date, label: "AI-reconstructed diary entry", timezone: "Europe/Warsaw", title, sections });
const S = (privacy_level, sentences) => ({ privacy_level, sentences: sentences.map(([text, claim_ids]) => ({ text, claim_ids })) });

export const journalEntrySeeds = [
  E("2023-01-10", "Trzeba to wreszcie ułożyć", [S("private", [["Szukam nowej pracy w QA, ale utknąłem na CV i samym wysyłaniu zgłoszeń.", ["JC002"]], ["Mam rok doświadczenia jako Test Analyst, myślę już o automatyzacji i od razu chcę tracker firm, kontaktów, wysłanych CV i kolejnych kroków.", ["JC003", "JC004"]]]), S("sensitive", [["Potrzebuję praktycznego wsparcia przy ADHD: planowanie i start zadań zalewają mnie lękiem, więc chcę rozbijać wszystko na ruchy, które naprawdę da się wykonać.", ["JC001"]]])]),
  E("2023-01-24", "Przeprowadzka, rutyna, smoothie", [S("private", [["W przyszłym miesiącu przeprowadzka, więc rozpisuję pakowanie i transport zamiast trzymać cały ten bałagan w głowie.", ["JC005"]], ["Przy okazji próbuję ułożyć zwykłą zdrową rutynę dnia.", ["JC006"]]]), S("normal", [["Układam banalnie łatwe śniadania na tydzień, listę zakupów i sprawdzam, jak zrobić smoothie z masłem orzechowym i bananem.", ["JC007", "JC008"]]])]),
  E("2023-02-20", "Koniec czegoś bardzo długiego", [S("sensitive", [["Jest mi smutno, pod koniec miesiąca się wyprowadzam i nie bardzo wiem, co ma być dalej.", ["JC009"]], ["Nie mówię po prostu, że jestem nieszczęśliwy; bardziej że nie widzę sensu życia ani niczego szczególnie ekscytującego.", ["JC011"]]]), S("third_party_sensitive", [["Skończył się trzynastoletni związek.", ["JC010"]]]), S("private", [["Jedyny zarys planu to zarabiać więcej, oszczędzić i kiedyś wyjechać na dwa lata, a nie na dwa tygodnie.", ["JC012"]]]), S("normal", [["A potem jeszcze wkurwiam się, bo rozmowa mieli w kółko te same przykłady.", ["JC013"]]])]),
  E("2024-07-21", "Skrypt, Primal Fear i park", [S("private", [["Mam dwie–trzy godziny na skrypt i chcę realnej listy priorytetów.", ["JC014"]], ["Konkret to Primal Fear: materiały nauczyciela i ucznia oraz ćwiczenie z reported speech.", ["JC016"]]]), S("normal", [["Wkurwiam się, gdy asystent z dupy wymyśla Contract Law zamiast zapytać, co właściwie robię.", ["JC015"]], ["Wieczorem siedzę w parku, czytam i odpoczywam; drugi rozdział wszedł wyraźnie łatwiej.", ["JC017"]]])]),
  E("2024-07-24", "UAT, relacja i RAM", [S("third_party_sensitive", [["W robocie raport i wznowione calle UAT są zamknięte, przy części defektów czekam na ludzi, a komunikację dla Juniper Costa Rica eskaluję mailem i na Teamsach.", ["JC018", "JC019"]], ["Poza pracą chcę lepiej słuchać partnerki, ale boję się, że mnie zaleje i znowu wejdę w unikanie.", ["JC020"]]]), S("normal", [["Jakby było mało: po zmianie RAM-u komputer nie startuje; na jednej nowej kości działa, na dwóch nie.", ["JC021"]]])]),
  E("2024-07-29", "Wszystko naraz, ale w tabeli", [S("private", [["Robię jedną wielką listę życia: Vinted, skrypt, nauka, sprzątanie i reszta zaległości.", ["JC022"]], ["Dopisuję do niej szukanie pracy w QA i wysyłanie CV.", ["JC023"]]]), S("normal", [["Czytam Dantego canto po canto — I mam za sobą, a potem dochodzi II.", ["JC024"]], ["Obok tego buduję rumuńskie historyjki tylko ze słów z listy frekwencyjnej, z tłumaczeniem, gramatyką i pomysłem na osobne MP3.", ["JC025"]]])]),
  E("2025-02-03", "Jedno pieprzone zadanie", [S("normal", [["Najpierw drobiazg: sprawdzam, co znaczy „Sterling A” na bransoletce.", ["JC026"]]]), S("sensitive", [["Potem jestem tak kurewsko przeciążony, że chcę tylko skończyć jedno pieprzone zadanie.", ["JC027"]]]), S("private", [["Mam wysłać klientowi EE IDs, tylko oczywiście najpierw muszę je jeszcze utworzyć.", ["JC028", "JC029"]]])]),
  E("2025-03-16", "Checklista rano, przepaść później", [S("private", [["Rano rozbijam sprzątanie pokoju, łazienki, kuchni i korytarza na małe kroki do grywalizowanej checklisty.", ["JC030"]], ["Do tego Biedronka Express, plan jedzenia i najbardziej zwykłe pytanie: jak zrobić owsiankę.", ["JC031"]]]), S("sensitive", [["Kilka godzin później piszę wprost, że chcę się zabić, jestem sam i nic nie daje mi radości ani ulgi.", ["JC032"]]]), S("third_party_sensitive", [["Napięcie w relacji rozwala mi próbę zaplanowania dnia; piszę też, że poprzedni dzień spędziłem, chcąc umrzeć.", ["JC033"]], ["Jeszcze później dzień wraca do groteskowej zwyczajności: pytam, w co mogą grać piłką i frisbee dwie dorosłe osoby i ośmiolatka.", ["JC034"]]])]),
  E("2025-08-11", "Trasa, tatuaże i leki", [S("private", [["Plan jest szeroki: cały dzień i wieczór w Tiranie, jedzenie, potem Prisztina.", ["JC035"]], ["W Turcji chcę wygodnych pociągów, żadnych morderczych odcinków ponad pięć godzin, a między Konyą i Kapadocją sprawdzam autobus do Göreme.", ["JC036", "JC037"]], ["Przy okazji porównuję ceny tatuaży i szukam oldschoolowych studiów w Tiranie.", ["JC037"]]]), S("sensitive", [["Najbardziej praktyczny problem to przewóz leków: metylofenidatu, wortioksetyny, duloksetyny i pregabaliny przez Albanię, Kosowo i Turcję.", ["JC038"]]])]),
  E("2025-10-21", "Dashboard dostaje kręgosłup", [S("private", [["W nocy robię pierwszy commit i próbuję wypchnąć cleaning-dashboard na GitHuba; branch i logowanie robią burdel, ale potem chcę już tylko wystawić to na Pages.", ["JC039", "JC040"]], ["Tego dnia Personal Dashboard przestaje być mgłą: ma mieć czas, pogodę, powietrze, sprzątanie, nawyki, wydarzenia, zdrowie i czytanie.", ["JC041"]], ["Chcę wciągać istniejące apki jako komponenty i dorzucam bota polującego na tanie książki.", ["JC042"]]]), S("sensitive", [["Do tego dochodzi wykres dwóch lat alkoholu, papierosów i leków — nie ozdoba, tylko własna historia w danych.", ["JC043"]]])]),
  E("2026-05-09", "Wrocław po bardzo długiej nocy", [S("sensitive", [["Po północy liczę whisky sour, piwo, czekoladę, pizzę i wafle, po czym mam tylko: ja pierdolę, co tu się odjebało, czy ja już zawsze będę gruby.", ["JC044", "JC045"]]]), S("private", [["Prawie od razu zamieniam panikę w feature: połączyć jedzenie w dashboardzie z Open Food Facts.", ["JC046"]], ["Potem Wrocław: stary cmentarz żydowski, goth/creepy rzeczy, ogarnianie biletu w tramwaju i sprint informacyjny do pociągu na Kraków o 20:57.", ["JC047"]], ["W tle sprawdzam jeszcze, jak wejść w kurierkę i które aplikacje zwiększą szanse na zlecenia w Krakowie.", ["JC048"]]])]),
  E("2026-07-07", "Plan awaryjny i wielka wiewiórka", [S("private", [["Przed urlopem, Włochami i koncertem MCR próbuję wreszcie rozpisać życie długoterminowo.", ["JC049"]]]), S("sensitive", [["Praca mnie skrajnie wypaliła; myślę o odejściu, ale mam trzy miesiące wypowiedzenia, pieniądze do policzenia i wracające depresyjne oraz samobójcze myśli związane z tym wszystkim.", ["JC050", "JC051"]]]), S("normal", [["I dokładnie obok tego proszę o obrazek wielkiej jak człowiek wiewiórki, która siedzi na fotelu i je orzecha.", ["JC052"]]])]),
  E("2026-08-17", "Archeologia własnej głowy", [S("private", [["Z dawnych dzienników próbuję odtworzyć ewolucję młodego mnie i filozofię, która naprawdę z tych wpisów wynika.", ["JC053"]], ["Materiały z lat 2016–2021 nadal przepisuję i nie mam jeszcze całości.", ["JC054"]], ["Dorzucam komplet 2016 i własne wiersze, a potem pytam wprost o korelacje między poezją a dziennikiem.", ["JC055"]]]), S("third_party_sensitive", [["Równolegle zaczynam drzewo genealogiczne z garścią rodzinnych danych i pytaniem, jak z tego w ogóle ruszyć.", ["JC056"]]])]),
  E("2026-09-17", "Cztery systemy w jednym dniu", [S("private", [["Finance puchnie od audytu przez rachunki i paragony aż po produkty oraz finansowego Akinatora.", ["JC057"]], ["Job Hunt przestaje udawać jedną ścieżkę: QA w Krakowie, dorywcze roboty i fizyczna praca w Norwegii muszą żyć obok siebie.", ["JC058"]], ["Równolegle wymyślam lokalnego Kermita — czat nad dokumentacją i danymi dashboardu, ale tylko do odczytu.", ["JC059"]], ["Na koniec odpalam samo katalogowanie historii rozmów i myślę już nie tylko o jednorazowym eksporcie, lecz o regularnej higienie całego archiwum.", ["JC060"]]])]),
];
