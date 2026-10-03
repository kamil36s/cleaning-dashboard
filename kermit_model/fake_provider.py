"""Deterministic fixture provider. It has no network or source access."""

import json

from .provider import ModelResult


class FakeProvider:
    def __init__(self, response=None, failure=None):
        self.response = response
        self.failure = failure

    def generate(self, messages, config):
        if self.failure:
            raise self.failure
        if self.response is None:
            user = messages[1]["content"]
            if "Latest user message: " in user:
                question = json.loads(user.split("Latest user message: ", 1)[1])
                answer = ("One possibility: consider a clearer progress view. This is a proposal, not a verified current feature."
                          if "Discuss possible improvements" in user else
                          "Hey! What's up?" if question.casefold().strip("! .") in ("hi", "hi, kermit", "hello", "hey")
                          else "I can chat about that. What would you like to explore?")
                response = json.dumps({"answer": answer, "citedEvidenceIds": [], "uncertainty": [],
                                       "conflictsMentioned": []})
                return ModelResult(response, "fake", config.model, 0, "stop", {})
            question = json.loads(user.split("Question: ", 1)[1].split("\n", 1)[0])
            evidence = json.loads(user.split("<untrusted_evidence_json>\n", 1)[1].split("\n</untrusted_evidence_json>", 1)[0])
            ids = [e["evidenceId"] for e in evidence["evidence"][:3]]
            subs = sorted({e["subsystem"] for e in evidence["evidence"] if e.get("subsystem")})
            conflicts = [c["id"] for c in evidence["conflicts"]]
            if "never indexed" in question.casefold():
                ids = []
                conflicts = []
                answer = "The supplied evidence is insufficient to verify an answer about an unindexed record."
            else:
                answer = ("Available evidence concerns " + ", ".join(subs) + ".") if ids else "The supplied evidence is insufficient to verify an answer."
            if conflicts:
                answer += " Registered findings remain unresolved: " + ", ".join(conflicts) + "."
            body = {"answer": answer, "citedEvidenceIds": ids, "uncertainty": evidence["uncertainty"], "conflictsMentioned": conflicts}
            response = json.dumps(body, ensure_ascii=False)
        else:
            response = self.response
        return ModelResult(response, "fake", config.model, 0, "stop", {})

    def health(self, config):
        return {"provider": "fake", "state": "ready", "reachable": True, "modelAvailable": True, "latencyMs": 0}
