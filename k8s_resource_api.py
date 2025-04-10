from quart import Blueprint, request, jsonify, websocket
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from dotenv import load_dotenv
import traceback
import json
import re
import os

from embedding_utils import embed_classify  

load_dotenv()

resource_api = Blueprint('resource_api', __name__)

VALID_TYPES = ["API", "DB", "Cache", "Frontend", "Worker", "Proxy"]

async def ai_infer_service_type(name, ports, image=None):
    try:
        return embed_classify(name, image)
    except Exception as e:
        print("[Fallback Exception]", e)
        return guess_type_from_name(name)

def guess_type_from_name(name):
    name = name.lower()
    if any(word in name for word in ["api", "service", "auth", "gateway"]):
        return "API"
    elif any(word in name for word in ["db", "postgres", "mysql", "mongo"]):
        return "DB"
    elif any(word in name for word in ["cache", "redis", "memcached"]):
        return "Cache"
    elif any(word in name for word in ["front", "web", "ui"]):
        return "Frontend"
    elif any(word in name for word in ["worker", "job", "cron"]):
        return "Worker"
    return "Unknown"

@resource_api.route("/api/environment-resources", methods=["GET"])
async def get_environment_resources():
    env_name = request.args.get("env_name")

    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    try:
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        resources = []
        matched_pods = set()
        matched_deployments = set()
        matched_statefulsets = set()

        # Pre-fetch everything
        all_pods = core_v1.list_namespaced_pod(env_name).items
        all_deployments = apps_v1.list_namespaced_deployment(env_name).items
        all_statefulsets = apps_v1.list_namespaced_stateful_set(env_name).items

        pod_map = {pod.metadata.name: pod for pod in all_pods}

        # Helper: Get pods matching a label selector
        def match_pods(selector):
            if not selector:
                return []
            label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
            return core_v1.list_namespaced_pod(env_name, label_selector=label_selector).items

        # Services
        services = core_v1.list_namespaced_service(env_name).items
        for svc in services:
            selector = svc.spec.selector or {}
            ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports or []]
            associated = []

            # Match deployments
            deployments = apps_v1.list_namespaced_deployment(env_name, label_selector=",".join(f"{k}={v}" for k, v in selector.items())).items
            for dep in deployments:
                matched_deployments.add(dep.metadata.name)
                dep_pods = match_pods(dep.spec.selector.match_labels)
                for pod in dep_pods:
                    matched_pods.add(pod.metadata.name)

                associated.append({
                    "k8s_type": "Deployment",
                    "name": dep.metadata.name,
                    "status": "Available" if dep.status.ready_replicas else "Pending",
                    "created_at": dep.metadata.creation_timestamp.isoformat(),
                    "pvcs": [],
                    "associated": [{
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    } for pod in dep_pods]
                })

            # Match statefulsets
            statefulsets = apps_v1.list_namespaced_stateful_set(env_name, label_selector=",".join(f"{k}={v}" for k, v in selector.items())).items
            for sts in statefulsets:
                matched_statefulsets.add(sts.metadata.name)
                sts_pods = match_pods(sts.spec.selector.match_labels)
                for pod in sts_pods:
                    matched_pods.add(pod.metadata.name)

                associated.append({
                    "k8s_type": "StatefulSet",
                    "name": sts.metadata.name,
                    "status": "Available" if sts.status.ready_replicas else "Pending",
                    "created_at": sts.metadata.creation_timestamp.isoformat(),
                    "pvcs": [],
                    "associated": [{
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    } for pod in sts_pods]
                })

            # Match loose pods
            pods = match_pods(selector)
            for pod in pods:
                if pod.metadata.name not in matched_pods:
                    matched_pods.add(pod.metadata.name)
                    associated.append({
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    })

            service_type = await ai_infer_service_type(svc.metadata.name, ports)

            resources.append({
                "type": service_type,
                "k8s_type": "Service",
                "name": svc.metadata.name,
                "status": "Active",
                "created_at": svc.metadata.creation_timestamp.isoformat(),
                "pvcs": [],
                "cluster_ip": svc.spec.cluster_ip or "",
                "ports": ports,
                "associated": associated
            })

        # Unmatched Deployments
        for dep in all_deployments:
            if dep.metadata.name not in matched_deployments:
                dep_pods = match_pods(dep.spec.selector.match_labels)
                for pod in dep_pods:
                    matched_pods.add(pod.metadata.name)
                image = dep.spec.template.spec.containers[0].image if dep.spec.template.spec.containers else None
                dep_type = await ai_infer_service_type(dep.metadata.name, [], image)

                resources.append({
                    "type": dep_type,
                    "k8s_type": "Deployment",
                    "name": dep.metadata.name,
                    "status": "Available" if dep.status.ready_replicas else "Pending",
                    "created_at": dep.metadata.creation_timestamp.isoformat(),
                    "pvcs": [],
                    "cluster_ip": "",
                    "ports": [],
                    "associated": [{
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    } for pod in dep_pods]
                })

        # Unmatched StatefulSets
        for sts in all_statefulsets:
            if sts.metadata.name not in matched_statefulsets:
                sts_pods = match_pods(sts.spec.selector.match_labels)
                for pod in sts_pods:
                    matched_pods.add(pod.metadata.name)
                image = sts.spec.template.spec.containers[0].image if sts.spec.template.spec.containers else None
                sts_type = await ai_infer_service_type(sts.metadata.name, [], image)

                resources.append({
                    "type": sts_type,
                    "k8s_type": "StatefulSet",
                    "name": sts.metadata.name,
                    "status": "Available" if sts.status.ready_replicas else "Pending",
                    "created_at": sts.metadata.creation_timestamp.isoformat(),
                    "pvcs": [],
                    "cluster_ip": "",
                    "ports": [],
                    "associated": [{
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    } for pod in sts_pods]
                })

        # Unmatched Pods
        for pod in all_pods:
            if pod.metadata.name not in matched_pods:
                image = pod.spec.containers[0].image if pod.spec.containers else None
                pod_type = await ai_infer_service_type(pod.metadata.name, [], image)
                resources.append({
                    "type": pod_type,
                    "k8s_type": "Pod",
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "created_at": pod.metadata.creation_timestamp.isoformat(),
                    "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    "cluster_ip": "",
                    "ports": [],
                    "associated": []
                })

        return jsonify({"resources": resources})

    except ApiException as e:
        return jsonify({"error": f"Kubernetes API error: {e.reason}"}), 500
    except Exception as e:
        print("Exception:", traceback.format_exc())
        return jsonify({"error": str(e)})