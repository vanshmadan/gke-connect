from quart import Blueprint, request, jsonify, websocket
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
import traceback
import json

resource_api = Blueprint('resource_api', __name__)

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

        # --- Services ---
        services = core_v1.list_namespaced_service(env_name)
        print(f"[DEBUG] Namespace: {env_name}")
        print(f"[DEBUG] Total services: {len(services.items)}")

        for svc in services.items:
            selector = svc.spec.selector or {}
            label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
            ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports or []]
            associated_resources = []

            print(f"[DEBUG] Service: {svc.metadata.name}, Selector: {selector}")

            if label_selector:
                print(f"[DEBUG] Fetching pods for selector: {label_selector}")
                pods = core_v1.list_namespaced_pod(env_name, label_selector=label_selector)
                print(f"[DEBUG] -> Found {len(pods.items)} matching pods")
                for pod in pods.items:
                    matched_pod_names.add(pod.metadata.name)
                    associated_resources.append({
                        "type": "Pod",
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat(),
                        "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    })

                deployments = apps_v1.list_namespaced_deployment(env_name, label_selector=label_selector)
                print(f"[DEBUG] -> Found {len(deployments.items)} matching deployments")
                for dep in deployments.items:
                    matched_deployment_names.add(dep.metadata.name)
                    associated_resources.append({
                        "type": "Deployment",
                        "name": dep.metadata.name,
                        "status": "Available" if dep.status.ready_replicas else "Pending",
                        "created_at": dep.metadata.creation_timestamp.isoformat(),
                        "pvcs": []
                    })

            resources.append({
                "type": "Service",
                "name": svc.metadata.name,
                "status": "Active",
                "created_at": svc.metadata.creation_timestamp.isoformat(),
                "pvcs": [],
                "cluster_ip": svc.spec.cluster_ip or "",
                "ports": ports,
                "associated": associated_resources
            })

        # --- Standalone Pods (not part of services) ---
        all_pods = core_v1.list_namespaced_pod(env_name).items
        for pod in all_pods:
            if pod.metadata.name not in matched_pod_names:
                resources.append({
                    "type": "Pod",
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "created_at": pod.metadata.creation_timestamp.isoformat(),
                    "pvcs": [vol.persistent_volume_claim.claim_name for vol in (pod.spec.volumes or []) if vol.persistent_volume_claim],
                    "cluster_ip": "",
                    "ports": [],
                    "associated": []
                })

        # --- Standalone Deployments (not part of services) ---
        all_deployments = apps_v1.list_namespaced_deployment(env_name).items
        for dep in all_deployments:
            if dep.metadata.name not in matched_deployment_names:
                resources.append({
                    "type": "Deployment",
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
        return jsonify({"error": str(e)}), 500

@resource_api.websocket("/ws/resources")
async def ws_resource_updates():
    env_name = websocket.args.get("env_name")
    if not env_name:
        await websocket.send(json.dumps({"error": "Missing env_name"}))
        return

    try:
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        w = watch.Watch()

        async def build_resources():
            resources = []
            services = core_v1.list_namespaced_service(env_name)

            for svc in services.items:
                selector = svc.spec.selector or {}
                label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
                ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports or []]
                associated = []

                if label_selector:
                    pods = core_v1.list_namespaced_pod(env_name, label_selector=label_selector)
                    for pod in pods.items:
                        associated.append({
                            "type": "Pod",
                            "name": pod.metadata.name,
                            "status": pod.status.phase,
                            "created_at": pod.metadata.creation_timestamp.isoformat(),
                            "pvcs": [
                                vol.persistent_volume_claim.claim_name
                                for vol in (pod.spec.volumes or [])
                                if vol.persistent_volume_claim
                            ],
                            "cluster_ip": "",
                            "ports": []
                        })

                    deployments = apps_v1.list_namespaced_deployment(env_name, label_selector=label_selector)
                    for dep in deployments.items:
                        associated.append({
                            "type": "Deployment",
                            "name": dep.metadata.name,
                            "status": "Available" if dep.status.ready_replicas else "Pending",
                            "created_at": dep.metadata.creation_timestamp.isoformat(),
                            "pvcs": [],
                            "cluster_ip": "",
                            "ports": []
                        })

                resources.append({
                    "type": "Service",
                    "name": svc.metadata.name,
                    "status": "Active",
                    "created_at": svc.metadata.creation_timestamp.isoformat(),
                    "pvcs": [],
                    "cluster_ip": svc.spec.cluster_ip or "",
                    "ports": ports,
                    "associated": associated
                })

            return resources

        # Stream updates and send full rebuilt resource list on each pod event
        for event in w.stream(core_v1.list_namespaced_pod, namespace=env_name):
            updated = await build_resources()
            await websocket.send(json.dumps({
                "type": "update",
                "resources": updated
            }))

    except Exception as e:
        print("[WebSocket Error]", traceback.format_exc())
        await websocket.send(json.dumps({"error": str(e)}))
