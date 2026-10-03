"""Run the real dashboard handler in a disposable source tree (no real runtime files)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from journal_store import JournalStore

server.JOURNAL_STORE = JournalStore(Path(sys.argv[1]))
server.JOURNAL_STORE.initialize()
httpd = server.DashboardHTTPServer(('127.0.0.1', 0), server.Handler)
print(f'SYNC_TEST_PORT={httpd.server_address[1]}', flush=True)
httpd.serve_forever()
