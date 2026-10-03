import concurrent.futures
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from football_service import FootballHub, PROFILE_TTLS, build_snapshot, club_statistics, final_matches, parse_transfers, merge_match_history
from football_store import FootballStore


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FootballStore(Path(self.temp.name) / 'football.sqlite')
        self.clock = [100000.0]
        self.club = {'key': 'liverpool', 'name': 'Liverpool', 'names': ['Liverpool'],
                     'providerIds': {'thesportsdb_team_id': 133602, 'ESPN': '364'}, 'espnLeague': 'eng.1'}
        self.store.put_entity('club', self.club)
        self.snapshot = {'clubs': [self.club], 'competitions': [{'key':'premier-league','name':'Premier League',
            'providerIds': {'espn_league':'eng.1'}, 'country':'England', 'standings':{'rows':[]}}],
            'matches': [], 'following': {'teams': ['liverpool']}}
        self.fetch = Mock(side_effect=self.provider)
        self.hub = FootballHub(self.store,self.fetch,[], 'https://www.thesportsdb.com/api/v1/json/123',clock=lambda:self.clock[0])

    def provider(self, url, **kwargs):
        if 'lookupteam' in url:
            return {'teams':[{'idTeam':'133602','strTeam':'Liverpool','strSport':'Soccer','strStadium':'Anfield','intFormedYear':'1892'}]}
        if '/roster' in url:
            return {'team':{'id':'364'},'season':{'year':2026},'athletes':[
                {'id':'100','displayName':'Example Player','fullName':'Example Player','citizenship':'England',
                 'dateOfBirth':'2000-01-01','position':{'displayName':'Forward'},'jersey':'9'}],
                 'coach':[{'id':'1','firstName':'Old','lastName':'Coach'}]}
        if '/overview' in url:
            return {'statistics':{'displayNames':['Goals'],'splits':[{'displayName':'2026-27 league','stats':['2']}]}}
        if '/teams?' in url:
            return {'sports':[{'leagues':[{'teams':[{'team':{'id':'364','displayName':'Liverpool'}}]}]}]}
        raise AssertionError(url)

    def detail(self, kind='club', key='liverpool', section='overview', year=''):
        return self.hub.detail(kind,key,section,self.snapshot,year)

    def test_club_and_stadium_metadata_keep_unknowns(self):
        value = self.detail()
        self.assertEqual(value['club']['founded'],'1892')
        stadium = self.detail('stadium',value['club']['stadium']['key'])['stadium']
        self.assertEqual(stadium['name'],'Anfield')
        self.assertIsNone(stadium['capacity'])
        self.assertTrue(value['club']['followed'])

    def test_squad_player_navigation_and_statistics(self):
        squad = self.detail(section='squad')
        player = self.detail('player',squad['players'][0]['key'])
        self.assertEqual(player['player']['clubKey'],'liverpool')
        self.assertEqual(player['statistics']['splits'][0]['stats'],['2'])
        self.assertIsNone(player['player']['photo'])
        self.assertEqual(squad['season']['year'],2026)

    def test_historical_espn_coaches_are_not_presented_as_current(self):
        self.detail(section='squad')
        result = self.detail(section='coach')
        self.assertEqual(result['rows'],[])
        self.assertIn('Brak',result['availability'])

    def test_verified_api_coach_appointment(self):
        self.hub.api_key='fixture-key'
        self.club['providerIds']['API-Football']=40
        self.store.put_entity('club',self.club)
        self.fetch.side_effect=lambda *a,**k: {'response':[
            {'id':1,'name':'Former','career':[{'team':{'id':40},'start':'2020-01-01','end':'2021-01-01'}]},
            {'id':2,'name':'Current','career':[{'team':{'id':40},'start':'2026-07-01','end':None}]}]}
        rows=self.detail(section='coach')['rows']
        self.assertEqual([r['name'] for r in rows],['Current'])
        self.assertEqual(rows[0]['appointed'],'2026-07-01')

    def test_transfers_without_credentials_are_explicit(self):
        self.assertIn('Brak',self.detail(section='transfers')['availability'])
        self.fetch.assert_not_called()

    def test_cache_hit_expiry_and_restart(self):
        self.detail(section='squad'); self.detail(section='squad')
        self.assertEqual(self.fetch.call_count,1)
        another=FootballHub(self.store,self.fetch,[],self.hub.sportsdb_base,clock=lambda:self.clock[0])
        another.detail('club','liverpool','squad',self.snapshot)
        self.assertEqual(self.fetch.call_count,1)
        self.clock[0]+=PROFILE_TTLS['squad']+1
        self.detail(section='squad')
        self.assertEqual(self.fetch.call_count,2)

    def test_error_fallback_keeps_original_timestamp(self):
        before=self.detail(section='squad')
        self.clock[0]+=PROFILE_TTLS['squad']+1
        self.fetch.side_effect=TimeoutError()
        after=self.detail(section='squad')
        self.assertTrue(after['stale'])
        self.assertEqual(after['players'],before['players'])
        self.assertEqual(after['cache'][0]['fetchedAt'],before['cache'][0]['fetchedAt'])

    def test_rate_limit_and_negative_cache_eventually_recover(self):
        self.fetch.side_effect=urllib.error.HTTPError('url',429,'limited',{},None)
        result=self.detail(section='squad')
        self.assertEqual(result['sourceErrors'][0]['error'],'rate-limited')
        self.clock[0]+=60
        self.detail(section='squad')
        self.assertEqual(self.fetch.call_count,1)
        self.clock[0]+=61
        self.fetch.side_effect=self.provider
        self.assertEqual(len(self.detail(section='squad')['players']),1)
        self.assertEqual(self.fetch.call_count,2)

    def test_identical_concurrent_lookup_makes_one_provider_call(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda _: self.detail(section='squad'),range(12)))
        self.assertEqual(self.fetch.call_count,1)
        self.assertTrue(all(len(row['players'])==1 for row in rows))

    def test_wrong_provider_identity_never_enters_store(self):
        self.fetch.side_effect=lambda *a,**k: {'team':{'id':'999'},'athletes':[]}
        result=self.detail(section='squad')
        self.assertEqual(result['players'],[])
        self.assertTrue(result['sourceErrors'])
        self.assertEqual(self.store.entities('player'),[])

    def test_wrong_sportsdb_identity_is_rejected(self):
        self.fetch.side_effect=lambda *a,**k: {'teams':[{'idTeam':'999','strSport':'Soccer','strStadium':'Wrong'}]}
        result=self.detail()
        self.assertNotIn('stadium',result['club'])
        self.assertTrue(result['sourceErrors'])

    def test_competition_aggregation_and_provider_mapping(self):
        self.snapshot['matches']=[{'id':'m','competitionKey':'premier-league'}]
        result=self.detail('competition','premier-league')
        self.assertEqual(result['matches'][0]['id'],'m')
        self.assertEqual(result['clubs'][0]['key'],'liverpool')
        self.assertEqual(self.store.entity('club','liverpool')['providerIds']['ESPN'],'364')

    def test_search_reads_local_entities_without_fetching(self):
        squad=self.detail(section='squad'); self.fetch.reset_mock()
        rows=self.hub.search(self.snapshot,'example','player')
        self.assertEqual(rows[0]['key'],squad['players'][0]['key'])
        self.assertEqual(self.hub.search(self.snapshot,'premier')[0]['kind'],'competition')
        self.assertEqual(self.hub.search(self.snapshot,'liverpool')[0]['key'],'liverpool')
        self.fetch.assert_not_called()

    def test_unknown_entity_raises_before_provider_call(self):
        with self.assertRaises(ValueError): self.detail('player','unknown')
        self.fetch.assert_not_called()

    def test_provider_mapping_is_persisted(self):
        player=self.detail(section='squad')['players'][0]
        self.assertTrue(any(m['entity_key']==player['key'] and m['external_id']=='100' for m in self.store.mappings()))

    def test_table_adapter_is_cached_and_preserves_provider_values(self):
        self.hub.standings_fetch=Mock(return_value={'rows':[{'name':'Liverpool','points':'0','played':'0'}]})
        for _ in range(2):
            result=self.detail('competition','premier-league')
            self.assertEqual(result['competition']['standings']['rows'][0]['points'],'0')
        self.hub.standings_fetch.assert_called_once_with('premier-league')

    def test_removed_player_is_not_claimed_as_current_squad_member(self):
        player=self.detail(section='squad')['players'][0]
        self.clock[0]+=PROFILE_TTLS['squad']+1
        self.fetch.side_effect=lambda url,**kwargs: {'team':{'id':'364'},'athletes':[]} if '/roster' in url else {}
        result=self.detail('player',player['key'])
        self.assertFalse(result['inCurrentSquad'])

    def test_api_error_payload_is_not_cached_as_empty_success(self):
        self.hub.api_key='test'
        self.club['providerIds']['API-Football']=40
        self.store.put_entity('club',self.club)
        self.fetch.side_effect=lambda *args,**kwargs: {'errors':{'plan':'restricted'},'response':[]}
        self.assertTrue(self.detail(section='transfers')['sourceErrors'])
        self.assertIsNone(self.store.cached('transfers:40'))


class CalculationTests(unittest.TestCase):
    @staticmethod
    def match(status='FT',score=None,**extra):
        return {'id':'1','status':status,'score':score or {'home':2,'away':1},'clubKeys':['a','b'],
                'playedAt':'2026-09-01T12:00:00',**extra}

    def test_form_excludes_nonfinals_and_duplicate_provider_rows(self):
        rows=[self.match(),self.match(provider='other')]
        rows += [self.match(status=s,playedAt=f'2026-09-{i+2:02d}') for i,s in enumerate(['HT','LIVE','Scheduled','Cancelled','Abandoned','Postponed'])]
        result=club_statistics(rows,'a')
        self.assertEqual(result['statistics']['played'],1)
        self.assertEqual(result['form'][0]['result'],'W')
        self.assertEqual(club_statistics(rows,'b')['form'][0]['result'],'L')

    def test_form_order_limit_and_zero_score(self):
        rows=[self.match(score={'home':0,'away':0},playedAt=f'2026-09-{day:02d}') for day in range(1,15)]
        result=club_statistics(rows,'a')
        self.assertEqual(result['statistics']['draws'],14)
        self.assertEqual(result['statistics']['cleanSheets'],14)
        self.assertEqual(len(result['form']),10)
        self.assertEqual(result['form'][0]['match']['playedAt'],'2026-09-14')

    def test_missing_scores_not_classified(self):
        self.assertEqual(final_matches([self.match(score={'home':None,'away':0})]),[])

    def test_final_match_replaces_historical_upcoming_and_live_ids(self):
        current=[self.match(id='espn:123',provider='espn',category='result')]
        history=[self.match(id='espn-next:liverpool:123',provider='espn',category='upcoming'),
                 self.match(id='espn-live:123',provider='espn',category='live')]
        self.assertEqual(merge_match_history(current,history),current)

    def test_football_view_excludes_hockey_without_mutating_preferences(self):
        settings={'sports':{'enabledTeamKeys':['montreal-canadiens']}}
        catalog=[{'key':'montreal-canadiens','name':'Montreal Canadiens','espn_sport':'hockey','thesportsdb_team_id':1}]
        result=build_snapshot({'matches':[{'id':'h','teamKey':'montreal-canadiens'}]},settings,catalog,{}, {})
        self.assertEqual(result['clubs'],[])
        self.assertEqual(result['matches'],[])
        self.assertEqual(settings['sports']['enabledTeamKeys'],['montreal-canadiens'])

    def test_transfers_in_out_year_and_missing_fee(self):
        rows=[{'player':{'id':1,'name':'One'},'transfers':[
            {'date':'2026-07-01','teams':{'in':{'id':40,'name':'A'},'out':{'id':50,'name':'B'}}},
            {'date':'2025-07-01','type':'Loan','teams':{'out':{'id':40,'name':'A'},'in':{'id':50,'name':'B'}}}]}]
        self.assertEqual([r['direction'] for r in parse_transfers(rows,40)],['IN','OUT'])
        selected=parse_transfers(rows,40,'2026')
        self.assertEqual(len(selected),1)
        self.assertIsNone(selected[0]['type'])
        self.assertEqual(parse_transfers(rows,999),[])
        self.assertEqual(len(parse_transfers(rows,40,'2026-2027')),1)

    def test_shared_table_publish_does_not_change_favourites_or_other_tables(self):
        import server
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'KITCHEN_SCORES_JSON',Path(directory)/'scores.json'), \
                patch.object(server,'read_kitchen_settings',return_value={'sports':{'enabledLeagueKeys':['nhl']}}), \
                patch.object(server,'fetch_kitchen_standings',return_value={'premier-league':{'rows':[{'name':'Liverpool','points':'1'}]}}):
            server.rewrite_json_file(server.KITCHEN_SCORES_JSON,{'standings':{'nhl':{'rows':[1]}},'updatedAt':'old'})
            table=server.read_football_competition_table('premier-league')
            saved=server.read_json_file(server.KITCHEN_SCORES_JSON,{})
            self.assertEqual(saved['standings']['nhl'],{'rows':[1]})
            self.assertEqual(saved['standings']['premier-league'],table)
            self.assertEqual(saved['updatedAt'],'old')

    def test_tablet_and_desktop_publish_identical_live_snapshot(self):
        import server
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'KITCHEN_SCORES_JSON',Path(directory)/'scores.json'), \
                patch.object(server,'_read_kitchen_scores',return_value={'matches':[], 'updatedAt':'2026-01-01','liveMatches':[self.match(status='HT')]}):
            tablet=server.read_kitchen_scores()
            stored=server.read_json_file(server.KITCHEN_SCORES_JSON,{})
        self.assertEqual(tablet,stored)
        self.assertEqual(stored['updatedAt'],'2026-01-01')
        self.assertTrue(stored['liveUpdatedAt'])

    def test_live_failure_preserves_previous_snapshot_age(self):
        import server
        previous={'liveUpdatedAt':'2026-01-01','liveMatches':[self.match(status='HT')]}
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'KITCHEN_SCORES_JSON',Path(directory)/'scores.json'), \
                patch.object(server,'_read_kitchen_scores',return_value={'liveError':'timeout','liveMatches':[]}):
            server.rewrite_json_file(server.KITCHEN_SCORES_JSON,previous)
            result=server.read_kitchen_scores()
        self.assertEqual(result['liveUpdatedAt'],previous['liveUpdatedAt'])
        self.assertEqual(result['liveMatches'],previous['liveMatches'])

if __name__ == '__main__': unittest.main()
