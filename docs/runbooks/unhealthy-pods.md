# Unhealthy pods

**Fires:** Prometheus `PodRestartingRepeatedly` (a process restarted more than 3 times in 10 minutes) or `TargetDown`
(Prometheus cannot scrape a process for 2 minutes). Also where [outbox-lag](outbox-lag.md),
[stuck-queue](stuck-queue.md) and [failed-deployment](failed-deployment.md) send you when a pod is the cause.

## Check

1. Run the **`cluster-capacity`** workflow. Read, in order:
   - "Pods that are not Ready, or have restarted": the pod, its phase, how many restarts, and the last reason
     (`OOMKilled`, `Error`, `CrashLoopBackOff`, `ImagePullBackOff`).
   - "Warning events, newest last": probe failures, failed scheduling, image pull errors.
   - "Pods against the limit" and "Requested against allocatable": a Pending pod with "Insufficient" in the events means
     the nodes are full (2 nodes, 58 pods, about 3.8 vCPU).
2. Read the process's own log: Logs Insights on `/aws/containerinsights/loria-retail-dev/application`, filter
   `kubernetes.pod_name like /<release name>/`. A crash loop ends in a traceback or a configuration error.

## Likely causes

| You see | Cause | Do |
| --- | --- | --- |
| `OOMKilled` | A memory limit is too low for the process | Raise the limit in the release's values and redeploy |
| `ImagePullBackOff` | The tag is not in ECR, or a registry limit (Docker Hub, Quay) for the monitoring pods | Run `app-prepare`'s `verify`; redeploy a tag that exists; for Prometheus or Grafana, wait and retry |
| Pending, "Insufficient cpu/pods" | The nodes are full | Free capacity, or raise `node_desired_size` and `platform-create` |
| Restarts, probe `/health/ready` failing, logs name PostgreSQL or DynamoDB | A dependency is down | [database-connectivity](database-connectivity.md); readiness is what removes a pod from rotation |
| Restarts started with a deploy | The new release is bad | `app-rollback` for that release |
| `TargetDown` only, pod looks fine | Prometheus cannot reach it | Check the monitoring pods are Ready (same table); it is not the application |

Liveness checks nothing external, so a restart loop means the process itself is failing, not that a dependency is down.

## Recovered when

The pod is Ready with no new restarts for 10 minutes and the alert resolves.
