from datetime import date

import server


def test_kitchen_namedays_come_from_complete_local_calendar():
    assert len(server.POLISH_NAMEDAYS) == 366
    assert server.daily_kitchen_info(date(2026, 10, 1))["namedays"][:2] == ["Danuta", "Remigiusz"]
    assert "Roman" in server.daily_kitchen_info(date(2024, 2, 29))["namedays"]
