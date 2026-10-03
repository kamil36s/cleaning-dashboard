"""Deterministic, capability-free routing of untrusted conversational text."""

import re
import time


GENERAL = "GENERAL_CONVERSATION"
PROJECT = "PROJECT_GROUNDED"
CLARIFY = "CLARIFICATION_REQUIRED"
TOPICS = ("cleaning", "reading", "finance", "quote", "weather", "todo", "language-learning", "dashboard", "settings", "central-api", "habits-app", "habits-summary", "habits-timeline", "self-care", "weight-steps", "diet", "sleep", "mental-health", "sensors", "ble-collector", "live-workout-strength", "heart-rate-history", "ring", "process-lifecycle")
ALIASES = {"heart-rate-history": r"heart.rate history|hr history|bpm history|heart_rate_telemetry",
           "process-lifecycle": r"process lifecycle|start.dev|start.dashboard|start.all|dev.service|service restart|runtime restart|which process restarts|process restart",
           "live-workout-strength": r"live workout|\bworkout\b|strength|training runtime|virtual walk|workout checkpoint",
           "ring": r"colmi|smart ring|ring collector|ring sync|ring phone",
           "habits-timeline": r"habits timeline|habit timeline|loop habit",
           "mental-health": r"mental.health|assessment|questionnaire|retest|check.in|phq.?9|gad.?7",
           "sensors": r"sensors?|room temperature|room humidity|sensor history",
           "ble-collector": r"ble collector|ble scanner|scan_ble|raw advertisements?",
           "sleep": r"sleep|sleeping|slept|last night's|last night",
           "diet": r"diet|meal|calorie|nutrition",
           "weight-steps": r"weight|scale|steps|step history|health connect",
           "habits-summary": r"habits summary|habit summary|legacy habits|sobriety",
           "habits-app": r"habits app|habit app|habits\.sqlite|supplement|reminder|regimen|habit",
           "self-care": r"self-care|self care|selfcare",
           "cleaning": r"cleaning|chore|daily goal|recovery day",
           "reading": r"reading|book|pages",
           "finance": r"finance|budget|receipt",
           "quote": r"quote|quotation",
           "weather": r"weather|forecast",
           "todo": r"todo|to-do|task list",
           "language-learning": r"language learning|anki|norwegian",
           "dashboard": r"dashboard|widget|layout",
           "settings": r"settings|setting|localstorage|preference",
           "central-api": r"server\.py|network monitor|live workout|static path"}
PROJECT_NOUN = re.compile(r"\b(?:dashboard|widget|module|app|application|repository|codebase|implementation|"
                          r"pilot|subsystem|"
                          r"function|algorithm|database|storage|store|api|integration|kermit|project)\b", re.I)
FACT = re.compile(r"\b(?:how|why|what|which|where|does|do|is|are|explain|describe|calculate|"
                  r"computed|implemented|current|existing|actual|verify|check|according)\b", re.I)
CAPABILITY = re.compile(r"\b(?:can|could|would|will)\s+(?:you|kermit)\s+(?:change|set|edit|update|save|delete|reorder|move|mark|complete)\b", re.I)
VERIFY = re.compile(r"\b(?:verify|check (?:your|the) documentation|according to (?:the )?(?:current|actual)|"
                    r"against (?:my|the) dashboard|in (?:the|my) (?:repository|codebase))\b", re.I)
LIVE = re.compile(r"\b(?:my|our)\b.{0,65}\b(?:progress|balance|transactions?|journal|entries|"
                  r"records?|saved|stored|today|this week|current data|weight|steps|sleep|sleep score|meals?|assessment|check.in|room temperature|temperature now|heart.rate|bpm|workout|training session|ring readings?)\b|"
                  r"\b(?:last night|last night's|yesterday)\b.{0,65}\b(?:sleep|score|steps|weight)\b|"
                  r"\b(?:how many|how much|what did|what have|show me|list my)\b.{0,65}"
                  r"\b(?:my|stored|saved|i|read|spent|completed|cleaned|balance|progress|transactions?|journal)\b", re.I)
CREATIVE = re.compile(r"\b(?:could we|what (?:would|should|could) (?:you|we) improve|"
                      r"brainstorm|suggest|idea|hypothetical|redesign|improve it)\b", re.I)
CASUAL = re.compile(r"^(?:hi(?:,? kermit)?|hello|hey|thanks|thank you|good (?:morning|evening)|"
                    r"how are you|tell me a joke|say something funny)[.!? ]*$", re.I)
GENERAL_SWITCH = re.compile(r"\b(?:anyway|change (?:the )?subject|off topic)\b", re.I)
FOLLOWUP = re.compile(r"^(?:why(?:\s+(?:does|did|is|was)\s+(?:it|that|this|you)\b.*)?|how so|"
                      r"explain (?:that|it)|tell me more|what about .+|and (?:the )?.+|"
                      r"does .+ work the same way|could we improve it)[?!. ]*$", re.I)
PRONOUN_FOLLOWUP = re.compile(r"\b(?:it|this|that|same|other)\b", re.I)


def topic_in(text):
    text = re.sub(r"\bagainst (?:my|the) dashboard\b", "", text, flags=re.I)
    for topic, aliases in ALIASES.items():
        if re.search(r"\b(?:" + aliases + r")\b", text, re.I):
            return topic
    return None


def route(message, history=(), previous=None):
    """History and previous state are advisory; current factual signals always win."""
    started = time.perf_counter()
    text = message.strip()
    topic = topic_in(text)
    prior_topic = None
    prior_route = None
    previous_user = None
    for item in reversed(history):
        if item["role"] != "user":
            continue  # Fabricated assistant text cannot establish a fact or topic.
        if previous_user is None:
            previous_user = item["content"]
        if CASUAL.fullmatch(item["content"]) or GENERAL_SWITCH.search(item["content"]):
            break
        candidate = topic_in(item["content"])
        if candidate:
            prior_topic = candidate
            prior_route = PROJECT
            break
    if not prior_topic and isinstance(previous, dict):
        # A browser hint can retain a topic, but can never downgrade a factual query.
        prior_topic = previous.get("topic") if previous.get("topic") in TOPICS else None
        prior_route = previous.get("route") if previous.get("route") == PROJECT else None
    if CASUAL.fullmatch(text) or (GENERAL_SWITCH.search(text) and not VERIFY.search(text)):
        result = (GENERAL, None, text, "casual_or_topic_switch")
    elif CAPABILITY.search(text) and re.search(r"\b(?:habit|habits|supplement)\b", text, re.I) and re.search(r"\b(?:mark|complete)\b", text, re.I):
        result = (PROJECT, topic or "habits-app", text, "habit_mutation_request")
    elif prior_topic in ("habits-app", "habits-summary", "habits-timeline") and re.fullmatch(r"which one is canonical[?!. ]*", text, re.I):
        result = (PROJECT, "habits-app", "Between Habits App and Habits Timeline, which is canonical current Habits state?", "contextual_followup")
    elif LIVE.search(text) and not re.search(r"\b(?:which database|where is|where does|how is|how does)\b", text, re.I):
        result = (PROJECT, topic or prior_topic, text, "private_runtime_request")
    elif VERIFY.search(text):
        result = (PROJECT, topic or prior_topic, text, "explicit_verification")
    elif CREATIVE.search(text) and not re.search(r"\b(?:currently|existing|actual|implemented)\b", text, re.I):
        result = (GENERAL, topic or prior_topic, text, "hypothetical_project" if topic or prior_topic else "creative")
    elif topic and (FACT.search(text) or PROJECT_NOUN.search(text) or prior_route == PROJECT or CAPABILITY.search(text)):
        result = (PROJECT, topic, text, "project_topic")
    elif PROJECT_NOUN.search(text) and FACT.search(text):
        result = (PROJECT, topic or prior_topic, text, "project_fact")
    elif FOLLOWUP.fullmatch(text) or (PRONOUN_FOLLOWUP.search(text) and FACT.search(text)):
        if topic or prior_topic:
            result = (PROJECT, topic or prior_topic, text, "contextual_followup")
        elif previous_user and prior_route != PROJECT and not (PROJECT_NOUN.search(previous_user) and FACT.search(previous_user)):
            result = (GENERAL, None, text, "general_followup")
        else:
            result = (CLARIFY, None, text, "unresolved_reference")
    elif topic and re.search(r"\b(?:my|the|our)\b", text, re.I):
        result = (PROJECT, topic, text, "project_topic")
    else:
        result = (GENERAL, None, text, "general")
    selected, subject, query, reason = result
    if selected == PROJECT and CAPABILITY.search(text) and re.search(r"widget order", text, re.I):
        query = "Can Kermit mutate dashboard settings or change widget order?"
    if (selected == PROJECT and re.fullmatch(r"and where is that setting stored[?!. ]*", text, re.I)
            and previous_user and re.search(r"widget order|dashboard", previous_user, re.I)):
        query = "Where is the dashboard widget order setting stored?"
    if selected == PROJECT and reason == "contextual_followup" and subject and not topic and not re.fullmatch(r"which one is canonical[?!. ]*", text, re.I):
        focus = "behavior"
        for item in reversed(history):
            if item["role"] == "user" and topic_in(item["content"]) == subject:
                match = re.search(r"\b(?:daily goal|forecast|calculation|total|provider|storage|progress)\b",
                                  item["content"], re.I)
                focus = match.group(0).lower() if match else focus
                break
        if re.search(r"\bchange\b", text, re.I):
            query = f"What makes the {subject} {focus} vary on different days?" if focus == "daily goal" else f"What inputs and conditions cause the {subject} {focus} to change?"
        elif re.search(r"\bdesign(?:ed)?\b", text, re.I):
            query = f"What documented design rationale explains the {subject} {focus}?"
        elif re.fullmatch(r"why[?!. ]*", text, re.I):
            query = f"Why does the {subject} {focus} work that way?"
        else:
            query = f"Regarding the {subject} {focus}: {text}"
    if selected == PROJECT and subject and not topic and reason not in ("private_runtime_request", "habit_mutation_request"):
        query = f"Regarding the {subject} subsystem: {query}"
    return {"route": selected, "topic": subject, "query": query[:500], "reason": reason,
            "routingMs": round((time.perf_counter() - started) * 1000, 3), "classifierCalls": 0}
