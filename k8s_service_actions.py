# k8s_service_actions.py

from quart import Blueprint, request, jsonify
from kubernetes import client
from auth_loader import load_k8s_auth
import datetime

service_actions = Blueprint("service_actions", __name__)


@service_actions.route("/api/service/start", methods=["POST"])
async def start_service():
    data = await request.get_json()
    env_name = data.get("envName")
    service_name = data.get("serviceName")

    if not env_name or not service_name:
        return jsonify({"error": "Missing envName or serviceName"}), 400

    try:
        await load_k8s_auth(env_name)  # Await this correctly
        apps_v1 = client.AppsV1Api()
        print(f"🚀 Scaling deployment {service_name} in namespace {env_name}")
        
        response = apps_v1.patch_namespaced_deployment_scale(
            name=service_name,
            namespace=env_name,
            body={"spec": {"replicas": 1}},
            _request_timeout=(5, 10)
        )

        return jsonify({"message": f"✅ {service_name} scaled to 1 in {env_name}", "response": str(response)})

    except Exception as e:
        print(f"❌ Kubernetes API error: {e}")
        return jsonify({"error": f"K8s API error: {e.reason}"}), 500
    except Exception as e:
        print(f"❌ Internal error: {e}")
        return jsonify({"error": str(e)}), 500



@service_actions.route("/api/service/stop", methods=["POST"])
async def stop_service():
    data = await request.get_json()
    env_name = data.get("envName")
    service_name = data.get("serviceName")

    if not env_name or not service_name:
        return jsonify({"error": "Missing envName or serviceName"}), 400

    try:
        await load_k8s_auth(env_name)
        apps_v1 = client.AppsV1Api()
        body = {"spec": {"replicas": 0}}
        apps_v1.patch_namespaced_deployment_scale(service_name, env_name, body)
        return jsonify({"message": f"🛑 {service_name} scaled to 0 in {env_name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@service_actions.route("/api/service/deploy", methods=["POST"])
async def redeploy_service():
    data = await request.get_json()
    env_name = data.get("envName")
    service_name = data.get("serviceName")

    if not env_name or not service_name:
        return jsonify({"error": "Missing envName or serviceName"}), 400

    try:
        await load_k8s_auth(env_name)
        apps_v1 = client.AppsV1Api()
        now = datetime.datetime.utcnow().isoformat("T") + "Z"

        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        apps_v1.patch_namespaced_deployment(service_name, env_name, body)
        return jsonify({"message": f"🔁 {service_name} re-deployed in {env_name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500