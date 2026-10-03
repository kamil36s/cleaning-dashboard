# Bokmal Core Grammar catalogue (Phase 11)

A1/A2/B1 are practical learner-oriented scope buckets, not certified CEFR assignments. Only SUPPORTED matches enter authoritative evidence. There are 7 supported, 0 experimental and 14 deferred candidates. Every identifier is retained in the UI.

Rules inspect Stanza hypotheses; they do not certify correctness or learner knowledge. Fixtures are original synthetic Bokmal sentences. grammar_cases.json contains independent expectations; grammar_parses.json retains inspected offline Stanza 1.14.0 output. Tests also reject ambiguous morphology and broken auxiliary links.

All pattern and detector contract versions are 1.0.0. Deferred entries reserve an identity but have no executable rule.

Review compatibility: same canonical sentence, pattern semantic version, exact role/token spans, POS/morphology, dependency relation and canonical head identity. Detector implementation version may change. Any change to those semantic inputs resets effective review; older runs/reviews remain exported.

## A1_BASIC_MAIN_CLAUSE_ORDER

- Practical bucket: A1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a1_basic_main_clause_order / 1.0.0
- Learner explanation: The subject usually precedes the finite verb in a neutral main clause.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Clause boundaries and ellipsis need broader validation.

## A1_YES_NO_QUESTION

- Practical bucket: A1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a1_yes_no_question / 1.0.0
- Learner explanation: A yes/no question commonly starts with the finite verb.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Inversion alone cannot distinguish questions, conditionals and quotations.

## A1_WH_QUESTION

- Practical bucket: A1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a1_wh_question / 1.0.0
- Learner explanation: Question words introduce questions about people, places or other details.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Subject questions and embedded questions require separate rules.

## A1_NOUN_DEFINITENESS

- Practical bucket: A1
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a1_noun_definiteness / 1.0.0
- Learner explanation: A noun's form can mark whether something is definite or indefinite.
- Technical evidence/rule: NOUN with unambiguous Definite=Def or Ind and a dependency relation.
- Positive fixtures: Hun har lest boken.; Jeg har en bil.; Bilen som kommer, er stor.; en bil; bilen; bilene; den store bilen; bilen min
- Hard-negative fixtures: Jeg jobber i Oslo.; Oslo; jeg
- Known limitations / evaluation decision: Detects explicit noun morphology, not discourse meaning or article correctness.

## A1_NOUN_NUMBER

- Practical bucket: A1
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a1_noun_number / 1.0.0
- Learner explanation: Noun forms can distinguish one thing from several.
- Technical evidence/rule: NOUN with unambiguous Number=Sing or Plur and a dependency relation.
- Positive fixtures: Hun har lest boken.; Jeg har en bil.; Bilen som kommer, er stor.; en bil; bilen; biler; bilene; en stor bil; et stort hus; store biler; min bil; Bilen er større enn huset.
- Hard-negative fixtures: Jeg jobber i Oslo.; Oslo; jeg
- Known limitations / evaluation decision: Ambiguous or absent number features are excluded; proper names are excluded.

## A1_PRESENT_TENSE

- Practical bucket: A1
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a1_present_tense / 1.0.0
- Learner explanation: A finite present verb can describe a current or habitual situation.
- Technical evidence/rule: VERB, VerbForm=Fin, Tense=Pres; no aux dependent.
- Positive fixtures: Jeg jobber i Oslo.; Hun leser.; Jeg kommer.; Jeg tror at han ikke kommer.; Jeg jobber ikke i dag.; På mandag begynner jeg på jobb.; Kommer du i morgen?; Hvor bor du?; Ærlige Øyvind kjøper øl på Ås.; Jeg leser, og hun jobber.
- Hard-negative fixtures: Jeg jobbet.; Hun leste.; Jeg har jobbet.; Hun har lest boken.; en bil; bilen; å jobbe
- Known limitations / evaluation decision: Only lexical finite verbs; does not infer time meaning or correctness.

## A1_SIMPLE_PAST

- Practical bucket: A1
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a1_simple_past / 1.0.0
- Learner explanation: A finite past verb presents a past situation.
- Technical evidence/rule: VERB, VerbForm=Fin, Tense=Past; no aux dependent.
- Positive fixtures: Jeg jobbet.; Hun leste.; I går kjøpte jeg en bok.
- Hard-negative fixtures: Jeg jobber i Oslo.; Hun leser.; Jeg har jobbet.; Hun har lest boken.; Jeg hadde jobbet.; en bil; bilen; å jobbe; På mandag begynner jeg på jobb.; Jeg leser, og hun jobber.; Boken blir lest.
- Known limitations / evaluation decision: Only lexical finite verbs, never participles or auxiliary chains.

## A1_BASIC_POSSESSIVE

- Practical bucket: A1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a1_basic_possessive / 1.0.0
- Learner explanation: Possessive words can come before or after a noun.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Genitives and possessive attachment require a broader fixture set.

## A1_BASIC_ADJECTIVE_AGREEMENT

- Practical bucket: A1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a1_basic_adjective_agreement / 1.0.0
- Learner explanation: Adjectives can change with the noun they describe.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Syncretic forms do not prove an agreement contrast.

## A2_V2_FRONTED_ELEMENT

- Practical bucket: A2
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a2_v2_fronted_element / 1.0.0
- Learner explanation: When another element starts a main clause, the finite verb usually precedes the subject.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Token positions alone do not prove constituent positions; coordination and embedding need validation.

## A2_BASIC_SUBORDINATE_CLAUSE

- Practical bucket: A2
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a2_basic_subordinate_clause / 1.0.0
- Learner explanation: A subordinate clause forms part of a larger sentence.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Complement and adverbial clause classes need separate validated rules.

## A2_SUBORDINATE_NEGATION

- Practical bucket: A2
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a2_subordinate_negation / 1.0.0
- Learner explanation: In many subordinate clauses, ikke comes before the finite verb.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Scope, embedding and fragment handling require broader fixtures.

## A2_PRESENT_PERFECT

- Practical bucket: A2
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a2_present_perfect / 1.0.0
- Learner explanation: A present form of ha combines with a past participle.
- Technical evidence/rule: VERB VerbForm=Part with direct aux lemma=ha, VerbForm=Fin, Tense=Pres; no passive aux.
- Positive fixtures: Jeg har jobbet.; Hun har lest boken.
- Hard-negative fixtures: Jeg jobber i Oslo.; Hun leser.; Jeg jobbet.; Hun leste.; Jeg hadde jobbet.; Jeg har en bil.; Jeg kan komme i morgen.; Du må lese boken.; Jeg vil ha kaffe.; I går kjøpte jeg en bok.; en stor bil; Boken blir lest.; Jeg har
- Known limitations / evaluation decision: Requires a direct ha auxiliary and a lexical participle; excludes passive auxiliaries.

## A2_MODAL_CONSTRUCTION

- Practical bucket: A2
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.a2_modal_construction / 1.0.0
- Learner explanation: A modal verb combines with an infinitive to express possibility, obligation or intention.
- Technical evidence/rule: VERB VerbForm=Inf with direct finite AUX aux whose lemma is kunne, måtte, skulle, ville, burde or tørre.
- Positive fixtures: Jeg kan komme i morgen.; Du må lese boken.; Jeg vil ha kaffe.
- Hard-negative fixtures: Jeg jobber i Oslo.; Hun leser.; Jeg har jobbet.; Jeg har en bil.; Jeg kommer.; å jobbe; et stort hus
- Known limitations / evaluation decision: Only direct UD auxiliary links for six common modals; excludes lexical uses.

## A2_COMPARISON

- Practical bucket: A2
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a2_comparison / 1.0.0
- Learner explanation: Comparative and superlative forms compare qualities.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Irregular and periphrastic comparisons need reviewed fixtures.

## A2_ADJECTIVE_DEFINITENESS_AGREEMENT

- Practical bucket: A2
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.a2_adjective_definiteness_agreement / 1.0.0
- Learner explanation: Definite noun phrases often use a determiner and a definite adjective form.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Morphological syncretism and determiner attachment need review.

## B1_VARIED_SUBORDINATE_CLAUSE

- Practical bucket: B1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.b1_varied_subordinate_clause / 1.0.0
- Learner explanation: Different linking words express different relations between clauses.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Broad semantic class is outside this small validated release.

## B1_RELATIVE_CLAUSE

- Practical bucket: B1
- Status: SUPPORTED
- Pattern version: 1.0.0
- Detector: nb.b1_relative_clause / 1.0.0
- Learner explanation: A relative clause adds information about a noun; som can connect the clause to it.
- Technical evidence/rule: Finite VERB acl:relcl attached to NOUN; direct som child with mark/nsubj/obj relation.
- Positive fixtures: Bilen som kommer, er stor.; Jeg ser mannen som bor her.
- Hard-negative fixtures: Jeg jobber i Oslo.; Jeg jobber som lærer.; Jeg tror at han ikke kommer.; Jeg jobber ikke i dag.; Kommer du i morgen?; Hvor bor du?; Ærlige Øyvind kjøper øl på Ås.; som; Bilen er større enn huset.
- Known limitations / evaluation decision: Only explicit som attached to a finite acl:relcl verb with a noun antecedent; zero relatives and copular relatives excluded.

## B1_CONDITIONAL

- Practical bucket: B1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.b1_conditional / 1.0.0
- Learner explanation: Conditional clauses describe a condition for another situation.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Hypothetical meaning cannot be inferred from a conjunction alone.

## B1_PASSIVE

- Practical bucket: B1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.b1_passive / 1.0.0
- Learner explanation: Passive constructions put the affected person or thing in focus.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: s-passives and bli-participles need ambiguity and hard-negative validation.

## B1_COMPLEX_WORD_ORDER

- Practical bucket: B1
- Status: DEFERRED
- Pattern version: 1.0.0
- Detector: nb.b1_complex_word_order / 1.0.0
- Learner explanation: Longer sentences combine main-clause and subordinate-clause order.
- Technical evidence/rule: Not implemented
- Positive fixtures: None; not promoted to supported.
- Hard-negative fixtures: No validated detector fixture set; deferred.
- Known limitations / evaluation decision: Too broad for one defensible detector in the current scope.
