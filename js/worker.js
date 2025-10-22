export default {
  async fetch(req) {
    const url = new URL(req.url);
    // przekieruj tylko /gios/* do API GIOŚ
    if (url.pathname.startsWith('/gios/')) {
      const upstream = 'https://api.gios.gov.pl' + url.pathname.replace('/gios','') + url.search;
      const r = await fetch(upstream, { headers: { 'accept':'application/json' } });
      const res = new Response(r.body, r);
      res.headers.set('Access-Control-Allow-Origin', '*');
      res.headers.set('Access-Control-Allow-Headers', '*');
      res.headers.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
      return res;
    }
    return new Response('ok', { status: 200 });
  }
}
