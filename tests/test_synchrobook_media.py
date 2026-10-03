import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from synchrobook_backend.media import prepare_analysis_chunks, prepare_audiobook, prepare_playback, probe_m4b


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are required")
class SynchrobookMediaTests(unittest.TestCase):
    def test_assembles_multiple_mp3_files_into_one_chaptered_m4b(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index, frequency in enumerate((330, 550), 1):
                source = root / f"chapter-{index:02d}.mp3"
                subprocess.run([
                    shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=1",
                    "-c:a", "libmp3lame", str(source),
                ], check=True)
                sources.append({"path": source, "title": f"Chapter {index}"})
            destination = root / "source.m4b"
            metadata = prepare_audiobook(sources, destination, root / "assembly")
            self.assertTrue(destination.is_file())
            self.assertGreater(metadata["duration"], 1.8)
            self.assertEqual([row["title"] for row in metadata["chapters"]], ["Chapter 1", "Chapter 2"])
            self.assertAlmostEqual(metadata["chapters"][1]["start"], 1.0, delta=0.15)

    def test_converts_wav_into_m4b(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "chapter.wav"
            subprocess.run([
                shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-c:a", "pcm_s16le", str(source),
            ], check=True)

            destination = root / "source.m4b"
            metadata = prepare_audiobook(
                [{"path": source, "title": "WAV chapter"}],
                destination,
                root / "assembly",
            )

            self.assertTrue(destination.is_file())
            self.assertGreater(metadata["duration"], 0.8)
            self.assertEqual(metadata["chapters"][0]["title"], "WAV chapter")

    def test_probes_m4b_and_prepares_cached_browser_and_analysis_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.m4b"
            subprocess.run([
                shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-metadata", "title=Wisła „w ogniu” — Test", "-c:a", "aac", str(source),
            ], check=True)
            metadata = probe_m4b(source)
            self.assertGreater(metadata["duration"], 1)
            self.assertEqual(metadata["title"], "Wisła „w ogniu” — Test")
            playback = root / "audio" / "playback.m4a"
            prepare_playback(source, playback)
            self.assertTrue(playback.is_file())
            chunks = prepare_analysis_chunks(source, root / "audio" / "analysis", chunk_seconds=1)
            self.assertGreaterEqual(len(chunks), 2)
            self.assertTrue(all(path.stat().st_size > 0 for path in chunks))
            refreshed = prepare_analysis_chunks(source, root / "audio" / "analysis", chunk_seconds=2)
            marker = json.loads((root / "audio" / "analysis" / "complete.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["chunkSeconds"], 2)
            self.assertLess(len(refreshed), len(chunks))


if __name__ == "__main__":
    unittest.main()
