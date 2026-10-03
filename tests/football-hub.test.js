import { beforeAll, afterAll, describe, expect, it, vi } from 'vitest';

const match = { id:'espn:1',category:'result',status:'FT',clubKeys:['liverpool','other'],home:{name:'Liverpool'},away:{name:'Other'},score:{home:2,away:0},playedAt:'2026-10-01',details:[{minute:'12',kind:'goal',team:'Liverpool',text:'<img src=x onerror=alert(1)>'}] };
const club = {key:'liverpool',name:'Liverpool',names:['Liverpool'],providerIds:{},followed:true};
const snapshot = {ok:true,updatedAt:'2026-10-01',cache:[{status:'fresh',ageSeconds:10}],sourceErrors:[],following:{teams:['liverpool'],competitions:[],standings:[],windowHours:24},clubs:[club],competitions:[],matches:[match],stored:{matches:1},newsStatus:'No feed',providers:[],requests:[],runs:[],fallback:{},storageNote:''};
let detailResponse;
let sportState = {enabledTeamKeys:['liverpool','montreal-canadiens'],enabledLeagueKeys:['nhl'],standingsLeagueKeys:[]};
const api = vi.fn(async (url,options={}) => {
 if (url === '/api/football' || url === '/api/football/refresh') return {ok:true,json:async()=>snapshot};
 if (url === '/api/football/settings') return {ok:true,json:async()=>({ok:true})};
 if (url === '/api/kitchen/settings') {
  if (options.method === 'POST') sportState=JSON.parse(options.body).sports;
  return {ok:true,json:async()=>({ok:true,sports:sportState})};
 }
 if (url.startsWith('/api/football/search')) return {ok:true,json:async()=>({ok:true,items:[{kind:'player',key:'player-one',name:'One'}]})};
 if (url === '/api/football/learn') return {ok:true,json:async()=>({ok:true,items:[{title:'Fact',text:'Text',category:'trivia',source:'IFAB',sourceUrl:'javascript:alert(1)',dateAdded:'2026-10-01'}]})};
 if (url.startsWith('/api/football/entity')) return {ok:true,json:async()=> typeof detailResponse === 'function' ? await detailResponse() : detailResponse};
 throw new Error(url);
});
async function route(hash) {
 window.location.hash=hash;
 window.dispatchEvent(new Event('hashchange'));
 await new Promise(resolve=>setTimeout(resolve,20));
}
beforeAll(async()=>{
 document.body.innerHTML='<p id="football-freshness"></p><p id="football-notice"></p><main id="football-content"></main>';
 window.location.hash='#overview';vi.stubGlobal('fetch',api);
 await import('../js/football.js');
 await vi.waitFor(()=>expect(document.querySelector('h2')?.textContent).toBe('Overview'));
});
afterAll(()=>{window.dispatchEvent(new Event('pagehide'));vi.unstubAllGlobals();});

describe('Football Hub navigation and degraded data',()=>{
 it('renders real match events as text and links clubs',async()=>{
  await route('#match/espn%3A1');
  expect(document.getElementById('football-content').textContent).toContain('<img src=x onerror=alert(1)>');
  expect(document.querySelector('img[src="x"]')).toBeNull();
  expect(document.querySelector('a[href="#club/liverpool"]')).toBeTruthy();
 });
 it('does not let a slow entity response overwrite the next screen',async()=>{
  let resolve;detailResponse=()=>new Promise(r=>{resolve=r;});
  await route('#player/slow');await route('#matches');
  resolve({ok:true,player:{name:'Stale'},statistics:{},cache:[]});
  await new Promise(r=>setTimeout(r,20));
  expect(document.querySelector('h2').textContent).toBe('Matches');
 });
 it('shows stale source state without discarding the player',async()=>{
  detailResponse={ok:true,player:{name:'One',clubKey:'liverpool',clubName:'Liverpool'},statistics:{},cache:[{key:'squad',state:'stale',error:'provider-unavailable',fetchedAt:1000}]};
  await route('#player/player-one');
  expect(document.querySelector('h2').textContent).toBe('One');
  expect(document.querySelector('.football-warning')).toBeTruthy();
 });
 it('uses debounced local search and ignores unsafe learning URLs',async()=>{
  await route('#players');
  expect(api.mock.calls.some(([url])=>url.includes('kind=player'))).toBe(true);
  const input=document.getElementById('football-search-query');
  const initial=api.mock.calls.length;
  for(const value of ['O','On','One']) {input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}
  await new Promise(r=>setTimeout(r,350));
  expect(api.mock.calls.length-initial).toBe(1);
  await route('#learn');
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(document.getElementById('football-content').textContent).toContain('IFAB');
 });
 it('adds a favourite once and preserves other sports on repeated saves',async()=>{
  await route('#following');
  document.getElementById('football-save-following').click();
  await vi.waitFor(()=>expect(sportState.enabledTeamKeys).toEqual(['liverpool','montreal-canadiens']));
  await route('#following');document.getElementById('football-save-following').click();
  await new Promise(r=>setTimeout(r,30));
  expect(sportState.enabledTeamKeys).toEqual(['liverpool','montreal-canadiens']);
  expect(sportState.enabledLeagueKeys).toEqual(['nhl']);
 });
});
