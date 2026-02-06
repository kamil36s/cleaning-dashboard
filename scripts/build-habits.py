import argparse
import csv
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None

ENTRY_RE = re.compile(r"value=([0-9]+(?:\.[0-9]+)?)")


def read_text_guess(path):
    for enc in ("utf-8", "cp1250", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except Exception:
            continue
    raise RuntimeError(f"Cannot read file with known encodings: {path}")


def parse_date(date_str, tz_name):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if tz_name.upper() == "UTC" or ZoneInfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif tz_name.lower() == "local":
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    else:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return int(dt.timestamp() * 1000)


def habit_name_from_folder(path):
    folder = os.path.basename(os.path.dirname(path))
    name = re.sub(r"^\d+\s*", "", folder).strip()
    return name or folder


def parse_value(cell):
    if cell is None:
        return None
    raw = cell.strip().strip(",")
    if not raw:
        return None
    if "Entry(" in raw:
        m = ENTRY_RE.search(raw)
        if m:
            return float(m.group(1))
    # numeric
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except Exception:
        pass
    # boolean-ish
    if raw.lower() in ("x", "true", "yes", "y", "done"):
        return 1
    if raw.lower() in ("false", "no", "n"):
        return 0
    return None


def load_db(db_path):
    habits = {}
    points = []
    info = {
        "path": db_path,
        "habits": 0,
        "points": 0,
        "errors": []
    }

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT Id, name, type, unit FROM Habits ORDER BY Id")
        for hid, name, htype, unit in cur.fetchall():
            habits[name] = {
                "id": int(hid),
                "name": name,
                "type": int(htype),
                "unit": unit or "",
            }

        cur.execute("SELECT habit, timestamp, value FROM Repetitions ORDER BY timestamp")
        for hid, ts, value in cur.fetchall():
            name = None
            for h in habits.values():
                if h["id"] == int(hid):
                    name = h["name"]
                    break
            if name is None:
                continue
            points.append((name, int(ts), float(value), f"db:{os.path.basename(db_path)}"))
        conn.close()
        info["habits"] = len(habits)
        info["points"] = len(points)
    except Exception as e:
        info["errors"].append(str(e))

    return habits, points, info


def load_checkmarks_csv(csv_path, tz_name):
    info = {
        "path": csv_path,
        "kind": None,
        "encoding": None,
        "rows": 0,
        "points": 0,
        "skipped_rows": 0,
        "skipped_values": 0,
        "errors": []
    }
    try:
        text, enc = read_text_guess(csv_path)
        info["encoding"] = enc
    except Exception as e:
        info["errors"].append(str(e))
        return [], {}, info

    rows = list(csv.reader(text.splitlines()))
    info["rows"] = len(rows)
    if not rows:
        return [], {}, info

    points = []
    habits = {}
    first = rows[0]
    has_header = first and first[0].strip().lower() in ("date", "day")

    warned_split = False
    if has_header:
        info["kind"] = "checkmarks_header"
        headers = [h.strip() for h in first[1:] if h.strip()]
        for name in headers:
            habits[name] = {"name": name}
        for row in rows[1:]:
            if not row or not row[0].strip():
                info["skipped_rows"] += 1
                continue
            date_str = row[0].strip()
            try:
                ts = parse_date(date_str, tz_name)
            except Exception:
                info["skipped_rows"] += 1
                continue
            row_cells = row[1:]
            if len(headers) == 1 and len(row_cells) > 1:
                row_cells = [",".join(row_cells)]
            elif len(row_cells) != len(headers) and not warned_split:
                info["errors"].append("Row has different column count than headers. CSV values may contain commas without quotes.")
                warned_split = True
            for i, name in enumerate(headers):
                if i >= len(row_cells):
                    info["skipped_values"] += 1
                    continue
                val = parse_value(row_cells[i])
                if val is None:
                    info["skipped_values"] += 1
                    continue
                points.append((name, ts, float(val), f"csv:{os.path.basename(csv_path)}"))
    else:
        info["kind"] = "checkmarks_simple"
        parent = os.path.basename(os.path.dirname(csv_path)).lower()
        if parent == "csv":
            info["kind"] = "checkmarks_simple_root"
            info["errors"].append("Simple CSV in data/raw/csv root has no habit name. Move it into a habit-named folder.")
            return [], {}, info
        name = habit_name_from_folder(csv_path)
        habits[name] = {"name": name}
        for row in rows:
            if not row or len(row) < 2:
                info["skipped_rows"] += 1
                continue
            date_str = row[0].strip()
            val = parse_value(row[1])
            if not date_str or val is None:
                info["skipped_rows"] += 1
                continue
            try:
                ts = parse_date(date_str, tz_name)
            except Exception:
                info["skipped_rows"] += 1
                continue
            points.append((name, ts, float(val), f"csv:{os.path.basename(csv_path)}"))
    info["points"] = len(points)
    return points, habits, info


def detect_type(values):
    for v in values:
        if v is None:
            continue
        if v > 2:
            return 1
    return 0


def build_dataset(db_paths, csv_paths, tz_name):
    habit_meta = {}
    points = []
    report = {
        "db_files": [],
        "csv_files": [],
        "csv_skipped": [],
        "input_points": 0,
        "kept_points": 0,
        "habits": 0,
        "conflicts": 0,
        "errors": []
    }

    # DB first
    for db_path in db_paths:
        db_habits, db_points, db_info = load_db(db_path)
        report["db_files"].append(db_info)
        report["errors"].extend(db_info.get("errors", []))
        for name, meta in db_habits.items():
            habit_meta[name] = meta
        points.extend(db_points)

    # CSV checkmarks
    for csv_path in csv_paths:
        base = os.path.basename(csv_path).lower()
        if base.startswith("scores"):
            report["csv_skipped"].append({"path": csv_path, "reason": "scores.csv"})
            continue
        if base.startswith("habits"):
            # not used for data points yet
            report["csv_skipped"].append({"path": csv_path, "reason": "habits.csv"})
            continue
        csv_points, csv_habits, csv_info = load_checkmarks_csv(csv_path, tz_name)
        report["csv_files"].append(csv_info)
        report["errors"].extend(csv_info.get("errors", []))
        points.extend(csv_points)
        for name in csv_habits.keys():
            if name not in habit_meta:
                habit_meta[name] = {"name": name, "type": None, "unit": ""}

    # determine types for csv-only habits
    values_by_habit = {}
    for name, ts, val, _src in points:
        values_by_habit.setdefault(name, []).append(val)
    for name, meta in habit_meta.items():
        if meta.get("type") is None:
            meta["type"] = detect_type(values_by_habit.get(name, []))

    # assign ids for csv-only habits
    used_ids = {m["id"] for m in habit_meta.values() if "id" in m}
    for name, meta in habit_meta.items():
        if "id" not in meta:
            new_id = 100000 + (abs(zlib_crc(name)) % 900000)
            while new_id in used_ids:
                new_id += 1
            used_ids.add(new_id)
            meta["id"] = new_id

    # merge with conflict detection
    conflicts = []
    data_points = {name: {} for name in habit_meta.keys()}
    merged_points = {name: [] for name in habit_meta.keys()}

    report["input_points"] = len(points)

    for name, ts, val, src in sorted(points, key=lambda x: x[1]):
        if name not in habit_meta:
            continue
        date_key = datetime.utcfromtimestamp(ts / 1000).date().isoformat()
        existing = data_points[name].get(date_key)
        if existing is None:
            data_points[name][date_key] = (val, src)
            merged_points[name].append([int(ts), int(val) if float(val).is_integer() else float(val)])
        else:
            existing_val, existing_src = existing
            if float(existing_val) != float(val):
                conflicts.append({
                    "habit": name,
                    "date": date_key,
                    "existing": {"value": existing_val, "source": existing_src},
                    "incoming": {"value": val, "source": src},
                    "action": "kept_existing"
                })

    habits_out = []
    for name, meta in habit_meta.items():
        pts = merged_points.get(name, [])
        pts.sort(key=lambda x: x[0])
        habits_out.append({
            "id": int(meta["id"]),
            "name": meta["name"],
            "type": int(meta["type"]),
            "unit": meta.get("unit", "") or "",
            "points": pts
        })
    habits_out.sort(key=lambda h: h["name"].lower())

    report["kept_points"] = sum(len(h["points"]) for h in habits_out)
    report["habits"] = len(habits_out)
    report["conflicts"] = len(conflicts)

    return {"habits": habits_out}, conflicts, report


def zlib_crc(text):
    import zlib
    return zlib.crc32(text.encode("utf-8"))


def find_latest_db(folder):
    if not os.path.isdir(folder):
        return []
    candidates = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".db")]
    if not candidates:
        return []
    latest = max(candidates, key=os.path.getmtime)
    return [latest]


def expand_csv_inputs(inputs, folder):
    paths = []
    for pattern in inputs:
        if os.path.isdir(pattern):
            paths.extend(glob.glob(os.path.join(pattern, "**", "*.csv"), recursive=True))
        else:
            paths.extend(glob.glob(pattern))
    if not inputs:
        if os.path.isdir(folder):
            paths.extend(glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True))
    return sorted(set(paths))


def html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_section(report, conflicts):
    def td(val):
        return f"<td>{html_escape(val)}</td>"

    def th(val):
        return f"<th>{html_escape(val)}</th>"

    def table(headers, rows):
        head = "<tr>" + "".join(th(h) for h in headers) + "</tr>"
        body = "".join("<tr>" + "".join(td(c) for c in row) + "</tr>" for row in rows)
        return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"

    db_rows = []
    for db in report.get("db_files", []):
        db_rows.append([
            db.get("path", ""),
            db.get("habits", 0),
            db.get("points", 0),
            "; ".join(db.get("errors", [])) or ""
        ])

    csv_rows = []
    for csv in report.get("csv_files", []):
        csv_rows.append([
            csv.get("path", ""),
            csv.get("kind", ""),
            csv.get("encoding", ""),
            csv.get("rows", 0),
            csv.get("points", 0),
            csv.get("skipped_rows", 0),
            csv.get("skipped_values", 0),
            "; ".join(csv.get("errors", [])) or ""
        ])

    skipped_rows = []
    for s in report.get("csv_skipped", []):
        skipped_rows.append([s.get("path", ""), s.get("reason", "")])

    conflict_rows = []
    for c in conflicts[:20]:
        conflict_rows.append([
            c.get("habit", ""),
            c.get("date", ""),
            f"{c.get('existing', {}).get('value', '')} ({c.get('existing', {}).get('source', '')})",
            f"{c.get('incoming', {}).get('value', '')} ({c.get('incoming', {}).get('source', '')})",
            c.get("action", "")
        ])

    title = f"{format_generated_at(report.get('generated_at', ''))} - CSV TZ {report.get('tz', '')}"

    section = f"""
<section class="report">
  <div class="report-ts">{html_escape(title)}</div>
  <div class="meta">Inputs: DB {html_escape(", ".join(report.get("inputs", {}).get("db", [])) or "-")} - CSV {html_escape(", ".join(report.get("inputs", {}).get("csv", [])) or "-")}</div>

  <h2>Summary</h2>
  <ul>
    <li>Habits: <strong>{report.get("habits", 0)}</strong></li>
    <li>Input points: <strong>{report.get("input_points", 0)}</strong></li>
    <li>Kept points: <strong>{report.get("kept_points", 0)}</strong></li>
    <li>Conflicts: <strong>{report.get("conflicts", 0)}</strong></li>
    <li>CSV files: <strong>{report.get("csv_files_count", 0)}</strong></li>
    <li>CSV points: <strong>{report.get("csv_points", 0)}</strong></li>
    <li>CSV skipped values: <strong>{report.get("csv_skipped_values", 0)}</strong></li>
  </ul>

  {"<h2>Warnings</h2><ul>" + "".join(f"<li>{html_escape(w)}</li>" for w in report.get("warnings", [])) + "</ul>" if report.get("warnings") else ""}

  <h2>DB Files</h2>
  {table(["Path", "Habits", "Points", "Errors"], db_rows) if db_rows else "<div class='meta'>No DB files</div>"}

  <h2>CSV Files</h2>
  {table(["Path", "Kind", "Encoding", "Rows", "Points", "Skipped rows", "Skipped values", "Errors"], csv_rows) if csv_rows else "<div class='meta'>No CSV files</div>"}

  <h2>CSV Skipped</h2>
  {table(["Path", "Reason"], skipped_rows) if skipped_rows else "<div class='meta'>No skipped files</div>"}

  <h2>Conflicts (first 20)</h2>
  {table(["Habit", "Date", "Existing", "Incoming", "Action"], conflict_rows) if conflict_rows else "<div class='meta'>No conflicts</div>"}

  <h2>Outputs</h2>
  <ul>
    <li>JSON: <code>{html_escape(report.get("outputs", {}).get("json", ""))}</code></li>
    <li>JS: <code>{html_escape(report.get("outputs", {}).get("js", ""))}</code></li>
    <li>Conflicts: <code>{html_escape(report.get("outputs", {}).get("conflicts", ""))}</code></li>
    <li>Report: <code>{html_escape(report.get("outputs", {}).get("report", ""))}</code></li>
    <li>Report HTML: <code>{html_escape(report.get("outputs", {}).get("report_html", ""))}</code></li>
  </ul>
</section>
"""
    return section


def format_generated_at(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return value


def extract_sections(html):
    return re.findall(r"<section class=\"report\">[\s\S]*?</section>", html, re.IGNORECASE)


def extract_body(html):
    m = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_generated_at(html):
    m = re.search(r"Generated at\s*([^<]+)", html, re.IGNORECASE)
    return m.group(1).strip() if m else "Previous import"


def legacy_section_from_html(html):
    body = extract_body(html) or html
    if not body:
        return ""
    body = re.sub(r"<h1[^>]*>[\s\S]*?</h1>", "", body, flags=re.IGNORECASE)
    body = re.sub(r"<div class=\"meta\">Generated at[\s\S]*?</div>", "", body, flags=re.IGNORECASE)
    body = body.strip()
    title = extract_generated_at(html)
    return f"""
<section class="report">
  <div class="report-ts">{html_escape(title)}</div>
  {body}
</section>
"""


def normalize_sections(sections):
    cleaned = []
    for sec in sections:
        if re.search(r"<!doctype|<html", sec, re.IGNORECASE):
            m = re.search(r"(<html[\s\S]*?</html>)", sec, re.IGNORECASE)
            html = m.group(1) if m else sec
            legacy = legacy_section_from_html(html)
            if legacy:
                cleaned.append(legacy)
                continue
        cleaned.append(sec)
    return cleaned


def render_report_page(sections_html):
    return f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Habit Import Reports</title>
  <style>
    body {{ font-family: system-ui, Segoe UI, Arial, sans-serif; padding: 20px; color: #111; background: #f6f6f6; }}
    h1 {{ margin: 0 0 12px; font-size: 22px; }}
    h2 {{ margin: 18px 0 8px; font-size: 16px; }}
    .meta {{ color: #666; font-size: 12px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 8px 0 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; }}
    code {{ background: #f1f1f1; padding: 2px 4px; border-radius: 4px; }}
    .report {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
    .report-ts {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; }}
  </style>
</head>
<body>
  <h1>Habit Import Reports</h1>
  <div id="reports">
  {sections_html}
  </div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build habit-data.json/js from DB and CSV exports")
    parser.add_argument("--db", nargs="*", default=None, help="Path(s) to .db files. If omitted, uses newest in data/raw/db.")
    parser.add_argument("--csv", nargs="*", default=None, help="Path(s)/glob(s) to CSV files. If omitted, uses data/raw/csv/*.csv.")
    parser.add_argument("--out", default="data/habit-data.json", help="Output JSON path")
    parser.add_argument("--js", default="js/habit-data.js", help="Output JS path")
    parser.add_argument("--conflicts", default="data/conflicts.json", help="Conflicts JSON path")
    parser.add_argument("--report", default="data/report.json", help="Report JSON path")
    parser.add_argument("--report-html", default="data/report.html", help="Report HTML path")
    parser.add_argument("--tz", default="Europe/Warsaw", help="Timezone for CSV dates (default: Europe/Warsaw). Use e.g. UTC or local.")
    args = parser.parse_args()

    db_paths = args.db if args.db is not None and len(args.db) else find_latest_db("data/raw/db")
    csv_paths = expand_csv_inputs(args.csv or [], "data/raw/csv")

    if not db_paths and not csv_paths:
        print("No DB or CSV inputs found.", file=sys.stderr)
        sys.exit(1)

    data, conflicts, report = build_dataset(db_paths, csv_paths, args.tz)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, separators=(",", ":"))
        f.write("\n")

    with open(args.js, "w", encoding="utf-8") as f:
        f.write("window.HABIT_DB=")
        json.dump(data, f, ensure_ascii=True, separators=(",", ":"))
        f.write(";\n")

    os.makedirs(os.path.dirname(args.conflicts), exist_ok=True)
    with open(args.conflicts, "w", encoding="utf-8") as f:
        json.dump({"conflicts": conflicts}, f, ensure_ascii=True, indent=2)

    report.update({
        "generated_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "tz": args.tz,
        "inputs": {"db": db_paths, "csv": csv_paths},
        "outputs": {
            "json": args.out,
            "js": args.js,
            "conflicts": args.conflicts,
            "report": args.report,
            "report_html": args.report_html
        }
    })
    csv_files = report.get("csv_files", [])
    report["csv_files_count"] = len(csv_files)
    report["csv_points"] = sum(f.get("points", 0) for f in csv_files)
    report["csv_skipped_values"] = sum(f.get("skipped_values", 0) for f in csv_files)
    report["csv_rows"] = sum(f.get("rows", 0) for f in csv_files)
    warnings = []
    for csv in csv_files:
        path = csv.get("path", "")
        if csv.get("rows", 0) > 1 and csv.get("points", 0) == 0:
            warnings.append(f"CSV {path}: 0 points parsed (check format/quotes).")
        if csv.get("skipped_values", 0) > 0:
            warnings.append(f"CSV {path}: skipped values {csv.get('skipped_values', 0)}.")
        for err in csv.get("errors", []):
            warnings.append(f"CSV {path}: {err}")
    report["warnings"] = warnings

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=True, indent=2)

    os.makedirs(os.path.dirname(args.report_html), exist_ok=True)
    new_section = render_section(report, conflicts)
    existing_sections = []
    if os.path.exists(args.report_html):
        try:
            with open(args.report_html, "r", encoding="utf-8") as f:
                existing_html = f.read()
        except Exception:
            existing_html, _enc = read_text_guess(args.report_html)
        existing_sections = extract_sections(existing_html)
        if existing_sections:
            existing_sections = normalize_sections(existing_sections)
        else:
            legacy = legacy_section_from_html(existing_html)
            if legacy:
                existing_sections = [legacy]

    page = render_report_page("\n".join([new_section] + existing_sections))
    with open(args.report_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Summary: habits={report.get('habits', 0)} | input_points={report.get('input_points', 0)} | kept_points={report.get('kept_points', 0)} | conflicts={report.get('conflicts', 0)}")
    print(f"Sources: db_files={len(db_paths)} | csv_files={len(csv_paths)} | csv_points={report.get('csv_points', 0)} | csv_skipped_values={report.get('csv_skipped_values', 0)}")

    for w in report.get("warnings", []):
        print(f"[WARN] {w}", file=sys.stderr)

    if conflicts:
        print(f"Conflicts detected: {len(conflicts)}", file=sys.stderr)
        for c in conflicts[:10]:
            print(f"[WARN] {c['habit']} {c['date']} existing={c['existing']} incoming={c['incoming']}", file=sys.stderr)
    else:
        print("No conflicts detected.")

    print(f"Wrote: {args.out}")
    print(f"Wrote: {args.js}")
    print(f"Wrote: {args.conflicts}")
    print(f"Wrote: {args.report}")
    print(f"Wrote: {args.report_html}")


if __name__ == "__main__":
    main()
