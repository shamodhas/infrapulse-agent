# agent/agent.py
import platform
import psutil
import requests
import os
import time
import threading
try:
    import docker
except ImportError:
    docker = None
from fastapi import FastAPI, Depends, HTTPException, Header
import uvicorn

app = FastAPI()

BACKEND_URL = os.environ.get(
    "BACKEND_URL", "https://infrapulse-backend.onrender.com/api/metrics")
AGENT_TOKEN = os.environ.get(
    "SECURE_TOKEN", "JPayZIfQHEmhaQzpDfhOld73Q7GFrcxdLwalPus88taEJqfTU3aeHO02gAOeayHf")
THRESHOLD_CPU = float(os.environ.get("THRESHOLD_CPU", 85.0))

docker_client = None
if docker:
    try:
        docker_client = docker.from_env()
    except Exception:
        docker_client = None


def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=403, detail="Unauthorized request to Agent")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer" or token != AGENT_TOKEN:
            raise HTTPException(
                status_code=403, detail="Unauthorized request to Agent")
    except Exception:
        raise HTTPException(
            status_code=403, detail="Invalid authorization header")
    return token


@app.get("/containers", dependencies=[Depends(verify_token)])
def list_containers():
    try:
        if docker_client:
            containers = []
            for c in docker_client.containers.list(all=True):
                containers.append({
                    "id": c.id,
                    "name": c.name,
                    "status": c.status
                })
            return containers
        else:
            processes = []
            for p in psutil.process_iter(['pid', 'name', 'status']):
                processes.append({
                    "id": str(p.info['pid']),
                    "name": p.info['name'],
                    "status": p.info['status'] or "running"
                })
            return processes[:20]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/containers/{container_id}/restart", dependencies=[Depends(verify_token)])
def restart_container(container_id: str):
    try:
        if docker_client:
            container = docker_client.containers.get(container_id)
            container.restart()
            return {"status": "success", "target": container_id, "action": "restarted"}
        else:
            return {"status": "success", "target": container_id, "action": "simulated_restart"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def collect_and_send_metrics():
    while True:
        try:
            sys_cpu = psutil.cpu_percent(interval=1)
            sys_mem = psutil.virtual_memory().percent

            container_metrics = []
            if docker_client:
                for c in docker_client.containers.list(all=True):
                    container_metrics.append({
                        "id": c.id,
                        "name": c.name,
                        "status": c.status
                    })

            payload = {
                "system": {"cpu": sys_cpu, "memory": sys_mem},
                "containers": container_metrics
            }

            headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
            requests.post(BACKEND_URL, json=payload,
                          headers=headers, timeout=5)
        except Exception:
            pass
        time.sleep(30)


@app.on_event("startup")
def startup_event():
    threading.Thread(target=collect_and_send_metrics, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
