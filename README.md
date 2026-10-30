# checkout-service

A small Python checkout API used to demo memory-pressure incidents (OOMKilled) on
Kubernetes. On startup it grows to **~250 MB resident memory** to simulate a
warm product cache.

- **No Dockerfile.** It runs on the public `python:3.12-slim` image. `app/main.py` is
  mounted from a ConfigMap that kustomize generates.
- **Stdlib only.** Nothing to `pip install`.

```
checkout-service/
├── app/main.py            # the service
├── k8s/
│   ├── namespace.yaml     # namespace: checkout
│   ├── deployment.yaml    # resources, probes, ConfigMap mount
│   └── service.yaml       # ClusterIP :80 -> :8080
├── kustomization.yaml     # builds the ConfigMap from app/main.py
└── Makefile
```

## Endpoints

| Method | Path        | Description                                          |
|--------|-------------|------------------------------------------------------|
| POST   | `/checkout` | `{"items":[{"price":19.99,"qty":2}]}` → `201` order  |
| GET    | `/healthz`  | Liveness                                             |
| GET    | `/readyz`   | `503` until the cache warm-up finishes, then `200`   |
| GET    | `/metrics`  | Prometheus: orders, failed orders, resident memory   |

## Resources

| Setting              | Value  | Why                                                      |
|----------------------|--------|----------------------------------------------------------|
| `TARGET_MEMORY_MI`   | 240    | Process RSS target (~250 MB)                             |
| requests.memory      | 256Mi  | Matches the steady-state cgroup usage (~241–256Mi)       |
| limits.memory        | 320Mi  | Headroom. A 256Mi limit gets OOMKilled too               |
| requests/limits.cpu  | 100m / 500m |                                                     |

The cgroup counts page cache and kernel memory on top of the Python RSS. A
~250 MB process therefore needs a limit somewhat above 256Mi.

## Usage (local colima cluster)

```sh
make deploy        # healthy: 1/1 Running, ~241Mi used of 320Mi
make oom           # limit -> 128Mi: OOMKilled (exit 137), CrashLoopBackOff
make status        # restarts + last termination reason
make restore       # back to the healthy limit
make delete        # tear down
```

Try the API:

```sh
make port-forward
curl -XPOST localhost:8080/checkout -d '{"items":[{"price":19.99,"qty":2}]}'
```

Editing `app/main.py` and re-running `make deploy` rolls the pods. The
ConfigMap name carries a content hash.
