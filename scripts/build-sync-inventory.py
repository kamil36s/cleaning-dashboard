"""Source-only audit; never opens runtime data. Run from repository root."""
import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
SOURCES = {}
for name in FILES:
    if name.endswith(('.py', '.js', '.kt')) and not name.startswith(('data/', 'public/', 'tests/', 'antigravity-context/', 'apps/history-wiki/')):
        try:
            SOURCES[name] = (ROOT / name).read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            pass


def link(name, line=1):
    return f'[{name}:{line}](../{name}#L{line})'


def clean(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def build():
    project_map = (ROOT / 'PROJECT_MAP.md').read_text(encoding='utf-8')
    stores = project_map.split('## Persistence / Data Stores')[1].split('\n## ')[0]
    domains = project_map.split('## Backend / API Domains')[1].split('\n## ')[0]
    store_rows = ['| Module | Data | Storage | Current source of truth | API | Sync candidate | Notes |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
    for line in stores.splitlines():
        if not line.startswith('| ') or line.startswith(('| Feature ', '| ---')):
            continue
        feature, storage, role, notes = [part.strip() for part in line.strip('|').split('|')]
        filenames = re.findall(r'`([^`]+)`', storage)
        api = [row.split('|')[1].strip() for row in domains.splitlines() if row.startswith('| `/api/')
               and any(filename in row for filename in filenames)]
        api = ', '.join(api) or 'Domain routes in API-INVENTORY; no exact file match'
        candidate = 'Selected written entry only' if feature == 'Journals' else 'Deferred; not migrated'
        role = role.replace('RAW ARCHIVE', 'CANONICAL evidence').replace('GENERATED', 'DERIVED').replace('MIGRATION/SEED', 'LEGACY').replace('browser-only', 'CLIENT-ONLY').replace('EXTERNAL MIRROR / ANALYTICS SOURCE', 'CACHE / DERIVED').replace('EXTERNAL OBSERVATION + EVENT HISTORY', 'CACHE observations + CANONICAL history')
        store_rows.append(f'| {feature} | {notes.split(";")[0]} | {storage} | {role} | {api} | {candidate} | {notes} |')
    stores = '\n'.join(store_rows)
    data = ['# Data inventory', '', 'Source audit started from build-0001 and regenerated from the task working tree; Sync pilot changes are detailed in SYNC-ARCHITECTURE.md. No private payloads are included.', '',
            '## Storage and authority', '',
            'SQLite, JSON, JSONL, CSV, raw filesystem archives, browser localStorage/sessionStorage and native Android Room/preferences are present. No browser IndexedDB implementation was found. SQLite is not automatically authoritative: reference DBs and metadata caches are rebuildable.', '',
            'Roles: CANONICAL = durable owner; CACHE = replaceable mirror; DERIVED = rebuildable output; CLIENT-ONLY = browser/native state; LEGACY = recovery/import only; UNKNOWN = authority not established. Raw originals are CANONICAL evidence, even when their parsed projections are derived.', '',
            'The following feature-local authority map is cross-referenced by the executable source evidence below. Mixed roles belong to distinct files within a domain, not interchangeable writers.', '', stores.strip(), '',
            '## Additional domains and pilot decision', '',
            '| Module | Data | Storage / current source of truth | API | Sync candidate | Notes |',
            '| --- | --- | --- | --- | --- | --- |',
            '| Todo / Projects / Shopping | Tasks, nested subtasks, backlog | CANONICAL `data/settings/todo.json`; CLIENT-ONLY recovery copy `todo-items-v1` | `/api/settings/todo`, `/api/phone-todo` | Later | Whole-list writes and fire-and-forget fallback can overwrite remote edits; seed deletion markers are meaningful. Do not migrate first. |',
            '| Written journal | Entries, poems, provenance | CANONICAL `data/journal.sqlite`; CLIENT-ONLY unsaved drafts and view preferences | `/api/journal/entries` | **Selected: journalEntry only** | UUID hex IDs, one store, no published-entry localStorage fallback; imports and voice/HTR publication converge on same SQL table. Preserve drafts. |',
            '| Feelings | Check-ins, tags, emotions | CANONICAL `data/feelings.sqlite` | `/api/feelings/*` | Later | Existing Android queue, imports and reference taxonomy require separate audit. |',
            '| Mental health | Assessments, trackers, schedules | CANONICAL `data/mental-health.sqlite` | `/api/mental-health/*` | Later | Multi-entity dependencies. |',
            '| Football | Historical observations | CANONICAL `data/football.sqlite`; CACHE Kitchen snapshots | `/api/football*` | Low | Mostly externally derived reads. |',
            '| Self care | Browser history plus imported timeline capture | CLIENT-ONLY browser state; CANONICAL capture JSONL; equivalence UNKNOWN | `/api/timeline/activity/*` | Defer | Do not infer that capture supersedes all browser history. |',
            '| Kermit | Derived index, temporary conversations | DERIVED filesystem index; CLIENT-ONLY/in-memory chat session | `/api/kermit/v1/*` | No | Does not own dashboard domain records. |', '',
            '## Risks / hard gate', '',
            'Published journal entries have an unambiguous canonical owner (`JournalStore`). Existing imports call that store; SQL triggers can track every insert/update/delete atomically, including older running processes. No relocation of content or ID conversion is needed. Back up the SQLite database with the SQLite backup API before adding metadata/triggers. Browser drafts remain unsaved user data, never a server fallback. Pilot gate: PASS.', '',
            'Todo local-first fallback, generated habits views versus Habits DB, alternate Spotify servers, central versus independent workout handlers, and direct import scripts are authority boundaries; they remain unchanged. Client wall clocks and timestamp-only cursors are unsuitable for shared synchronization.', '',
            '## Source evidence by mechanism', '']
    patterns = {
        'Persistence / browser stores': r'sqlite3\.connect|localStorage|sessionStorage|indexedDB|Room\.databaseBuilder|DataStore|SharedPreferences',
        'File writes / settings / import-export / backups': r'write_text\(|write_bytes\(|json\.dump\(|\.backup\(|os\.replace\(|def .*import|def .*export|def .*backup',
        'Transports / polling / jobs': r'fetch\(|EventSource|WebSocket|setInterval\(|Worker\(|Thread\(|def .*sync|def .*worker',
        'Identity / timestamps / revisions / deletion': r'uuid4|randomUUID|createdAt|updatedAt|deletedAt|baseRevision|expectedVersion|AUTOINCREMENT',
    }
    for title, pattern in patterns.items():
        data += [f'### {title}', '', '| Source | Matching lines |', '| --- | --- |']
        for name, source in sorted(SOURCES.items()):
            matches = [i for i, line in enumerate(source.splitlines(), 1) if re.search(pattern, line)]
            if matches:
                data.append(f'| {link(name, matches[0])} | {", ".join(map(str, matches))} |')
        data.append('')
    (ROOT / 'docs/DATA-INVENTORY.md').write_text('\n'.join(data).rstrip() + '\n', encoding='utf-8')

    rows = set()
    contracts = {}
    for name, source in SOURCES.items():
        if not name.endswith('.py'):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            method = re.search(r'(?:do_|dispatch_.*_)(GET|POST|PATCH|PUT|DELETE|OPTIONS|HEAD)$', fn.name, re.I)
            methods = [method[1].upper()] if method else []
            decorator_paths = []
            for decorator in fn.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr in ('get', 'post', 'put', 'patch', 'delete', 'route'):
                        decorator_paths += [n.value for n in decorator.args if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')]
                        if decorator.func.attr == 'route':
                            methods += [n.value for kw in decorator.keywords if kw.arg == 'methods' for n in ast.walk(kw.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                        else:
                            methods.append(decorator.func.attr.upper())
            if not methods:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith('/api/'):
                    # Route patterns are retained verbatim; prefix dispatch is explicitly labelled.
                    path = node.value
                    if '\n' in path or len(path) > 240:
                        continue
                    for verb in methods:
                        rows.add((path, verb, name, node.lineno, fn.name))
                    branch = node
                    while branch in parents and not isinstance(branch, (ast.If, ast.FunctionDef)):
                        branch = parents[branch]
                    calls = [item for item in ast.walk(branch) if isinstance(item, ast.Call)]
                    fields = sorted({item.args[0].value for item in calls if isinstance(item.func, ast.Attribute)
                        and item.func.attr == 'get' and item.args and isinstance(item.args[0], ast.Constant)
                        and isinstance(item.args[0].value, str)})
                    responses = [ast.unparse(item.args[0]) for item in calls if isinstance(item.func, ast.Attribute)
                        and item.func.attr in ('send_json', 'jsonify') and item.args]
                    delegates = sorted({ast.unparse(item.func) for item in calls if isinstance(item.func, ast.Attribute)
                        and isinstance(item.func.value, ast.Name) and item.func.value.id.isupper()})
                    contracts[(name, node.lineno)] = (', '.join(fields[:12]), '; '.join(responses[:2])[:210], ', '.join(delegates[:3]))
    api = ['# API inventory', '', 'Generated source route index, not a claim that every endpoint has a runtime contract test. Regex paths and prefix dispatches are retained verbatim; a prefix row denotes a route family. Source links locate route expressions. Extracted request, response and delegate snippets are heuristic: a shared enclosing handler can contribute unrelated branches. They are navigation hints, not verified per-route schemas; unknown authority is explicitly UNKNOWN. The reviewed Sync contract is in SYNC-PROTOCOL.md. Run `python scripts/build-sync-inventory.py` to refresh.', '',
           '## Domain ownership and persistence', '', domains.strip(), '',
           '## Contract conventions and conflicts', '',
           '- Central API: `ThreadingHTTPServer`, default `127.0.0.1:8000`, configurable `DASHBOARD_HOST`, explicit allowed origins. Existing authorization varies by domain; Sync adds a stricter isolated boundary.',
           '- Settings: GET returns `{ok,data}`; POST `{data}` writes allowlisted JSON. Frontend `file-settings.js` maintains localStorage and may send an old fallback after a failed read. Todo phone writes lock and replace that same canonical file.',
           '- Journal: GET collection `{entries}`, item/plain record; POST/PATCH mutable fields; DELETE `{deleted,id}`; domain errors `{error,code}`; Sync validation/conflicts use `{error:{code,message,details}}`, with HTTP 409 for stale writes. Existing UI uses `js/journal-api.js`; drafts are local only.',
           '- Habits: snapshot/sync with revisions, cursor and processed mutations. Kept intact; shared Sync follows its SQLite/receipt precedent without pretending its wire format is identical.',
           '- Workout: central legacy handlers duplicate independent runtime routes; current frontend owns runtime base URL. Spotify Python/Node routes also overlap. Do not choose either duplicate as a new authority.',
           '- Network uses Flask JSON; language/job-hunt/finance use service-specific objects; some routes return files, SSE or HTML. Read/write column describes HTTP intent, not proof that a GET never refreshes a cache.',
           '- Direct filesystem writers, imports, browser bypasses, polling and background jobs are indexed in DATA-INVENTORY.md. Response keys, validation, status codes and persistence must be read together at each linked handler; schemas are not standardized by this audit.', '',
           '## Python routes', '', '| Method | Path / pattern | Domain | Read / write | Request | Response | Persistence / canonical? | Used by / implementation |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for path, method, name, line, fn in sorted(rows):
        domain = path.split('/')[2] if len(path.split('/')) > 2 else 'dispatch'
        callers = [n for n, s in SOURCES.items() if n.endswith(('.js', '.kt')) and f'/api/{domain}' in s]
        used = ', '.join(f'`{n}`' for n in callers[:4]) or 'No literal client match; dynamic/indirect caller UNKNOWN'
        fields, responses, delegates = contracts.get((name, line), ('', '', ''))
        request = ('query/path' if method in ('GET', 'HEAD', 'DELETE', 'OPTIONS') else 'body/path') + (f'; fields found: {fields}' if fields else '; parser/delegation at source')
        response = f'`{clean(responses)}`' if responses else f'Handler `{fn}` (JSON/file/SSE by branch)'
        persistence = f'`{clean(delegates)}`; domain ownership above' if delegates else 'Domain ownership above; unresolved paths UNKNOWN'
        api.append(f'| {method} | `{clean(path)}` | {domain} | {"READ" if method in ("GET", "HEAD", "OPTIONS") else "WRITE/action"} | {clean(request)}; {link(name, line)} | {response} | {persistence} | {used} |')
    api += ['', '## Common Sync additions', '', 'The exact request, response, persistence, authorization and client contract for the four new `/api/sync/*` routes is specified in [SYNC-PROTOCOL.md](SYNC-PROTOCOL.md). Their dispatch is factored into `dashboard_sync/http.py`; the canonical domain adapter is `dashboard_sync/journal.py`. No other domain is migrated.']
    api += ['', '## Alternate Node routes', '', '| Method | Path | Implementation |', '| --- | --- | --- |']
    for name, source in SOURCES.items():
        if not name.endswith('.js'):
            continue
        for i, line in enumerate(source.splitlines(), 1):
            match = re.search(r'\b(?:app|router)\.(get|post|put|patch|delete)\([\'\"]([^\'\"]+)', line)
            if match:
                api.append(f'| {match[1].upper()} | `{match[2]}` | {link(name, i)} |')
    (ROOT / 'docs/API-INVENTORY.md').write_text('\n'.join(api) + '\n', encoding='utf-8')
    print(f'Audited {len(SOURCES)} source files; {len(rows)} Python route/prefix registrations.')


if __name__ == '__main__':
    build()
