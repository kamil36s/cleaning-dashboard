from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from language_learning.errors import LanguageError
from language_learning.grammar import GrammarService, semantic_key
from language_learning.grammar_nb import CATALOGUE, detect
from language_learning.grammar_parser import GrammarParser, map_canonical
from language_learning.jobs import LanguageJobManager
from language_learning.migrations import MIGRATIONS
from language_learning.service import LanguageService
from language_learning.store import LanguageStore, canonical_json
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for, wait_for_job

FIXTURE = Path(__file__).parent / 'fixtures/language/nb/grammar_parses.json'


class FixtureParser:
    def __init__(self):
        self.cases = {c['text']: c['parse'] for c in json.loads(FIXTURE.read_text(encoding='utf-8'))}
        self.error = None
        self.transform = lambda x: x
    def health(self):
        return {'state': 'AVAILABLE', 'loadVerified': True, 'provenance': {'fixture': 'stanza-1.14.0'}}
    def parse(self, text):
        if self.error:
            raise self.error
        return self.transform(deepcopy(self.cases[text]))


class GrammarDetectorTests(unittest.TestCase):
    def test_every_candidate_has_explicit_status_and_supported_positive_hard_negatives(self):
        expected = '''A1_BASIC_MAIN_CLAUSE_ORDER A1_YES_NO_QUESTION A1_WH_QUESTION A1_NOUN_DEFINITENESS A1_NOUN_NUMBER A1_PRESENT_TENSE A1_SIMPLE_PAST A1_BASIC_POSSESSIVE A1_BASIC_ADJECTIVE_AGREEMENT A2_V2_FRONTED_ELEMENT A2_BASIC_SUBORDINATE_CLAUSE A2_SUBORDINATE_NEGATION A2_PRESENT_PERFECT A2_MODAL_CONSTRUCTION A2_COMPARISON A2_ADJECTIVE_DEFINITENESS_AGREEMENT B1_VARIED_SUBORDINATE_CLAUSE B1_RELATIVE_CLAUSE B1_CONDITIONAL B1_PASSIVE B1_COMPLEX_WORD_ORDER'''.split()
        self.assertEqual({p['patternId'] for p in CATALOGUE}, set(expected))
        cases = json.loads(FIXTURE.read_text(encoding='utf-8'))
        positive = Counter(p for c in cases for p in c['yes'])
        negative = Counter(p for c in cases for p in c['no'])
        for pattern in CATALOGUE:
            self.assertIn(pattern['status'], {'SUPPORTED','EXPERIMENTAL','DEFERRED'})
            if pattern['status'] == 'SUPPORTED':
                self.assertGreaterEqual(positive[pattern['patternId']], 2)
                self.assertGreaterEqual(negative[pattern['patternId']], 2)
        for case in cases:
            with self.subTest(text=case['text']):
                matches = {m['patternId'] for s in case['parse']['sentences'] for m in detect(s)}
                self.assertTrue(set(case['yes']) <= matches)
                self.assertFalse(set(case['no']) & matches)

    def test_ambiguous_morphology_and_broken_auxiliary_structure_are_not_matches(self):
        parser = FixtureParser()
        sentence = parser.parse('en bil')['sentences'][0]
        noun = next(t for t in sentence['tokens'] if t['pos'] == 'NOUN')
        noun['morphology'] = {'Definite': 'Def,Ind', 'Number': 'Sing,Plur'}
        self.assertEqual(detect(sentence), [])
        sentence = parser.parse('Jeg har jobbet.')['sentences'][0]
        sentence['tokens'][1]['head'] = 1
        self.assertNotIn('A2_PRESENT_PERFECT', [m['patternId'] for m in detect(sentence)])

    def test_mapping_unicode_offsets_punctuation_and_divergence(self):
        parser = FixtureParser()
        parsed = parser.parse('Ærlige Øyvind kjøper øl på Ås.')
        sentence = parsed['sentences'][0]
        snapshot = {'document': {'raw_text': 'Ærlige Øyvind kjøper øl på Ås.'},
                    'sentences': [{'id':'s', 'source_start':sentence['start'], 'source_end':sentence['end'], 'exact_text':'Ærlige Øyvind kjøper øl på Ås.'}],
                    'tokens':[{'id':str(i),'sentence_id':'s','token_order':i,'source_start':t['start'],'source_end':t['end'],'surface':t['surface']} for i,t in enumerate(sentence['tokens'])]}
        before = deepcopy(snapshot)
        self.assertEqual(len(map_canonical(parsed, snapshot)[0]['tokens']), len(snapshot['tokens']))
        self.assertEqual(snapshot, before)
        for field, value in [('start', 1),('surface','o'),('index',99),('head',99)]:
            changed = deepcopy(parsed); changed['sentences'][0]['tokens'][0][field] = value
            with self.assertRaisesRegex(LanguageError,'mapping diverged'):
                map_canonical(changed,snapshot)

    def test_missing_model_no_download_and_failed_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            parser = GrammarParser(model_dir=temp)
            self.assertEqual(parser.health()['reason'],'MODEL_NOT_PROVISIONED')
            with patch('socket.socket.connect',side_effect=AssertionError('network')):
                with self.assertRaises(LanguageError): parser.parse('Jeg jobber.')
        parser = GrammarParser(pipeline_factory=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('private path')))
        with patch.object(parser,'resources',return_value=(Path('.'),{})):
            with self.assertRaises(LanguageError) as caught: parser.parse('Jeg jobber.')
            self.assertEqual(caught.exception.code,'PARSER_INITIALIZATION_FAILED')
            self.assertEqual(parser.health()['state'],'UNAVAILABLE')
            self.assertNotIn('private path',str(caught.exception))

    def test_pipeline_always_none_and_is_reused(self):
        from types import SimpleNamespace
        calls = []
        def factory(**kwargs):
            calls.append(kwargs)
            return lambda text: SimpleNamespace(sentences=[])
        parser = GrammarParser(pipeline_factory=factory)
        with patch.object(parser,'resources',return_value=(Path('.'),{})), patch('socket.socket.connect',side_effect=AssertionError('network')):
            parser.parse('one'); parser.parse('two')
        from stanza.pipeline.core import DownloadMethod
        self.assertEqual(calls[0]['download_method'],DownloadMethod.NONE)
        self.assertEqual(len(calls),1)


class GrammarServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name)/'language.sqlite')
        self.parser = FixtureParser()
        self.service = LanguageService(self.store, analyzer_registry=registry_for(FakeAnalyzer()), frequency_provider=FakeFrequencyProvider(), grammar_parser=self.parser)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()['profile']['id']
        self.manager = LanguageJobManager(self.service,poll_interval=.01)
    def tearDown(self):
        self.manager.stop(); self.temp.cleanup()
    def text(self, raw='Jeg jobber i Oslo.', source='PASTED'):
        text = self.service.create_text_draft({'languageProfileId':self.profile,'title':'Synthetic grammar','rawText':raw,'sourceType':source})['data']['text']
        job = self.service.enqueue_analysis(text['id'],{})['data']['job']
        self.assertEqual(wait_for_job(self.service,job['id'])['state'],'COMPLETED')
        return text
    def mine(self, text):
        job = self.service.enqueue_grammar(text['id'],{'languageProfileId':self.profile})['data']['job']
        return wait_for_job(self.service,job['id'])
    def detail(self, pattern='A1_PRESENT_TENSE'):
        return self.service.grammar_summary(self.profile,pattern)['data']
    def invariant(self):
        with self.store.connection() as c:
            return {table:[tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in self.store.EXPORT_TABLES if not table.startswith('grammar_') and table != 'language_jobs'}

    def test_job_discovered_review_reload_and_no_other_mutation(self):
        text = self.text(); before = self.invariant()
        job = self.mine(text); self.assertEqual(job['state'],'COMPLETED',job)
        detail = self.detail(); example = detail['examples'][0]
        self.assertEqual(detail['pattern']['state'],'DISCOVERED')
        self.assertEqual(example['sourceProvenance']['kind'],'READER')
        self.assertTrue(example['evidence']['FINITE_VERB']['tokenId'])
        self.assertTrue(example['parserProvenance']['resources'])
        self.assertEqual(self.mine(text)['id'],job['id'])
        for decision in ['CONFIRMED','REJECTED','UNREVIEWED']:
            self.service.review_grammar(example['id'],{'languageProfileId':self.profile,'decision':decision})
            reloaded = GrammarService(self.service,self.parser).summary(self.profile,'A1_PRESENT_TENSE')
            self.assertEqual(reloaded['examples'][0]['reviewState'],decision)
            self.assertEqual(reloaded['pattern']['state'],'NOT_DISCOVERED' if decision=='REJECTED' else 'DISCOVERED')
        self.assertEqual(self.invariant(),before)

    def test_exact_sentence_study_required_and_other_text_does_not_count(self):
        text = self.text(); other = self.text('Hun leser.'); self.mine(text)
        session = self.service.start_reader_session({'languageProfileId':self.profile,'textDocumentId':other['id'],'clientSessionId':'other'})['data']['session']
        self._study(other,session)
        self.assertEqual(self.detail()['pattern']['state'],'DISCOVERED')
        self.service.get_text(text['id']); self.detail()
        self.assertEqual(self.detail()['pattern']['state'],'DISCOVERED')
        session = self.service.start_reader_session({'languageProfileId':self.profile,'textDocumentId':text['id'],'clientSessionId':'exact'})['data']['session']
        self._study(text,session)
        self.assertEqual(self.detail()['pattern']['state'],'ENCOUNTERED')
    def _study(self,text,session):
        snapshot=self.store.get_text(text['id']); sentence=snapshot['sentences'][0]
        counts=Counter(t['selected_lemma_id'] for t in snapshot['tokens'] if t['selected_lemma_id'])
        self.service.record_reader_exposure_batch(session['id'],{'textDocumentId':text['id'],'sentenceId':sentence['id'],'idempotencyKey':session['id']+':sentence','occurrences':[{'lemmaId':k,'occurrenceCount':v} for k,v in counts.items()]})

    def test_failure_and_divergence_leave_reader_and_occurrences_untouched(self):
        text = self.text()
        for code in ['MODEL_NOT_PROVISIONED','PARSER_INITIALIZATION_FAILED','TOKEN_MAPPING_DIVERGED']:
            before=self.invariant()
            self.parser.error=LanguageError('Grammar unavailable',code=code)
            job=self.mine(text)
            self.assertEqual(job['errorCode'],code)
            self.assertEqual(self.store.get_text(text['id'])['document']['processing_state'],'ANALYZED')
            self.assertEqual(self.invariant(),before)
            self.assertEqual(self.detail()['examples'],[])
        self.parser.error=None
        def diverge(parsed):
            parsed['sentences'][0]['tokens'][0]['start']+=1
            return parsed
        self.parser.transform=diverge
        self.assertEqual(self.mine(text)['errorCode'],'TOKEN_MAPPING_DIVERGED')

    def test_compatible_upgrade_preserves_review_but_changed_structure_does_not(self):
        text=self.text(); self.mine(text); example=self.detail()['examples'][0]
        self.service.review_grammar(example['id'],{'languageProfileId':self.profile,'decision':'CONFIRMED'})
        upgraded=tuple({**p,'detectorVersion':'1.0.1'} for p in CATALOGUE)
        with patch('language_learning.grammar.registry',return_value=(upgraded,detect)):
            self.assertEqual(self.mine(text)['state'],'COMPLETED')
            self.assertEqual(self.detail()['examples'][0]['reviewState'],'CONFIRMED')
        upgraded=tuple({**p,'patternVersion':'2.0.0'} for p in CATALOGUE)
        with patch('language_learning.grammar.registry',return_value=(upgraded,detect)):
            self.assertEqual(self.mine(text)['state'],'COMPLETED')
            self.assertEqual(self.detail()['examples'][0]['reviewState'],'UNREVIEWED')
        pattern=CATALOGUE[5]; role={'FINITE_VERB':{'tokenId':'1','start':1,'end':2,'relation':'root'}}
        key=semantic_key('s',pattern,role)
        role['FINITE_VERB']['relation']='conj'
        self.assertNotEqual(key,semantic_key('s',pattern,role))

    def test_experimental_cannot_be_authoritative_even_if_confirmed(self):
        experimental=tuple({**p,'status':'EXPERIMENTAL'} if p['patternId']=='A1_PRESENT_TENSE' else p for p in CATALOGUE)
        text=self.text()
        with patch('language_learning.grammar.registry',return_value=(experimental,detect)):
            self.mine(text); example=self.detail()['examples'][0]
            self.service.review_grammar(example['id'],{'languageProfileId':self.profile,'decision':'CONFIRMED'})
            self.assertEqual(self.detail()['pattern']['state'],'NOT_DISCOVERED')

    def test_cross_profile_invalid_ids_and_client_detector_truth_rejected(self):
        text=self.text(); self.mine(text)
        other=self.service.create_profile({'languageCode':'nb','locale':'nb','displayName':'Other'})['data']['profile']['id']
        with self.assertRaises(LanguageError): self.service.text_grammar(text['id'],other)
        with self.assertRaises(LanguageError): self.service.review_grammar(self.detail()['examples'][0]['id'],{'languageProfileId':other,'decision':'CONFIRMED'})
        with self.assertRaises(LanguageError): self.service.enqueue_grammar(text['id'],{'languageProfileId':self.profile,'pattern':'V2'})
        with self.assertRaises(LanguageError): self.service.grammar_summary(self.profile,'UNKNOWN')
        with self.assertRaises(LanguageError): self.service.text_grammar('invalid',self.profile)

    def test_restart_recovery_and_cancellation_use_existing_queue(self):
        text=self.text(); self.manager.stop()
        with patch.object(self.manager,'start'),patch.object(self.manager,'notify'):
            job=self.service.enqueue_grammar(text['id'],{'languageProfileId':self.profile})['data']['job']
        self.store.claim_next_analysis_job(); self.manager.initialize()
        self.assertEqual(self.store.get_analysis_job(job['id'])['state'],'QUEUED')
        self.service.cancel_analysis_job(job['id'])
        self.assertEqual(self.store.get_analysis_job(job['id'])['state'],'CANCELLED')
        self.assertEqual(self.detail()['examples'],[])

    def test_additive_v14_migration_preserves_rows_and_export(self):
        path=Path(self.temp.name)/'v14.sqlite'
        with sqlite3.connect(path) as c:
            for migration in MIGRATIONS[:-2]: c.executescript(migration.sql)
            c.execute('CREATE TABLE language_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT,checksum TEXT)')
            c.executemany('INSERT INTO language_schema_migrations VALUES(?,?,?)',[(m.version,'before',m.checksum) for m in MIGRATIONS[:-2]])
        store=LanguageStore(path); store.initialize()
        with store.connection() as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM language_schema_migrations').fetchone()[0],16)
        self.assertEqual(store.export_data()['exportVersion'],'language-learning-export/v16')

    def test_queries_are_batched_and_no_parser_runs_on_reads(self):
        text=self.text(); self.mine(text)
        with patch.object(self.parser,'parse',side_effect=AssertionError('unexpected parse')):
            for _ in range(3): self.service.get_text(text['id']); self.detail(); self.service.text_grammar(text['id'],self.profile)
        with self.store.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM grammar_analysis_runs').fetchone()[0],1)
        # Exclude the independent queue poll from this request's query budget.
        self.manager.stop()
        statements=[]; original=self.store._connect
        def traced():
            connection=original();connection.set_trace_callback(statements.append);return connection
        with patch.object(self.store,'_connect',side_effect=traced):
            self.detail()
        self.assertEqual(len([s for s in statements if s.lstrip().startswith(('SELECT','WITH'))]),3)

    def test_listening_qualification_required_for_encountered(self):
        text=self.text(); self.mine(text)
        sentence=self.store.get_text(text['id'])['sentences'][0]['id']
        session=self.service.start_listening_session(text['id'],{'languageProfileId':self.profile,'clientSessionId':'grammar-listen','mode':'READ_LISTEN'})['data']['session']
        payload={'textDocumentId':text['id'],'sentenceId':sentence,'idempotencyKey':'partial','outcome':'ENDED','playbackSource':'BROWSER_TTS','activeMs':100,'durationMs':1000}
        self.service.record_listening_sentence_event(session['id'],payload)
        self.assertEqual(self.detail()['pattern']['state'],'DISCOVERED')
        self.service.record_listening_sentence_event(session['id'],{**payload,'idempotencyKey':'complete','activeMs':1000})
        self.assertEqual(self.detail()['pattern']['state'],'ENCOUNTERED')

    def test_inbox_transcript_and_generated_provenance_and_eligibility(self):
        for source,text in [('PASTED_TEXT','Hun leser.'),('LOCAL_TRANSCRIPT','Jeg jobbet.')]:
            payload={'sourceType':source,'title':'Synthetic source','text':text,'transcriptText':text,'format':'PLAIN'}
            created=self.service.create_content(self.profile,payload)['data']
            detail=self.service.content_detail(created['item']['id'])['data']
            wait_for_job(self.service,detail['latestJob']['id'])
            detail=self.service.content_detail(created['item']['id'])['data']
            self.assertEqual(self.mine(detail['document'])['state'],'COMPLETED')
            grammar=self.service.text_grammar(detail['document']['id'],self.profile)['data']
            self.assertEqual(grammar['examples'][0]['sourceProvenance']['kind'],'AUTHENTIC' if source=='PASTED_TEXT' else 'TRANSCRIPT')
            self.assertEqual(self.service.content_detail(created['item']['id'])['data']['latestJob']['analysisDomain'],'TEXT')
        text=self.text('Jeg har jobbet.',source='GENERATED_GEMINI')
        with self.assertRaises(LanguageError): self.mine(text)
        from types import SimpleNamespace
        from tests.test_language_phase9 import Phase9SharedContextTests
        fixture=SimpleNamespace(store=self.store,profile={'id':self.profile})
        Phase9SharedContextTests.add_generation_candidate(fixture,status='ACCEPTED',document_id=text['id'])
        self.assertEqual(self.mine(text)['state'],'COMPLETED')
        self.assertEqual(self.detail('A2_PRESENT_PERFECT')['examples'][0]['sourceProvenance']['kind'],'GENERATED')

    def test_reanalysis_cannot_delete_grammar_history(self):
        text=self.text(); self.mine(text)
        snapshot=self.store.get_text(text['id'])
        # A new normal analysis fingerprint exercises the commit guard.
        values=self.service._analysis_job_values(text['id'],job_type='ANALYZE',fingerprint_suffix='upgrade')
        job=self.service._enqueue_job(values)['data']['job']
        self.assertEqual(wait_for_job(self.service,job['id'])['errorCode'],'grammar_text_reanalysis_blocked')
        self.assertEqual(self.store.get_text(text['id'])['tokens'],snapshot['tokens'])


if __name__=='__main__': unittest.main()
