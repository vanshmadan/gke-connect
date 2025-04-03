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
        matched_pod_names = set()
        matched_deployment_names = set()

        services = core_v1.list_namespaced_service(env_name)
        for svc in services.items:
            selector = svc.spec.selector or {}
            label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
            ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports or []]
            associated_resources = []

            if label_selector:
                pods = core_v1.list_namespaced_pod(env_name, label_selector=label_selector)
                for pod in pods.items:
                    matched_pod_names.add(pod.metadata.name)
                    associated_resources.append({
                        "k8s_type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    })

                deployments = apps_v1.list_namespaced_deployment(env_name, label_selector=label_selector)
                for dep in deployments.items:
                    matched_deployment_names.add(dep.metadata.name)
                    associated_resources.append({
                        "k8s_type": "Deployment",
                        "name": dep.metadata.name,
                        "status": "Available" if dep.status.ready_replicas else "Pending",
                        "created_at": dep.metadata.creation_timestamp.isoformat(),
                        "pvcs": []
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
                "associated": associated_resources
            })

        all_pods = core_v1.list_namespaced_pod(env_name).items
        for pod in all_pods:
            if pod.metadata.name not in matched_pod_names:
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

        all_deployments = apps_v1.list_namespaced_deployment(env_name).items
        for dep in all_deployments:
            if dep.metadata.name not in matched_deployment_names:
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
                    "associated": []
                })

        return jsonify({"resources": resources})

    except ApiException as e:
        return jsonify({"error": f"Kubernetes API error: {e.reason}"}), 500
    except Exception as e:
        print("Exception:", traceback.format_exc())
        return jsonify({"error": str(e)})