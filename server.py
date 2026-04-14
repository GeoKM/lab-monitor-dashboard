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
ALERT_ROOT = Path.home() / "lab-docs" / "monitoring" / "alerts"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Lab Monitor Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── helpers ──────────────────────────────────────────────────────────────────

def latest_snapshot(hostname: str) -> Optional[dict]:
    """Return the most recent snapshot JSON for a given hostname."""
    pattern = SNAPSHOT_ROOT / hostname / f"{hostname}-*.json"
    files = sorted(glob.glob(str(pattern)), reverse=True)
    if not files:
        return None
    try:
        with open(files[0]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
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
    """
    hosts_file = Path.home() / "lab-docs" / "monitoring" / "hosts.d" / "hosts.yaml"
    hostnames = []
    if hosts_file.exists():
        import yaml
        with open(hosts_file) as f:
            data = yaml.safe_load(f)
            hostnames = [h["name"] for h in data.get("hosts", [])]

    result = []
    for hostname in hostnames:
        snapshot = latest_snapshot(hostname)
        alerts = read_alerts(hostname)
        status = host_status(snapshot, alerts)

        entry = {
            "hostname": hostname,
            "status": status,
            "alerts": alerts,
        }
        if snapshot:
            entry.update({
                "timestamp": snapshot.get("timestamp"),
                "kernel": snapshot.get("kernel"),
                "uptime_seconds": snapshot.get("uptime_seconds"),
                "load_1m": snapshot.get("load", {}).get("1m"),
                "cpu_idle": snapshot.get("cpu", {}).get("idle_pct"),
                "mem_available": snapshot.get("memory", {}).get("available"),
                "mem_total": snapshot.get("memory", {}).get("total"),
                "disk_count": len(snapshot.get("disk", [])),
            })
        result.append(entry)

    return result


@app.get("/api/hosts/{hostname}")
def host_detail(hostname: str):
    """Return full snapshot and alert data for a specific host."""
    snapshot = latest_snapshot(hostname)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No snapshot found for {hostname}")

    alerts = read_alerts(hostname)
    status = host_status(snapshot, alerts)

    return {
        "hostname": hostname,
        "status": status,
        "alerts": alerts,
        "snapshot": snapshot,
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