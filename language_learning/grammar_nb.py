"""Bokmål rules only. Practical buckets are not certified CEFR assignments."""
from __future__ import annotations

VERSION = "1.0.0"

_CANDIDATES = [
    ("A1_BASIC_MAIN_CLAUSE_ORDER", "Subject-first main clause", "DEFERRED", "The subject usually precedes the finite verb in a neutral main clause.", "Clause boundaries and ellipsis need broader validation."),
    ("A1_YES_NO_QUESTION", "Yes/no questions", "DEFERRED", "A yes/no question commonly starts with the finite verb.", "Inversion alone cannot distinguish questions, conditionals and quotations."),
    ("A1_WH_QUESTION", "Question words", "DEFERRED", "Question words introduce questions about people, places or other details.", "Subject questions and embedded questions require separate rules."),
    ("A1_NOUN_DEFINITENESS", "Definite and indefinite nouns", "SUPPORTED", "A noun's form can mark whether something is definite or indefinite.", "Detects explicit noun morphology, not discourse meaning or article correctness."),
    ("A1_NOUN_NUMBER", "Singular and plural nouns", "SUPPORTED", "Noun forms can distinguish one thing from several.", "Ambiguous or absent number features are excluded; proper names are excluded."),
    ("A1_PRESENT_TENSE", "Present tense", "SUPPORTED", "A finite present verb can describe a current or habitual situation.", "Only lexical finite verbs; does not infer time meaning or correctness."),
    ("A1_SIMPLE_PAST", "Simple past", "SUPPORTED", "A finite past verb presents a past situation.", "Only lexical finite verbs, never participles or auxiliary chains."),
    ("A1_BASIC_POSSESSIVE", "Possessives", "DEFERRED", "Possessive words can come before or after a noun.", "Genitives and possessive attachment require a broader fixture set."),
    ("A1_BASIC_ADJECTIVE_AGREEMENT", "Adjective agreement", "DEFERRED", "Adjectives can change with the noun they describe.", "Syncretic forms do not prove an agreement contrast."),
    ("A2_V2_FRONTED_ELEMENT", "Fronted elements and V2", "DEFERRED", "When another element starts a main clause, the finite verb usually precedes the subject.", "Token positions alone do not prove constituent positions; coordination and embedding need validation."),
    ("A2_BASIC_SUBORDINATE_CLAUSE", "Subordinate clauses", "DEFERRED", "A subordinate clause forms part of a larger sentence.", "Complement and adverbial clause classes need separate validated rules."),
    ("A2_SUBORDINATE_NEGATION", "Negation in subordinate clauses", "DEFERRED", "In many subordinate clauses, ikke comes before the finite verb.", "Scope, embedding and fragment handling require broader fixtures."),
    ("A2_PRESENT_PERFECT", "Present perfect", "SUPPORTED", "A present form of ha combines with a past participle.", "Requires a direct ha auxiliary and a lexical participle; excludes passive auxiliaries."),
    ("A2_MODAL_CONSTRUCTION", "Modal plus infinitive", "SUPPORTED", "A modal verb combines with an infinitive to express possibility, obligation or intention.", "Only direct UD auxiliary links for six common modals; excludes lexical uses."),
    ("A2_COMPARISON", "Comparison", "DEFERRED", "Comparative and superlative forms compare qualities.", "Irregular and periphrastic comparisons need reviewed fixtures."),
    ("A2_ADJECTIVE_DEFINITENESS_AGREEMENT", "Definite adjective phrases", "DEFERRED", "Definite noun phrases often use a determiner and a definite adjective form.", "Morphological syncretism and determiner attachment need review."),
    ("B1_VARIED_SUBORDINATE_CLAUSE", "Varied subordinate clauses", "DEFERRED", "Different linking words express different relations between clauses.", "Broad semantic class is outside this small validated release."),
    ("B1_RELATIVE_CLAUSE", "Relative clauses with som", "SUPPORTED", "A relative clause adds information about a noun; som can connect the clause to it.", "Only explicit som attached to a finite acl:relcl verb with a noun antecedent; zero relatives and copular relatives excluded."),
    ("B1_CONDITIONAL", "Conditionals", "DEFERRED", "Conditional clauses describe a condition for another situation.", "Hypothetical meaning cannot be inferred from a conjunction alone."),
    ("B1_PASSIVE", "Passive constructions", "DEFERRED", "Passive constructions put the affected person or thing in focus.", "s-passives and bli-participles need ambiguity and hard-negative validation."),
    ("B1_COMPLEX_WORD_ORDER", "Complex word order", "DEFERRED", "Longer sentences combine main-clause and subordinate-clause order.", "Too broad for one defensible detector in the current scope."),
]

RULES = {
    "A1_NOUN_DEFINITENESS": "NOUN with unambiguous Definite=Def or Ind and a dependency relation.",
    "A1_NOUN_NUMBER": "NOUN with unambiguous Number=Sing or Plur and a dependency relation.",
    "A1_PRESENT_TENSE": "VERB, VerbForm=Fin, Tense=Pres; no aux dependent.",
    "A1_SIMPLE_PAST": "VERB, VerbForm=Fin, Tense=Past; no aux dependent.",
    "A2_PRESENT_PERFECT": "VERB VerbForm=Part with direct aux lemma=ha, VerbForm=Fin, Tense=Pres; no passive aux.",
    "A2_MODAL_CONSTRUCTION": "VERB VerbForm=Inf with direct finite AUX aux whose lemma is kunne, måtte, skulle, ville, burde or tørre.",
    "B1_RELATIVE_CLAUSE": "Finite VERB acl:relcl attached to NOUN; direct som child with mark/nsubj/obj relation.",
}

CATALOGUE = tuple({"patternId": key, "patternVersion": VERSION, "detectorId": "nb." + key.lower(),
                   "detectorVersion": VERSION, "name": name, "bucket": key[:2], "status": status,
                   "explanation": explanation, "rule": RULES.get(key, "Not implemented"), "limitations": limitations}
                  for key, name, status, explanation, limitations in _CANDIDATES)


def detect(sentence):
    words = sentence["tokens"]
    by_index = {word["index"]: word for word in words}
    children = {}
    for word in words:
        children.setdefault(word["head"], []).append(word)
    matches = []
    def emit(pattern, roles):
        matches.append({"patternId": pattern, "roles": roles})
    for word in words:
        morphology = word["morphology"]
        if not word.get("relation"):
            continue
        if word["pos"] == "NOUN":
            if morphology.get("Definite") in {"Def", "Ind"}:
                emit("A1_NOUN_DEFINITENESS", {"HEAD_NOUN": word})
            if morphology.get("Number") in {"Sing", "Plur"}:
                emit("A1_NOUN_NUMBER", {"HEAD_NOUN": word})
        if word["pos"] != "VERB":
            continue
        dependents = children.get(word["index"], [])
        auxiliaries = [item for item in dependents if item["relation"].split(":")[0] == "aux"]
        if morphology.get("VerbForm") == "Fin" and not auxiliaries:
            if morphology.get("Tense") == "Pres":
                emit("A1_PRESENT_TENSE", {"FINITE_VERB": word})
            if morphology.get("Tense") == "Past":
                emit("A1_SIMPLE_PAST", {"FINITE_VERB": word})
        for auxiliary in auxiliaries:
            if auxiliary["pos"] != "AUX" or auxiliary["relation"] != "aux" or auxiliary["morphology"].get("VerbForm") != "Fin":
                continue
            if morphology.get("VerbForm") == "Part" and auxiliary["lemma"] == "ha" and auxiliary["morphology"].get("Tense") == "Pres" and not any(a["relation"] == "aux:pass" for a in auxiliaries):
                emit("A2_PRESENT_PERFECT", {"AUXILIARY": auxiliary, "PARTICIPLE": word})
            if morphology.get("VerbForm") == "Inf" and auxiliary["lemma"] in {"kunne", "måtte", "skulle", "ville", "burde", "tørre"}:
                emit("A2_MODAL_CONSTRUCTION", {"AUXILIARY": auxiliary, "INFINITIVE": word})
        antecedent = by_index.get(word["head"])
        if word["relation"] == "acl:relcl" and morphology.get("VerbForm") == "Fin" and antecedent and antecedent["pos"] == "NOUN":
            for marker in dependents:
                if marker["lemma"] == "som" and marker["relation"] in {"mark", "nsubj", "obj"}:
                    emit("B1_RELATIVE_CLAUSE", {"HEAD_NOUN": antecedent, "RELATIVE_MARKER": marker, "FINITE_VERB": word})
    return matches


def registry(language_code):
    return (CATALOGUE, detect) if language_code == "nb" else ((), lambda sentence: [])
