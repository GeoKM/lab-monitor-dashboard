#!/usr/bin/env python3
"""
Lab Monitor Dashboard - FastAPI Server
Serves static files and exposes an API for lab monitoring snapshots and alerts.
"""
import os
import json
import glob
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Paths
SNAPSHOT_ROOT = Path.home() / "lab-docs" / "monitoring" / "snapshots"
SNAPSHOT_ROOT_AIX = Path.home() / "lab-docs" / "monitoring" / "snapshots-aix"
ALERT_ROOT = Path.home() / "lab-docs" / "monitoring" / "alerts"
STATIC_DIR = Path(__file__).parent / "static"
HOSTS_FILE = Path.home() / "lab-docs" / "monitoring" / "hosts.d" / "hosts.yaml"
HOSTS_FILE_AIX = Path.home() / "lab-docs" / "monitoring" / "aix-hosts.d" / "hosts.yaml"

app = FastAPI(title="Lab Monitor Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── helpers ──────────────────────────────────────────────────────────────────

def snapshot_files(hostname: str, root: Path = SNAPSHOT_ROOT) -> list[str]:
    pattern = root / hostname / f"{hostname}-*.json"
    files = glob.glob(str(pattern))
    return sorted(files, key=lambda p: Path(p).stat().st_mtime, reverse=True)


def load_snapshot(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def latest_snapshot(hostname: str, root: Path = SNAPSHOT_ROOT) -> Optional[dict]:
    """Return the most recent snapshot JSON for a given hostname."""
    for path in snapshot_files(hostname, root):
        snap = load_snapshot(path)
        if snap is not None:
            return snap
    return None


def latest_successful_snapshot(hostname: str, root: Path = SNAPSHOT_ROOT) -> Optional[dict]:
    """Return the most recent non-unavailable snapshot for a given hostname."""
    for path in snapshot_files(hostname, root):
        snap = load_snapshot(path)
        if snap and not snap.get("unavailable"):
            return snap
    return None


def read_alerts(hostname: str) -> list[dict]:
    """Read today's alert log for a hostname. Returns list of alert entries."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alert_file = ALERT_ROOT / f"{hostname}-{today}.log"
    alerts = []
    if not alert_file.exists():
        # Try yesterday
        yesterday = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) -
                     __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
        alert_file = ALERT_ROOT / f"{hostname}-{yesterday}.log"
    if alert_file.exists():
        for line in alert_file.read_text().splitlines():
            if "[CRITICAL]" in line:
                alerts.append({"level": "CRITICAL", "message": line.strip()})
            elif "[ALERT]" in line:
                alerts.append({"level": "ALERT", "message": line.strip()})
    return alerts


def host_status(snapshot: Optional[dict], alerts: list[dict]) -> str:
    """Determine host status: green, orange, or red."""
    if snapshot and snapshot.get("_summary_severity"):
        sev = str(snapshot.get("_summary_severity", "OK")).upper()
        return {"CRITICAL": "red", "WARNING": "orange", "OK": "green"}.get(sev, "green")
    if any(a["level"] == "CRITICAL" for a in alerts):
        return "red"
    if alerts:
        return "orange"
    return "green"


def format_bytes(b: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def uptime_str(seconds: int) -> str:
    """Format uptime seconds as human-readable string."""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) or "<1m"


# ── API endpoints ────────────────────────────────────────────────────────────

@app.get("/api/hosts")
def list_hosts():
    """
    Returns summary of all known hosts with their latest snapshot and alert status.
    Includes both Linux and AIX hosts.
    """
    hostnames = []

    if HOSTS_FILE.exists():
        import yaml
        with open(HOSTS_FILE) as f:
            data = yaml.safe_load(f)
            hostnames += [h["name"] for h in data.get("hosts", [])]

    if HOSTS_FILE_AIX.exists():
        import yaml
        with open(HOSTS_FILE_AIX) as f:
            data = yaml.safe_load(f)
            hostnames += [h["name"] for h in data.get("hosts", [])]

    result = []
    for hostname in hostnames:
        # Try Linux snapshot root first, then AIX
        latest = latest_snapshot(hostname, SNAPSHOT_ROOT)
        snap_root = SNAPSHOT_ROOT
        if not latest:
            latest = latest_snapshot(hostname, SNAPSHOT_ROOT_AIX)
            snap_root = SNAPSHOT_ROOT_AIX

        display_snapshot = latest_successful_snapshot(hostname, snap_root) if latest and latest.get("unavailable") else latest
        alerts = read_alerts(hostname)
        if display_snapshot and display_snapshot.get("_alerts"):
            alerts = [
                {"level": "CRITICAL" if a.get("severity") == "critical" else "ALERT",
                 "message": f"[{a.get('severity','').upper()}] {a.get('metric')} = {a.get('value')}"}
                for a in display_snapshot.get("_alerts", [])
            ]
        status = host_status(display_snapshot, alerts)

        entry = {
            "hostname": hostname,
            "status": status,
            "alerts": alerts,
            "unavailable": bool(latest and latest.get("unavailable")),
            "unavailable_checked_at": latest.get("unavailable_checked_at") if latest else None,
            "error": latest.get("error") if latest else None,
            "last_known_status": latest.get("last_known_status") if latest else None,
        }
        if display_snapshot:
            entry.update({
                "timestamp": display_snapshot.get("timestamp"),
                "kernel": display_snapshot.get("kernel"),
                "uptime_seconds": display_snapshot.get("uptime_s") or display_snapshot.get("uptime_seconds"),
                "load_1m": display_snapshot.get("load", {}).get("1m"),
                "cpu_idle": display_snapshot.get("cpu", {}).get("idle_pct"),
                "mem_total": display_snapshot.get("memory", {}).get("total_kb", 0) * 1024 or display_snapshot.get("memory", {}).get("total"),
                "mem_available": display_snapshot.get("memory", {}).get("free_kb", 0) * 1024 or display_snapshot.get("memory", {}).get("available"),
                "disk_count": len(display_snapshot.get("disk", [])) or len(display_snapshot.get("filesystems", [])),
            })
            # Normalise memory object keys so memBar() works (expects total/available, gets total_kb/free_kb from AIX)
            mem = display_snapshot.get("memory", {})
            if "total" not in mem and "total_kb" in mem:
                entry["memory"] = {
                    "total": mem["total_kb"] * 1024,
                    "available": mem["free_kb"] * 1024,
                    "used": (mem["total_kb"] - mem["free_kb"]) * 1024 if "used_kb" not in mem else mem["used_kb"] * 1024,
                }
            result.append(entry)

    return result


@app.get("/api/hosts/{hostname}")
def host_detail(hostname: str):
    """Return full snapshot and alert data for a specific host."""
    latest = latest_snapshot(hostname, SNAPSHOT_ROOT)
    snap_root = SNAPSHOT_ROOT
    if not latest:
        latest = latest_snapshot(hostname, SNAPSHOT_ROOT_AIX)
        snap_root = SNAPSHOT_ROOT_AIX

    if not latest:
        raise HTTPException(status_code=404, detail=f"No snapshot found for {hostname}")

    snapshot = latest_successful_snapshot(hostname, snap_root) if latest.get("unavailable") else latest
    alerts = read_alerts(hostname)
    if snapshot and snapshot.get("_alerts"):
        alerts = [
            {"level": "CRITICAL" if a.get("severity") == "critical" else "ALERT",
             "message": f"[{a.get('severity','').upper()}] {a.get('metric')} = {a.get('value')}"}
            for a in snapshot.get("_alerts", [])
        ]
    status = host_status(snapshot, alerts)

    # ---- Normalise AIX snapshot fields to match frontend expectations ----
    # AIX uses `summary_severity`, frontend expects `_summary_severity`
    if "summary_severity" in snapshot and "_summary_severity" not in snapshot:
        snapshot["_summary_severity"] = snapshot.pop("summary_severity")

    # Memory: total_kb/free_kb -> total/available in bytes
    mem = snapshot.get("memory", {})
    if "total" not in mem and "total_kb" in mem:
        snapshot["memory"] = {
            "total": mem["total_kb"] * 1024,
            "available": mem["free_kb"] * 1024,
            "used": (mem["total_kb"] - mem["free_kb"]) * 1024,
        }

    # Swap: compute from paging spaces if not present
    if "swap" not in snapshot or not snapshot["swap"]:
        paging = snapshot.get("paging", [])
        swap_total = 0
        swap_used = 0
        for ps in paging:
            if ps.get("size_mb", 0) > 0:
                swap_total += ps["size_mb"] * 1024 * 1024
                swap_used += int(ps["size_mb"] * 1024 * 1024 * ps.get("used_pct", 0) / 100)
        if "memory" not in snapshot:
            snapshot["memory"] = {}
        snapshot["memory"]["swap_total"] = swap_total
        snapshot["memory"]["swap_used"] = swap_used

    # Filesystems: normalise filesystems -> disk with total/used/avail/use_pct (AIX uses total_kb/used_kb/free_kb/use_pct)
    if "disk" not in snapshot and "filesystems" in snapshot:
        snapshot["disk"] = [
            {
                "total": fs["total_kb"] * 1024,
                "used": fs["used_kb"] * 1024,
                "avail": fs["free_kb"] * 1024,
                "use_pct": float(fs["use_pct"]),
                "mount": fs.get("mount", ""),
            }
            for fs in snapshot.get("filesystems", [])
        ]

    return {
        "hostname": hostname,
        "status": status,
        "alerts": alerts,
        "snapshot": snapshot,
        "unavailable": bool(latest.get("unavailable")),
        "unavailable_checked_at": latest.get("unavailable_checked_at"),
        "error": latest.get("error"),
        "last_known_status": latest.get("last_known_status"),
    }


@app.get("/api/refresh")
def refresh():
    """Trigger a monitoring run. Runs collect + parse for all hosts."""
    import subprocess
    monitor_script = Path.home() / "lab-docs" / "monitoring" / "scripts" / "run-monitor.sh"
    if monitor_script.exists():
        result = subprocess.run(
            ["bash", str(monitor_script), "--all"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {"ok": True, "output": result.stdout[-500:] if result.stdout else ""}
    raise HTTPException(status_code=500, detail="Monitor script not found")


# ── static files ─────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)