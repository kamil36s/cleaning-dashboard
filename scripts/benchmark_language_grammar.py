"""Explicit offline developer audit; synthetic data only; no model downloader."""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from language_learning.grammar_parser import GrammarParser
from language_learning.analysis.norwegian_bokmal import NorwegianBokmalStanzaAnalyzer
from language_learning.grammar_nb import detect


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--capture-fixtures', action='store_true')
    options = args.parse_args()
    parser = GrammarParser()
    print(json.dumps(parser.health(), ensure_ascii=True))
    from scripts.benchmark_language_analyzers import rss_bytes
    memory = rss_bytes() or 0
    base = 'Jeg jobber i Oslo. Hun har lest boken. Bilen som kommer, er stor. '
    def timed(call):
        start = time.perf_counter(); value = call()
        return value, round((time.perf_counter()-start)*1000, 3)
    with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
        parsed, cold = timed(lambda: parser.parse(''))
        _, warm_init = timed(lambda: parser.parse(''))
        print(json.dumps({'grammarColdInitMs': cold, 'grammarWarmInitMs': warm_init, 'rssDeltaMiB': round(((rss_bytes() or 0)-memory)/1048576, 2)}))
        normal = NorwegianBokmalStanzaAnalyzer()
        _, normal_cold = timed(lambda: normal.analyze('Jeg jobber.', language_code='nb'))
        print(json.dumps({'readerColdInitAndSmallMs': normal_cold}))
        for label, text in [('small',base),('200words',base*15),('large',base*150)]:
            parsed, grammar_ms = timed(lambda: parser.parse(text))
            _, reader_ms = timed(lambda: normal.analyze(text,language_code='nb'))
            _, detector_ms = timed(lambda: [detect(s) for s in parsed['sentences']])
            print(json.dumps({'sample':label,'words':len(text.split()),'grammarMs':grammar_ms,'readerMs':reader_ms,'detectorMs':detector_ms}))
        if options.capture_fixtures:
            path = Path('tests/fixtures/language/nb/grammar_cases.json')
            cases = json.loads(path.read_text(encoding='utf-8'))
            for case in cases:
                case['parse'] = parser.parse(case['text'])
                matches = {m['patternId'] for s in case['parse']['sentences'] for m in detect(s)}
                assert set(case['yes']) <= matches, (case['text'],set(case['yes'])-matches)
                assert not set(case['no']) & matches, (case['text'],set(case['no']) & matches)
            Path('tests/fixtures/language/nb/grammar_parses.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('Captured and checked',len(cases),'real offline parser fixtures')

if __name__ == '__main__':
    main()
