import unittest

from synchrobook_backend.alignment import align_sentences, build_alignment, match_chapters


def sentences(*values):
    return [
        {"id": f"s{index + 1}", "text": value, "originalText": value}
        for index, value in enumerate(values)
    ]


def segments(*values):
    output = []
    timestamp = 0.0
    for value in values:
        duration = max(2, len(value.split()))
        output.append({"text": value, "start": timestamp, "end": timestamp + duration})
        timestamp += duration
    return output


class SynchrobookAlignmentTests(unittest.TestCase):
    def test_numeric_audio_tracks_do_not_create_a_false_chapter_map(self):
        matched = match_chapters(
            [{"id": "ch01", "title": "Part0007 Split 001"}, {"id": "ch02", "title": "Why friends matter"}],
            [{"index": 0, "title": "001", "start": 0, "end": 10}, {"index": 1, "title": "002", "start": 10, "end": 20}],
        )
        self.assertTrue(all(row["audioChapterIndex"] is None for row in matched))

    def test_numbered_file_parts_do_not_create_a_false_chapter_map(self):
        matched = match_chapters(
            [{"id": "ch01", "title": "1. A Change in Vocation"}, {"id": "ch02", "title": "2. The Best Tea Monk in Panga"}],
            [
                {"index": 0, "title": "A Psalm for the Wild-Built Monk (1)", "start": 0, "end": 20},
                {"index": 1, "title": "A Psalm for the Wild-Built Monk (2)", "start": 20, "end": 320},
            ],
        )
        self.assertTrue(all(row["audioChapterIndex"] is None for row in matched))

    def test_composite_m4b_titles_map_numbered_epub_chapters(self):
        matched = match_chapters(
            [
                {"id": "title", "title": "Wool"},
                {"id": "part-1", "title": "Part 1: Holston"},
                {"id": "chapter-1", "title": "1"},
                {"id": "chapter-2", "title": "2"},
                {"id": "part-2", "title": "Part 2: Proper Gauge"},
                {"id": "chapter-8", "title": "8"},
            ],
            [
                {"title": "Opening Credits", "start": 0},
                {"title": "Dedication", "start": 10},
                {"title": "Part 1: Holston: Chapter 1", "start": 20},
                {"title": "Part 1: Holston: Chapter 2", "start": 30},
                {"title": "Part 2: Proper Gauge: Chapter 8", "start": 40},
            ],
        )
        self.assertEqual(
            [row["audioChapterIndex"] for row in matched],
            [None, None, 2, 3, None, 4],
        )

    def test_global_alignment_excludes_unspoken_supplementary_sections_from_quality(self):
        book = {"chapters": [
            {"id": "front", "title": "Copyright", "paragraphs": [{"sentences": [{"id": "front-s1", "text": "All rights reserved.", "originalText": "All rights reserved."}]}]},
            {"id": "main", "title": "1 Why friends matter", "paragraphs": [{"sentences": [{"id": "main-s1", "text": "The actual chapter begins here.", "originalText": "The actual chapter begins here."}]}]},
        ]}
        _, report = build_alignment(
            "book", book, {"segments": segments("The actual chapter begins here.")},
            [{"title": "001", "start": 0, "end": 10}],
        )
        self.assertEqual(report["chapters"][0]["quality"], "NOT_IN_AUDIO")
        self.assertEqual(report["summary"]["eligibleSentences"], 1)
        self.assertEqual(report["summary"]["percentageAligned"], 100.0)

    def test_sparse_chapter_titles_fall_back_to_global_alignment(self):
        book = {"chapters": [
            {"id": "axioms", "title": "AXIOMS", "paragraphs": [{"sentences": [{"id": "axioms-s1", "text": "Everything which exists is either in itself or in something else.", "originalText": "Everything which exists is either in itself or in something else."}]}]},
            {"id": "propositions", "title": "PROPOSITIONS", "paragraphs": [{"sentences": [{"id": "propositions-s1", "text": "Substance is by nature prior to its modifications.", "originalText": "Substance is by nature prior to its modifications."}]}]},
            {"id": "appendix", "title": "APPENDIX", "paragraphs": [{"sentences": [{"id": "appendix-s1", "text": "People commonly suppose that all things act for an end.", "originalText": "People commonly suppose that all things act for an end."}]}]},
        ]}
        transcript = {"segments": segments(
            "Everything which exists is either in itself or in something else.",
            "Substance is by nature prior to its modifications.",
            "People commonly suppose that all things act for an end.",
        )}
        audio_chapters = [
            {"title": "01. Concerning God", "start": 0, "end": 10},
            {"title": "02. Propositions 11 to 15", "start": 10, "end": 20},
            {"title": "03. Propositions 16 to 19", "start": 20, "end": 30},
            {"title": "04. Appendix", "start": 30, "end": 40},
            {"title": "05. Another technical split", "start": 40, "end": 50},
            {"title": "06. Final technical split", "start": 50, "end": 60},
        ]
        alignment, report = build_alignment("book", book, transcript, audio_chapters)
        aligned = [
            sentence["start"]
            for chapter in alignment["chapters"]
            for sentence in chapter["sentences"]
        ]
        self.assertTrue(all(value is not None for value in aligned))
        self.assertTrue(all(row["audioChapterIndex"] is None for row in report["chapterMapping"]))

    def test_structural_fragments_do_not_lower_quality_percentage(self):
        book = {"chapters": [{
            "id": "main", "title": "Propositions", "paragraphs": [{"sentences": [
                {"id": "label", "text": "PROP.", "originalText": "PROP."},
                {"id": "number", "text": "III.", "originalText": "III."},
                {"id": "content", "text": "Things which have nothing in common cannot cause one another.", "originalText": "Things which have nothing in common cannot cause one another."},
                {"id": "qed", "text": "Q.E.D.", "originalText": "Q.E.D."},
            ]}]}]}
        _, report = build_alignment(
            "book", book,
            {"segments": segments("Things which have nothing in common cannot cause one another.")},
            [],
        )
        self.assertEqual(report["chapters"][0]["eligibleSentences"], 1)
        self.assertEqual(report["summary"]["percentageAligned"], 100.0)

    def test_short_structural_chapter_is_not_assumed_missing_from_audio(self):
        book = {"chapters": [{
            "id": "part-five", "title": "PART V", "paragraphs": [{"sentences": [{
                "id": "part-five-label", "text": "PART V.", "originalText": "PART V.",
            }]}],
        }]}
        _, report = build_alignment("book", book, {"segments": []}, [])
        self.assertTrue(report["chapters"][0]["inAudiobook"])
        self.assertEqual(report["chapters"][0]["quality"], "PROBLEMATIC")

    def test_project_gutenberg_boilerplate_is_excluded_from_quality(self):
        book = {"chapters": [
            {"id": "boilerplate", "title": "The Book", "paragraphs": [{"sentences": [{
                "id": "boilerplate-s1",
                "text": "The Project Gutenberg eBook may be redistributed under its license.",
                "originalText": "The Project Gutenberg eBook may be redistributed under its license.",
            }]}]},
            {"id": "main", "title": "Chapter One", "paragraphs": [{"sentences": [{
                "id": "main-s1", "text": "The actual chapter begins here.",
                "originalText": "The actual chapter begins here.",
            }]}]},
        ]}
        _, report = build_alignment(
            "book", book, {"segments": segments("The actual chapter begins here.")}, [],
        )
        self.assertEqual(report["chapters"][0]["quality"], "NOT_IN_AUDIO")
        self.assertEqual(report["summary"]["eligibleSentences"], 1)
        self.assertEqual(report["summary"]["percentageAligned"], 100.0)

    def test_weak_long_match_is_rejected(self):
        result = align_sentences(
            sentences("Alpha beta gamma delta epsilon."),
            segments("Alpha beta zeta eta theta."),
        )
        self.assertIsNone(result[0]["start"])

    def test_contraction_matches_expanded_epub_text(self):
        result = align_sentences(sentences("He could not understand."), segments("He couldn't understand."))
        self.assertIsNotNone(result[0]["start"])

    def test_punctuation_differences_match(self):
        result = align_sentences(sentences("Hello, world!"), segments("Hello world."))
        self.assertIsNotNone(result[0]["start"])

    def test_omitted_epub_sentence_does_not_break_surrounding_matches(self):
        result = align_sentences(
            sentences("Alpha begins now.", "This sentence is absent from audio.", "Omega finishes here."),
            segments("Alpha begins now.", "Omega finishes here."),
        )
        self.assertIsNotNone(result[0]["start"])
        self.assertIsNone(result[1]["start"])
        self.assertIsNotNone(result[2]["start"])

    def test_narrator_introduction_is_skipped(self):
        result = align_sentences(
            sentences("The actual story starts here."),
            segments("Welcome to this audiobook, narrated by Jane Doe.", "The actual story starts here."),
        )
        self.assertGreater(result[0]["start"], 0)

    def test_repeated_phrase_remains_monotonic(self):
        result = align_sentences(
            sentences("The bell rang softly.", "A long evening passed between them.", "The bell rang softly."),
            segments("The bell rang softly.", "A long evening passed between them.", "The bell rang softly."),
        )
        starts = [row["start"] for row in result]
        self.assertTrue(all(value is not None for value in starts))
        self.assertEqual(starts, sorted(starts))
        self.assertGreater(starts[2], starts[0])

    def test_epub_only_footnote_can_remain_unaligned(self):
        result = align_sentences(
            sentences("The road turned north.", "Footnote concerning an obscure 1842 edition.", "Snow began to fall."),
            segments("The road turned north.", "Snow began to fall."),
        )
        self.assertIsNone(result[1]["start"])
        self.assertIsNotNone(result[2]["start"])

    def test_extra_m4b_chapter_before_chapter_one_is_allowed(self):
        result = match_chapters(
            [{"id": "ch01", "title": "Chapter One"}, {"id": "ch02", "title": "Chapter Two"}],
            [{"title": "Publisher Introduction", "start": 0}, {"title": "Chapter One", "start": 30}, {"title": "Chapter Two", "start": 90}],
        )
        self.assertEqual([row["audioChapterIndex"] for row in result], [1, 2])

    def test_small_edition_differences_remain_usable(self):
        result = align_sentences(
            sentences("He could not understand what had happened in the old house."),
            segments("He couldn't understand what happened in that old house."),
        )
        self.assertIsNotNone(result[0]["start"])
        self.assertGreater(result[0]["confidence"], 0.6)

    def test_alignment_recovers_after_unmatched_words(self):
        result = align_sentences(
            sentences("First anchor sentence appears here.", "These several consecutive words have no spoken counterpart at all.", "Recovery anchor sentence appears now."),
            segments("First anchor sentence appears here.", "Recovery anchor sentence appears now."),
        )
        self.assertIsNotNone(result[0]["start"])
        self.assertIsNone(result[1]["start"])
        self.assertIsNotNone(result[2]["start"])

    def test_short_generic_sentence_cannot_jump_far_forward(self):
        transcript = segments(*(["unrelated filler words continue here"] * 15), "Goodbye.")
        result = align_sentences(sentences("Goodbye."), transcript)
        self.assertIsNone(result[0]["start"])

    def test_chapter_markers_keep_front_matter_out_of_novel_alignment(self):
        front_sentence = {"id": "front-s1", "text": "A publisher essay not present in audio.", "originalText": "A publisher essay not present in audio."}
        part_sentence = {"id": "part-s1", "text": "The actual novel begins here.", "originalText": "The actual novel begins here."}
        book = {"chapters": [
            {"id": "front", "title": "Introduction", "paragraphs": [{"sentences": [front_sentence]}]},
            {"id": "part", "title": "Part One", "paragraphs": [{"sentences": [part_sentence]}]},
        ]}
        transcript = {"segments": segments("Audible opening credits.", "The actual novel begins here.")}
        audio_chapters = [
            {"title": "Opening Credits", "start": 0, "end": 3},
            {"title": "Part One", "start": 3, "end": 20},
        ]
        alignment, report = build_alignment("book", book, transcript, audio_chapters)
        self.assertIsNone(alignment["chapters"][0]["sentences"][0]["start"])
        self.assertIsNotNone(alignment["chapters"][1]["sentences"][0]["start"])
        self.assertEqual(report["chapters"][0]["quality"], "NOT_IN_AUDIO")
        self.assertEqual(report["summary"]["eligibleSentences"], 1)


if __name__ == "__main__":
    unittest.main()
