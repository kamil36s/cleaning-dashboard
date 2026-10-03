"""Real Edge + production app/API; disposable synthetic canonical DB only."""
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from language_learning.jobs import LanguageJobManager
from language_learning.grammar_parser import GrammarParser
from tests.language_phase2_fakes import wait_for_job


def main():
    edge=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    output=Path(tempfile.mkdtemp(prefix='language-phase11-edge-'))
    print('Artifacts:',output,flush=True)
    service=None; manager=None
    class Handler(server.Handler):
        def do_GET(self):
            if self.path.startswith('/__grammar_fixture/smoke?'):
                body=(ROOT/'tests/fixtures/language/phase11-browser-smoke.html').read_bytes()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            if self.path=='/__grammar_fixture/parser-unavailable':
                service.grammar.parser=GrammarParser(model_dir=output/'missing')
                self.send_json({'ok':True,'data':{}}); return
            super().do_GET()
        def log_message(self,*args): pass
    httpd=server.DashboardHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    try:
        results=[]
        for width,height in [(1440,1000),(430,900),(390,844)]:
            if manager: manager.stop()
            service=LanguageService(LanguageStore(output/f'synthetic-{width}.sqlite'))
            service.initialize(); profile=service.ensure_bokmal_profile()['profile']['id']
            manager=LanguageJobManager(service,poll_interval=.01)
            server.LANGUAGE_SERVICE=service; server.LANGUAGE_STORE=service.store; server.LANGUAGE_JOBS=manager
            # Unique neutral whitespace prevents cross-document canonical dedupe.
            text=service.create_text_draft({'languageProfileId':profile,'title':f'Grammar synthetic {width}','rawText':'Jeg jobber i Oslo.'+' '*(width%7+1)+'Jeg har jobbet.'})['data']['text']
            with patch('socket.socket.connect',side_effect=AssertionError('NLP network blocked')):
                job=service.enqueue_analysis(text['id'],{})['data']['job']
                assert wait_for_job(service,job['id'],timeout=60)['state']=='COMPLETED'
            url=f"http://127.0.0.1:{httpd.server_address[1]}/__grammar_fixture/smoke?text={text['id']}&profile={profile}"
            command=['node',str(ROOT/'scripts/language_grammar_edge.mjs'),str(edge),str(output/('profile-'+str(width))),str(width),str(height),url,str(output/(str(width)+'.png')),str(output/(str(width)+'.html'))]
            completed=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=120)
            result=json.loads(completed.stdout) if completed.stdout.strip().startswith('{') else {'pass':False,'error':'PENDING','stderr':completed.stderr[-1000:]}
            results.append({'width':width,'height':height,**result});print(json.dumps(results[-1]),flush=True)
            if not result['pass']: break
        (output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        # Query/Reader timings on real canonical synthetic evidence.
        timings={}
        for name,fn in [('landing',lambda:service.grammar.summary(profile)),('patternDetail',lambda:service.grammar.summary(profile,'A1_PRESENT_TENSE')),('readerWithoutGrammar',lambda:service.get_text(text['id']))]:
            samples=[]
            for _ in range(20):
                start=time.perf_counter();fn();samples.append((time.perf_counter()-start)*1000)
            timings[name]={'medianMs':round(sorted(samples)[len(samples)//2],3),'maxMs':round(max(samples),3)}
        print(json.dumps(timings),flush=True)
        if not all(r['pass'] for r in results) or len(results)!=3: raise SystemExit(1)
    finally:
        if manager: manager.stop()
        httpd.shutdown();httpd.server_close();thread.join(2)

if __name__=='__main__': main()
