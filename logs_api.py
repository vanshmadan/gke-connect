from kubernetes import config, client
from auth_loader import load_k8s_auth
from quart import Blueprint, request, jsonify

logs_api = Blueprint("logs_api", __name__)

@logs_api.route("/api/logs", methods=["GET"])
async def get_filtered_logs():
    env_name = request.args.get("env_name")
    controller_name = request.args.get("controller_name")

    if not env_name or not controller_name:
        return jsonify({"error": "Missing env_name or controller_name"}), 400

    try:
        await load_k8s_auth(env_name)
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        batch_v1 = client.BatchV1Api()

        pods = core_v1.list_namespaced_pod(namespace=env_name)
        matching_pods = []

        for pod in pods.items:
            owner_refs = pod.metadata.owner_references
            if owner_refs:
                for ref in owner_refs:
                    if ref.name == controller_name and ref.kind in ["Deployment", "StatefulSet", "ReplicaSet", "CronJob"]:
                        matching_pods.append(pod.metadata.name)

        if not matching_pods:
            return jsonify({"message": f"No pods found for {controller_name}"}), 404

        all_logs = []

        for pod_name in matching_pods:
            try:
                log = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=env_name,
                    tail_lines=100,
                    timestamps=True
                )
                log_block = f"\n◆ Deployment Pod: {pod_name}\n" + log
                all_logs.append(log_block)
            except Exception as e:
                all_logs.append(f"\n❌ Failed to get logs from {pod_name}: {str(e)}")

        return "\n\n".join(all_logs)

    except client.exceptions.ApiException as e:
        return jsonify({"error": e.reason, "details": e.body}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500