"""Isolated real-Edge route and layout smoke for Phase 11.6."""

import subprocess
from datetime import datetime

from language_learning.study_session import _candidate, compose
from tests.test_language_api import LanguageApiTests


def main():
    fixture = LanguageApiTests()
    fixture.setUp()
    try:
        url = f"http://127.0.0.1:{fixture.port}/language.html#study-session"
        script = "scripts/smoke_language_study_session_cdp.mjs"
        for mode in ("empty", "populated"):
            if mode == "populated":
                candidates = [
                    _candidate("ANKI_DUE", "due", "Anki due", "Five due cards", "#reviews"),
                    _candidate("CLOZE_MISTAKES", "mistakes", "Cloze mistakes", "Two current clusters", "#cloze"),
                    _candidate("CONTINUE_READING", "reader", "Continue Reader", "Text is 62% complete", "#reader"),
                    _candidate("CONTINUE_LISTENING", "listen", "Continue Listening", "One unfinished text", "#listening"),
                    _candidate("CURRICULUM_GAP", "work", "Work vocabulary", "Eight eligible items", "#curriculum"),
                ]
                def preview(profile_id, minutes):
                    return {"ok": True, "data": compose(profile_id, minutes, datetime.now().date().isoformat(), candidates)}
                fixture.service.study_session = preview
            for width, height in ((1440, 1000), (430, 900), (390, 844)):
                subprocess.run(["node", script, url, str(width), str(height), mode], check=True, timeout=45)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
