from quart import Blueprint, jsonify
from kubernetes import client, config
import asyncpg
from config import Config

# Blueprint for delete environment
delete_environment = Blueprint("delete_environment", __name__)

# Helper DB connections
def get_cluster_db():
    return asyncpg.connect(**Config.CLUSTER_DB_CONFIG)

def get_environment_db():
    return asyncpg.connect(**Config.ENVIRONMENT_DB_CONFIG)

@delete_environment.route("/api/delete-namespace/<env_name>", methods=["DELETE"])
async def delete_environment_and_resources(env_name):
    try:
        # Load Kubernetes config
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        v1 = client.CoreV1Api()

        # Delete Namespace
        try:
            v1.delete_namespace(env_name)
            print(f"🗑️ Namespace '{env_name}' deletion initiated.")
        except client.exceptions.ApiException as e:
            if e.status != 404:
                return jsonify({"error": f"Failed to delete namespace: {str(e)}"}), 500
            else:
                print(f"⚠️ Namespace '{env_name}' not found, skipping deletion.")

        # Delete from clusters table
        try:
            conn = await get_cluster_db()
            await conn.execute("DELETE FROM clusters WHERE env_name = $1", env_name)
            await conn.close()
            print(f"🧹 Cluster record for '{env_name}' deleted.")
        except Exception as e:
            return jsonify({"error": f"Failed to delete cluster record: {str(e)}"}), 500

        # Delete from environments table
        try:
            conn = await get_environment_db()
            await conn.execute("DELETE FROM environments WHERE name = $1", env_name)
            await conn.close()
            print(f"✅ Environment '{env_name}' fully deleted.")
        except Exception as e:
            return jsonify({"error": f"Failed to delete environment record: {str(e)}"}), 500

        return jsonify({"message": f"Environment '{env_name}' deleted successfully."}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
