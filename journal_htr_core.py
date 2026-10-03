"""Pure Journal HTR workflow helpers shared by the store and tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable, Sequence


LINE_STATUSES = {
    "unreviewed",
    "corrected",
    "approved",
    "uncertain",
    "illegible",
    "excluded",
}
JOB_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}
PAGE_STATUSES = {
    "uploaded",
    "segmenting",
    "segmented",
    "transcribing",
    "transcribed",
    "reviewed",
    "failed",
}
TRAINABLE_LINE_STATUSES = {"approved", "corrected"}


class HtrValidationError(ValueError):
    """Raised when HTR state cannot be safely persisted."""


def validate_status(value: str, allowed: set[str], field: str = "status") -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise HtrValidationError(
            f"{field} must be one of: {', '.join(sorted(allowed))}"
        )
    return normalized


def line_eligible_for_training(
    review_status: str,
    corrected_text: str | None,
    predicted_text: str | None,
    use_for_training: bool | None,
) -> bool:
    """Return whether a reviewed line is valid ground truth."""
    if use_for_training is False:
        return False
    if review_status not in TRAINABLE_LINE_STATUSES:
        return False
    text = corrected_text if corrected_text is not None else predicted_text
    return bool(str(text or "").strip())


def levenshtein_distance(left: Sequence, right: Sequence) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row_index, left_item in enumerate(left, start=1):
        current = [row_index]
        for column_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    reference = str(reference or "")
    hypothesis = str(hypothesis or "")
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein_distance(reference, hypothesis) / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = str(reference or "").split()
    hypothesis_words = str(hypothesis or "").split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return levenshtein_distance(reference_words, hypothesis_words) / len(reference_words)


def split_pages(
    page_ids: Iterable[str],
    *,
    train_ratio: float = 0.8,
    validation_ratio: float = 0.1,
    test_ratio: float = 0.1,
    salt: str = "journal-htr-v1",
    fixed_test_pages: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """Deterministically split by page, never by individual line."""
    ratios = [float(train_ratio), float(validation_ratio), float(test_ratio)]
    if any(value < 0 for value in ratios) or abs(sum(ratios) - 1.0) > 0.000001:
        raise HtrValidationError("Dataset ratios must be non-negative and sum to 1")

    unique_pages = sorted({str(value) for value in page_ids if str(value)})
    fixed_test = {str(value) for value in (fixed_test_pages or [])}
    test = [page_id for page_id in unique_pages if page_id in fixed_test]
    remaining = [page_id for page_id in unique_pages if page_id not in fixed_test]
    remaining.sort(
        key=lambda page_id: sha256(f"{salt}:{page_id}".encode("utf-8")).hexdigest()
    )

    desired_test = round(len(unique_pages) * test_ratio)
    needed_test = max(0, desired_test - len(test))
    test.extend(remaining[:needed_test])
    remaining = remaining[needed_test:]

    non_test_ratio = train_ratio + validation_ratio
    validation_share = validation_ratio / non_test_ratio if non_test_ratio else 0
    validation_count = round(len(remaining) * validation_share)
    validation = remaining[:validation_count]
    train = remaining[validation_count:]
    return {"train": train, "validation": validation, "test": sorted(test)}


def character_statistics(texts: Iterable[str]) -> dict:
    counter = Counter("".join(str(value or "") for value in texts))
    polish = "ąćęłńóśźż"
    return {
        "characters": sum(counter.values()),
        "distribution": dict(sorted(counter.items(), key=lambda item: (-item[1], item[0]))),
        "polishCharacters": {char: counter[char] for char in polish},
        "digits": sum(count for char, count in counter.items() if char.isdigit()),
        "punctuation": sum(
            count for char, count in counter.items() if not char.isalnum() and not char.isspace()
        ),
    }


def filter_review_lines(lines: Iterable[dict], filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    result = []
    for line in lines:
        if filters.get("status") and line.get("reviewStatus") != filters["status"]:
            continue
        if filters.get("language") and line.get("language") != filters["language"]:
            continue
        if filters.get("projectId") and line.get("projectId") != filters["projectId"]:
            continue
        if filters.get("modelId") and line.get("modelId") != filters["modelId"]:
            continue
        if filters.get("segmentationIssue") is True and not line.get("segmentationIssue"):
            continue
        if filters.get("dateFrom") and str(line.get("entryDate") or "") < filters["dateFrom"]:
            continue
        if filters.get("dateTo") and str(line.get("entryDate") or "") > filters["dateTo"]:
            continue
        training_filter = filters.get("useForTraining")
        if training_filter is not None and bool(line.get("useForTraining")) is not bool(training_filter):
            continue
        result.append(line)

    active_model = filters.get("activeModelId")

    def priority(line: dict):
        confidence = line.get("confidence")
        confidence_value = float(confidence) if confidence is not None else 1.0
        text = str(line.get("predictedText") or "")
        rare_chars = sum(1 for char in text if ord(char) > 127)
        if line.get("reviewStatus") == "unreviewed":
            group = 0
        elif rare_chars:
            group = 1
        elif active_model and line.get("modelId") != active_model:
            group = 2
        else:
            group = 3
        return group, confidence_value, int(line.get("lineOrder") or 0)

    return sorted(result, key=priority)


@dataclass(frozen=True)
class NextStep:
    title: str
    description: str
    reason: str
    action_label: str
    action_url: str
    priority: int
    blocking_issue: bool = False

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "reason": self.reason,
            "actionLabel": self.action_label,
            "actionUrl": self.action_url,
            "priority": self.priority,
            "blockingIssue": self.blocking_issue,
        }


def calculate_next_step(state: dict) -> dict:
    """Return one deterministic, actionable next step for both UIs."""
    base = "./journal-ocr.html"
    if not state.get("enabled"):
        return NextStep(
            "Skonfiguruj lokalny silnik HTR",
            "Włącz moduł i ustaw lokalny adres eScriptorium.",
            "HTR_ENABLED nie jest ustawione na true.",
            "Otwórz konfigurację",
            f"{base}#configuration",
            1,
            True,
        ).as_dict()
    if state.get("bootstrapState") == "waiting_for_virtualization":
        return NextStep(
            "Silnik OCR czeka na wirtualizację",
            "Upload i lokalny zapis działają już teraz; rozpoznawanie ruszy automatycznie po włączeniu SVM/AMD-V.",
            state.get("providerError")
            or "Firmware komputera zgłasza wyłączoną wirtualizację procesora.",
            "Dodaj strony lokalnie",
            f"{base}#upload",
            2,
            True,
        ).as_dict()
    if not state.get("providerConfigured"):
        return NextStep(
            "Uzupełnij konfigurację eScriptorium",
            "Wymagane są adres, token, projekt i skrypt pisma.",
            "Adapter nie ma kompletu danych potrzebnych do tworzenia dokumentów.",
            "Sprawdź konfigurację",
            f"{base}#configuration",
            2,
            True,
        ).as_dict()
    if not state.get("providerOnline"):
        return NextStep(
            "Napraw połączenie z eScriptorium",
            "Sprawdź kontenery, adres i token API.",
            state.get("providerError") or "Lokalna usługa HTR nie odpowiada.",
            "Pokaż diagnostykę",
            f"{base}#configuration",
            3,
            True,
        ).as_dict()
    if int(state.get("totalPages") or 0) == 0:
        return NextStep(
            "Dodaj pierwsze zdjęcia dziennika",
            "Wgraj JPG, PNG, TIFF albo wielostronicowy PDF.",
            "Nie ma jeszcze żadnych lokalnych stron.",
            "Dodaj strony",
            f"{base}#upload",
            4,
        ).as_dict()
    if int(state.get("segmentingPages") or 0):
        count = int(state["segmentingPages"])
        return NextStep(
            f"Segmentacja trwa dla {count} stron",
            "Kraken wykrywa regiony i linie. To jeszcze nie jest rozpoznawanie tekstu.",
            "Po zakończeniu strony automatycznie zmienią status na „linie gotowe”.",
            "Pokaż zadania",
            f"{base}#jobs",
            5,
        ).as_dict()
    if int(state.get("pendingSegmentation") or 0):
        count = int(state["pendingSegmentation"])
        return NextStep(
            f"Uruchom segmentację {count} stron",
            "Wykryj regiony, linie i kolejność czytania.",
            "Co najmniej jedna strona nie ma segmentacji.",
            "Przejdź do segmentacji",
            f"{base}#segmentation",
            5,
        ).as_dict()
    if int(state.get("segmentationIssues") or 0):
        return NextStep(
            "Popraw oznaczone błędy segmentacji",
            "Skoryguj tylko strony oznaczone jako wymagające uwagi.",
            "System lub użytkownik oznaczył nieprawidłową geometrię linii.",
            "Otwórz segmentację",
            f"{base}#segmentation",
            6,
        ).as_dict()
    if int(state.get("transcribingPages") or 0):
        count = int(state["transcribingPages"])
        return NextStep(
            f"Rozpoznawanie tekstu trwa dla {count} stron",
            "Model HTR odczytuje tekst z wcześniej wykrytych linii.",
            "Po zakończeniu pojawią się linie do sprawdzenia i poprawienia.",
            "Pokaż zadania",
            f"{base}#jobs",
            7,
        ).as_dict()
    if int(state.get("pendingTranscription") or 0):
        count = int(state["pendingTranscription"])
        return NextStep(
            f"Uruchom transkrypcję {count} stron",
            "Zastosuj wybrany lokalny model rozpoznawania.",
            "Segmentacja jest gotowa, ale brakuje predykcji.",
            "Przejdź do transkrypcji",
            f"{base}#transcription",
            7,
        ).as_dict()
    if int(state.get("unreviewedLines") or 0):
        count = int(state["unreviewedLines"])
        return NextStep(
            f"Sprawdź {count} rozpoznanych linii",
            "Najpierw pokazane zostaną linie o najniższej pewności.",
            "Predykcje nie są jeszcze zatwierdzonym ground truth.",
            "Otwórz korektę",
            f"{base}#correction",
            8,
        ).as_dict()

    approved = int(state.get("approvedTrainingLines") or 0)
    minimum = int(state.get("trainingMinimum") or 200)
    if approved < minimum:
        missing = minimum - approved
        return NextStep(
            f"Zatwierdź jeszcze {missing} linii",
            "Buduj reprezentatywny zbiór polskich i angielskich zapisów.",
            f"Do zalecanego minimum treningowego brakuje {missing} linii.",
            "Pokaż zbiór",
            f"{base}#dataset",
            9,
        ).as_dict()
    if not state.get("hasCustomModel"):
        return NextStep(
            "Wytrenuj model v1",
            f"Masz {approved} zatwierdzonych linii gotowych do treningu.",
            "Osiągnięto minimalny rozmiar zbioru i nie ma własnego modelu.",
            "Utwórz trening",
            f"{base}#training",
            10,
        ).as_dict()
    if int(state.get("unevaluatedModels") or 0):
        return NextStep(
            "Oceń model kandydujący",
            "Uruchom ewaluację na stałym zbiorze testowym.",
            "Istnieje model bez wyniku CER/WER.",
            "Otwórz ocenę",
            f"{base}#models",
            11,
        ).as_dict()
    if state.get("betterCandidate"):
        return NextStep(
            "Porównaj kandydata z aktywnym modelem",
            "Aktywacja wymaga ręcznej decyzji.",
            "Kandydat ma niższy testowy CER niż aktywny model.",
            "Porównaj modele",
            f"{base}#models",
            12,
        ).as_dict()
    if int(state.get("newLinesSinceTraining") or 0) >= int(
        state.get("retrainAfterLines") or 300
    ):
        return NextStep(
            "Wytrenuj kolejną wersję modelu",
            "Od poprzedniego treningu przybyła wystarczająca liczba danych.",
            "Przekroczono próg automatycznej sugestii ponownego treningu.",
            "Utwórz trening",
            f"{base}#training",
            13,
        ).as_dict()
    if int(state.get("exportablePages") or 0):
        return NextStep(
            "Zaimportuj zatwierdzony wpis do dziennika",
            "Połącz linie, sprawdź strukturę i utwórz wpis.",
            "Co najmniej jedna kompletna strona jest zatwierdzona.",
            "Przejdź do eksportu",
            f"{base}#export",
            14,
        ).as_dict()
    return NextStep(
        "Dodaj kolejne strony",
        "Bieżąca kolejka nie zawiera pilnej pracy.",
        "Wszystkie dostępne strony zostały przetworzone.",
        "Dodaj strony",
        f"{base}#upload",
        15,
    ).as_dict()
