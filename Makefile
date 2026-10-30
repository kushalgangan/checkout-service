# checkout-service -- deploy / break / restore on a local colima cluster.
# See README.md for usage.

SHELL := /bin/bash

NAMESPACE    ?= checkout
DEPLOYMENT   ?= checkout-service
KUBE_CONTEXT ?= colima
OOM_LIMIT    ?= 32Mi

KUBECTL := kubectl --context $(KUBE_CONTEXT)

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
	      /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: deploy
deploy: ## Apply namespace, ConfigMap, Deployment, Service (healthy 64Mi limit).
	$(KUBECTL) apply -k .
	$(KUBECTL) -n $(NAMESPACE) rollout status deploy/$(DEPLOYMENT) --timeout=120s

.PHONY: oom
oom: ## Drop the memory limit to $(OOM_LIMIT) so the pod gets OOMKilled.
	$(KUBECTL) -n $(NAMESPACE) set resources deploy/$(DEPLOYMENT) --limits=memory=$(OOM_LIMIT) --requests=memory=$(OOM_LIMIT)
	@echo "Watch it crash-loop: make status"

.PHONY: restore
restore: deploy ## Re-apply the manifests to restore the healthy limit.

.PHONY: status
status: ## Show pods, restart counts, and last termination reason.
	@$(KUBECTL) -n $(NAMESPACE) get pods -l app=$(DEPLOYMENT) \
		-o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,LIMIT:.spec.containers[0].resources.limits.memory,LAST_STATE:.status.containerStatuses[0].lastState.terminated.reason'

.PHONY: logs
logs: ## Tail service logs.
	$(KUBECTL) -n $(NAMESPACE) logs -f deploy/$(DEPLOYMENT)

.PHONY: port-forward
port-forward: ## Forward the service to localhost:8080.
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/$(DEPLOYMENT) 8080:80

.PHONY: delete
delete: ## Remove everything, including the namespace.
	$(KUBECTL) delete -k .
