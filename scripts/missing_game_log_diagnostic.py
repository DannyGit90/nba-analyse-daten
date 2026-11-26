#!/usr/bin/env python3
"""Read-only diagnostic: why completed schedule games are missing from local team logs."""
import datetime as dt
import json
from pathlib import Path

DATE_KEYS = ("game_date", "date", "game_date_utc", "game_date_est")


def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def latest_season(data_root):
    seasons = []
    for path in (data_root / "schedule").glob("season=*.jsonl"):
        try:
            seasons.append(int(path.stem.split("=", 1)[1]))
        except ValueError:
            continue
    return max(seasons) if seasons else None


def date_of(row):
    for key in DATE_KEYS:
        if row.get(key):
            return str(row[key])[:10]
    return None


def diagnose(data_root, ids, today_utc):
    season = latest_season(data_root)
    result = {"schema": "missing-game-log-diagnostic-v1", "season": season,
              "today_utc": today_utc, "games": [], "schedule_keys_seen": [],
              "completed_before_today_without_logs": []}
    if season is None:
        result["error"] = "no schedule file found"
        return result
    schedule = read_jsonl(data_root / "schedule" / f"season={season}.jsonl")
    logs = read_jsonl(data_root / "team_game_logs" / f"season={season}.jsonl")
    keys = sorted({k for row in schedule for k in row})
    result["schedule_keys_seen"] = keys
    log_ids = {str(r.get("game_id")) for r in logs}
    log_dates = {}
    for row in logs:
        log_dates.setdefault(date_of(row), set()).add(str(row.get("game_id")))
    sched_by_id = {}
    for row in schedule:
        sched_by_id.setdefault(str(row.get("game_id")), []).append(row)
    for gid in ids:
        rows = sched_by_id.get(str(gid), [])
        dates = sorted({d for d in (date_of(r) for r in rows) if d})
        same_day_sched = sorted({g for g, rs in sched_by_id.items()
                                 if any(date_of(r) in dates for r in rs)}) if dates else []
        result["games"].append({
            "game_id": str(gid),
            "in_schedule": bool(rows),
            "schedule_rows": rows[:4],
            "dates": dates,
            "log_rows": sum(1 for r in logs if str(r.get("game_id")) == str(gid)),
            "same_day_schedule_games": len(same_day_sched),
            "same_day_games_with_logs": sum(1 for g in same_day_sched if g in log_ids),
        })
    missing = sorted(g for g, rs in sched_by_id.items() if g not in log_ids
                     and any((date_of(r) or "9999") < today_utc for r in rs))
    result["completed_before_today_without_logs"] = missing[:60]
    result["completed_before_today_without_logs_count"] = len(missing)
    result["log_rows"] = len(logs)
    result["schedule_rows"] = len(schedule)
    return result


def render_md(result):
    lines = ["# Diagnose: fehlende Spiel-Logs", "",
             "Nur lesend. Keine Korrektur, Freigabe oder Modelländerung.", "",
             f"Saison: {result.get('season')}  |  Stand UTC-Tag: {result.get('today_utc')}",
             f"Zeilen Spielplan: {result.get('schedule_rows')}  |  Zeilen Team-Logs: {result.get('log_rows')}", ""]
    if result.get("error"):
        lines.append(f"Fehler: {result['error']}")
        return "\n".join(lines) + "\n"
    lines.append(f"Spielplan-Felder: {', '.join(result['schedule_keys_seen'])}")
    lines.append("")
    for g in result["games"]:
        lines.append(f"## {g['game_id']}")
        lines.append(f"Im Spielplan: {g['in_schedule']}  |  Datum: {', '.join(g['dates']) or 'unbekannt'}  |  Log-Zeilen: {g['log_rows']}")
        lines.append(f"Gleicher Tag: {g['same_day_schedule_games']} Spiele im Spielplan, davon {g['same_day_games_with_logs']} mit Logs")
        lines.append("<pre>" + json.dumps(g["schedule_rows"], ensure_ascii=False, indent=1) + "</pre>")
        lines.append("")
    lines.append(f"Vor dem UTC-Tag angesetzt, aber ohne Logs: {result['completed_before_today_without_logs_count']}")
    lines.append(", ".join(result["completed_before_today_without_logs"]))
    return "\n".join(lines) + "\n"


def main():
    root = Path(".")
    latest = json.loads((root / "reports" / "paper_latest.json").read_text(encoding="utf-8"))
    ids = [str(x) for x in latest.get("completed_schedule_games_missing_from_logs", [])]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    result = diagnose(root / "data" / "nba", ids, today)
    out = root / "reports" / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    (out / "missing_game_logs.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "missing_game_logs.md").write_text(render_md(result), encoding="utf-8")


if __name__ == "__main__":
    main()
