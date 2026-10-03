import sqlite3
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest import mock
from http.server import ThreadingHTTPServer

import server


class FilmStartupSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        server.ensure_films_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_existing_library_poster_is_reused_without_remote_request(self):
        film_id = server.upsert_film_library_row(
            self.conn,
            {
                "canonical_key": "title:example-film:2026",
                "title": "Example Film",
                "release_year": 2026,
                "poster_url": "https://example.test/poster.jpg",
                "poster_source": "manual",
            },
            fetch_missing_poster=False,
        )

        with mock.patch.object(server, "wiki_poster") as wiki_poster:
            updated_id = server.upsert_film_library_row(
                self.conn,
                {
                    "canonical_key": "title:example-film:2026",
                    "title": "Example Film",
                    "release_year": 2026,
                },
            )

        self.assertEqual(updated_id, film_id)
        wiki_poster.assert_not_called()
        row = self.conn.execute(
            "SELECT poster_url, poster_source FROM film_library WHERE id = ?",
            (film_id,),
        ).fetchone()
        self.assertEqual(row["poster_url"], "https://example.test/poster.jpg")
        self.assertEqual(row["poster_source"], "manual")

    def test_watchlist_sync_is_local_only_by_default(self):
        columns = ", ".join(f"{name} {column_type}" for name, column_type in server.COLUMNS)
        self.conn.execute(f"CREATE TABLE watchlist ({columns})")
        self.conn.execute(
            "INSERT INTO watchlist (title, oscars_year) VALUES (?, ?)",
            ("Posterless Film", 2026),
        )
        self.conn.commit()

        with mock.patch.object(server, "wiki_poster") as wiki_poster:
            synced = server.sync_watchlist_to_film_library(self.conn)

        self.assertEqual(synced, 1)
        wiki_poster.assert_not_called()
        row = self.conn.execute(
            "SELECT title, poster_url FROM film_library WHERE title = ?",
            ("Posterless Film",),
        ).fetchone()
        self.assertEqual(row["title"], "Posterless Film")
        self.assertIsNone(row["poster_url"])

    def test_wikipedia_rate_limit_uses_retry_after(self):
        rate_limit = urllib.error.HTTPError(
            "https://example.test/wiki",
            429,
            "Too Many Requests",
            {"Retry-After": "0.5"},
            None,
        )
        with (
            mock.patch.object(server, "http_get_json", side_effect=[rate_limit, {"ok": True}]) as request,
            mock.patch.object(server.time, "sleep") as sleep,
        ):
            result = server.wiki_get_json("https://example.test/wiki")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.5)


class FilmLibraryPaginationTests(unittest.TestCase):
    def test_pagination_is_bounded_and_reports_the_total(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "films.sqlite"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            server.ensure_films_tables(conn)
            for index in range(5):
                server.upsert_film_library_row(
                    conn,
                    {"canonical_key": f"film:{index}", "title": f"Film {index}"},
                    fetch_missing_poster=False,
                )
            conn.close()

            with (
                mock.patch.object(server, "DB_PATH", db_path),
                mock.patch.object(server, "hydrate_library_posters", side_effect=lambda rows: [dict(row) for row in rows]),
            ):
                first = server.fetch_film_library(limit=2, offset=0)
                last = server.fetch_film_library(limit=2, offset=4)

        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["pagination"]["total"], 5)
        self.assertTrue(first["pagination"]["has_more"])
        self.assertEqual(len(last["items"]), 1)
        self.assertFalse(last["pagination"]["has_more"])

    def test_invalid_pagination_is_rejected_and_large_pages_are_capped(self):
        self.assertEqual(
            server.normalize_film_library_pagination(1000, 0),
            (server.FILM_LIBRARY_MAX_LIMIT, 0),
        )
        for limit, offset in ((0, 0), (10, -1), ("bad", 0)):
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                server.normalize_film_library_pagination(limit, offset)


class WeightDashboardSummaryTests(unittest.TestCase):
    def test_period_views_reuse_event_payloads_without_history_reads(self):
        with (
            mock.patch.object(server, "read_weight_events", return_value={"events": [1]}) as weight_events,
            mock.patch.object(server, "read_steps_events", return_value={"events": [2]}) as steps_events,
            mock.patch.object(server, "read_weight_history") as weight_history,
            mock.patch.object(server, "read_steps_history") as steps_history,
            mock.patch.object(server, "read_scale_signal", return_value={"ok": True}),
            mock.patch.object(server, "read_weight_stats", return_value={"ok": True}),
            mock.patch.object(server, "read_health_latest", return_value={"ok": True, "snapshot": None}),
        ):
            payload = server.read_weight_dashboard_summary(weight_period=True, steps_all=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["weight_events"], {"events": [1]})
        self.assertEqual(payload["steps_events"], {"events": [2]})
        self.assertIsNone(payload["weight_history"])
        self.assertIsNone(payload["steps_history"])
        weight_events.assert_called_once_with()
        steps_events.assert_called_once_with()
        weight_history.assert_not_called()
        steps_history.assert_not_called()


class StepsSourceAggregationTests(unittest.TestCase):
    def test_virtual_walk_steps_are_idempotent_and_preserve_normal_steps(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
        ):
            server.upsert_steps_event({"day": "2026-08-23", "steps": 4000, "source": "manual"})
            server.upsert_steps_event({
                "day": "2026-08-23", "steps": 2100, "source": "virtual_walk",
                "session_id": "walk-1", "duration_seconds": 1200,
            })
            server.upsert_steps_event({
                "day": "2026-08-23", "steps": 2205, "source": "virtual_walk",
                "session_id": "walk-1", "duration_seconds": 1260,
            })
            result = server.upsert_steps_event({
                "day": "2026-08-23", "steps": 1050, "source": "virtual_walk",
                "session_id": "walk-2", "duration_seconds": 600,
            })

            self.assertEqual(result["event"]["normal_steps"], 4000)
            self.assertEqual(result["event"]["virtual_steps"], 3255)
            self.assertEqual(result["event"]["steps"], 7255)
            self.assertEqual(len(result["event"]["virtual_walk_sessions"]), 2)

            with mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=[]):
                automatic = server.upsert_steps_event({"day": "2026-08-23", "steps": 5000, "source": "health_connect"})
            self.assertEqual(automatic["event"]["steps"], 7255)
            self.assertEqual(automatic["event"]["manual_steps"], 4000)
            self.assertEqual(automatic["event"]["automatic_steps"], 5000)
            self.assertEqual(automatic["event"]["normal_mode"], "manual")

            deleted = server.delete_steps_event({"day": "2026-08-23"})
            self.assertEqual(deleted["deleted"], 1)
            restored_automatic = server.read_steps_events()["events"][0]
            self.assertEqual(restored_automatic["normal_mode"], "automatic")
            self.assertEqual(restored_automatic["automatic_steps"], 5000)
            self.assertEqual(restored_automatic["virtual_steps"], 3255)
            self.assertEqual(restored_automatic["steps"], 8255)

    def test_deleting_manual_steps_keeps_virtual_walk_source(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
        ):
            server.upsert_steps_event({"day": "2026-08-23", "steps": 4000, "source": "manual"})
            server.upsert_steps_event({
                "day": "2026-08-23", "steps": 1050, "source": "virtual_walk",
                "session_id": "walk-1", "duration_seconds": 600,
            })
            server.delete_steps_event({"day": "2026-08-23"})
            event = server.read_steps_events()["events"][0]

            self.assertEqual(event["normal_steps"], 0)
            self.assertEqual(event["virtual_steps"], 1050)
            self.assertEqual(event["steps"], 1050)

    def test_deleting_virtual_walk_removes_only_that_sessions_steps(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
            mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=[]),
        ):
            server.upsert_steps_event({"day": "2026-08-23", "steps": 4000, "source": "phone"})
            server.upsert_steps_event({
                "day": "2026-08-23", "steps": 1050, "source": "virtual_walk",
                "session_id": "walk-1", "duration_seconds": 600,
            })
            server.upsert_steps_event({
                "day": "2026-08-23", "steps": 525, "source": "virtual_walk",
                "session_id": "walk-2", "duration_seconds": 300,
            })

            removed = server.remove_virtual_walk_steps("walk-1")
            event = server.read_steps_events()["events"][0]

            self.assertEqual(removed, 1050)
            self.assertEqual(event["normal_steps"], 4000)
            self.assertEqual(event["virtual_steps"], 525)
            self.assertEqual(event["steps"], 4525)

    def test_automatic_steps_are_a_third_source_and_do_not_delete_virtual_history(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
            mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=[]),
        ):
            server.upsert_steps_event({
                "day": "2026-08-24", "steps": 1200, "source": "virtual_walk",
                "session_id": "walk-automatic-test", "duration_seconds": 600,
            })
            result = server.upsert_steps_event({
                "day": "2026-08-24", "steps": 4300, "source": "health_connect",
            })

            event = result["event"]
            self.assertEqual(event["manual_steps"], 0)
            self.assertEqual(event["automatic_steps"], 4300)
            self.assertEqual(event["virtual_steps"], 1200)
            self.assertEqual(event["steps"], 5500)
            self.assertEqual([source["key"] for source in event["sources"]], ["manual", "automatic", "virtual_walk"])

    def test_automatic_update_is_ignored_while_dashboard_workout_is_active(self):
        zone = server.ZoneInfo("Europe/Warsaw")
        started_at = int(server.datetime(2026, 8, 26, 12, 0, tzinfo=zone).timestamp() * 1000)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
            mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=[{
                "id": "active-walk", "started_by": "dashboard", "started_at": started_at,
                "status": "running", "workout_type": "strength",
            }]),
        ):
            result = server.upsert_steps_event({
                "day": "2026-08-26", "steps": 7000, "source": "health_connect",
            })

            self.assertTrue(result["ignored"])
            self.assertEqual(result["reason"], "live_workout_active")
            self.assertFalse((Path(temp_dir) / "steps.json").exists())

    def test_completed_workout_requires_automatic_steps_filtered_by_its_interval(self):
        zone = server.ZoneInfo("Europe/Warsaw")
        started_at = int(server.datetime(2026, 8, 26, 12, 0, tzinfo=zone).timestamp() * 1000)
        ended_at = started_at + 20 * 60 * 1000
        workout = {
            "id": "finished-strength", "started_by": "dashboard", "started_at": started_at,
            "ended_at": ended_at, "status": "finished", "workout_type": "strength",
        }
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(server, "STEPS_JSON", Path(temp_dir) / "steps.json"),
            mock.patch.object(server, "broadcast_step_update"),
            mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=[workout]),
        ):
            legacy = server.upsert_steps_event({
                "day": "2026-08-26", "steps": 2252, "source": "health_connect",
            })

            self.assertTrue(legacy["ignored"])
            self.assertEqual(legacy["reason"], "workout_exclusions_required")
            self.assertFalse((Path(temp_dir) / "steps.json").exists())

            filtered = server.upsert_steps_event({
                "day": "2026-08-26",
                "steps": 180,
                "raw_steps": 2252,
                "excluded_steps": 2072,
                "excluded_intervals": [{
                    "start": started_at,
                    "end": ended_at,
                    "session_id": "finished-strength",
                    "status": "finished",
                    "workout_type": "strength",
                }],
                "source": "health_connect",
            })

            self.assertNotIn("ignored", filtered)
            self.assertEqual(filtered["event"]["automatic_steps"], 180)
            self.assertEqual(filtered["event"]["automatic_raw_steps"], 2252)
            self.assertEqual(filtered["event"]["automatic_excluded_steps"], 2072)


class ApiOriginSecurityTests(unittest.TestCase):
    def make_handler(self, origin, client="127.0.0.1"):
        handler = object.__new__(server.Handler)
        handler.headers = {"Origin": origin}
        handler.client_address = (client, 12345)
        handler._cors_origin = None
        handler.send_json = mock.Mock()
        return handler

    def test_private_network_origin_is_not_implicitly_trusted(self):
        handler = self.make_handler("http://192.168.1.55:5173")
        with mock.patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("DASHBOARD_ALLOWED_ORIGINS", None)
            allowed = handler.authorize_api_request("/api/films/library", require_origin=True)

        self.assertFalse(allowed)
        handler.send_json.assert_called_once_with({"error": "Origin not allowed"}, status=403)

    def test_private_network_origin_can_be_explicitly_allowlisted(self):
        origin = "http://192.168.1.55:5173"
        handler = self.make_handler(origin, client="192.168.1.55")
        with mock.patch.dict(server.os.environ, {"DASHBOARD_ALLOWED_ORIGINS": origin}):
            allowed = handler.authorize_api_request("/api/films/library", require_origin=True)

        self.assertTrue(allowed)
        self.assertEqual(handler._cors_origin, origin)
        handler.send_json.assert_not_called()

    def test_origins_are_canonicalized_before_allowlist_comparison(self):
        self.assertEqual(server.normalize_origin("HTTP://LOCALHOST:80/"), "http://localhost")
        self.assertEqual(server.normalize_origin("javascript://localhost"), "")


class JournalHtrUploadErrorTests(unittest.TestCase):
    def make_handler(self, content_length="1"):
        handler = object.__new__(server.Handler)
        handler.path = "/api/journal-htr/upload"
        handler.headers = {"Content-Length": content_length, "Content-Type": "application/octet-stream"}
        handler.rfile = BytesIO(b"x")
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()
        return handler

    def test_upload_value_error_is_not_misreported_as_invalid_content_length(self):
        handler = self.make_handler()
        with (
            mock.patch.object(server.JOURNAL_HTR, "upload", side_effect=ValueError("processing failed")),
            mock.patch.object(server, "log_line"),
        ):
            handler.do_POST()

        handler.send_json.assert_called_once_with({"error": "Could not save HTR upload"}, status=500)

    def test_invalid_content_length_still_returns_411(self):
        handler = self.make_handler("not-a-number")
        handler.do_POST()

        handler.send_json.assert_called_once_with(
            {"error": "Valid Content-Length is required", "code": "invalid_content_length"},
            status=411,
        )


class HttpConsoleLogTests(unittest.TestCase):
    def test_compact_mode_hides_successful_reads_but_keeps_writes_and_errors(self):
        with mock.patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("DASHBOARD_HTTP_LOG", None)
            self.assertFalse(server.show_http_log_in_console(200, "GET"))
            self.assertTrue(server.show_http_log_in_console(200, "POST"))
            self.assertFalse(server.show_http_log_in_console(202, "POST", "/api/live-workout/telemetry"))
            self.assertFalse(server.show_http_log_in_console(400, "POST", "/api/live-workout/telemetry"))
            self.assertTrue(server.show_http_log_in_console(404, "GET"))

    def test_all_mode_restores_successful_read_logs(self):
        with mock.patch.dict(server.os.environ, {"DASHBOARD_HTTP_LOG": "all"}):
            self.assertTrue(server.show_http_log_in_console(200, "GET"))


class ClientDisconnectTests(unittest.TestCase):
    def make_handler(self):
        handler = object.__new__(server.Handler)
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.wfile = mock.Mock()
        handler.close_connection = False
        return handler

    def test_send_json_silently_ends_an_aborted_browser_request(self):
        handler = self.make_handler()
        handler.wfile.write.side_effect = ConnectionAbortedError(10053, "aborted")

        sent = handler.send_json({"ok": True})

        self.assertFalse(sent)
        self.assertTrue(handler.close_connection)

    def test_send_bytes_silently_ends_a_reset_browser_request(self):
        handler = self.make_handler()
        handler.end_headers.side_effect = ConnectionResetError(10054, "reset")

        sent = handler.send_bytes(b"image", "image/png")

        self.assertFalse(sent)
        self.assertTrue(handler.close_connection)

    def test_send_json_keeps_real_server_errors_visible(self):
        handler = self.make_handler()
        handler.wfile.write.side_effect = OSError(5, "real write failure")

        with self.assertRaises(OSError):
            handler.send_json({"ok": True})

    def test_server_suppresses_only_disconnect_tracebacks(self):
        httpd = object.__new__(server.DashboardHTTPServer)
        disconnect = ConnectionAbortedError(10053, "aborted")
        with (
            mock.patch.object(server.sys, "exc_info", return_value=(ConnectionAbortedError, disconnect, None)),
            mock.patch.object(ThreadingHTTPServer, "handle_error") as parent_error,
        ):
            httpd.handle_error(None, ("127.0.0.1", 12345))
        parent_error.assert_not_called()

        real_error = RuntimeError("real failure")
        with (
            mock.patch.object(server.sys, "exc_info", return_value=(RuntimeError, real_error, None)),
            mock.patch.object(ThreadingHTTPServer, "handle_error") as parent_error,
        ):
            httpd.handle_error(None, ("127.0.0.1", 12345))
        parent_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
