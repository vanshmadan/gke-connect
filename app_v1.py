from quart import Quart, request, jsonify
from quart_cors import cors
import asyncio
import asyncpg
import os
from kubernetes import client, config
from dotenv import load_dotenv
from save_config import save_yaml_to_gcs  # 👈 Import the helper function

# Load environment variables
load_dotenv()

app = Quart(__name__)
app = cors(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database config
DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}

async def get_db_connection():
    return await asyncpg.connect(**DB_CONFIG)

@app.route("/api/connect-gke", methods=["POST"])
async def connect_gke():
    form = await request.form
    upload_type = form.get("upload_type")
    env_name = form.get("env_name")
    cluster_url = form.get("cluster_url") or os.getenv("CLUSTER_URL")

    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    if not cluster_url:
        await save_cluster_state(env_name, "UNKNOWN", "token", True)
        return jsonify({"message": "Cluster state saved with UNKNOWN URL"}), 200

    try:
        if upload_type == "token":
            return await connect_via_token(env_name, cluster_url)
        elif upload_type == "kubeconfig":
            return await connect_via_kubeconfig(env_name)
        else:
            return jsonify({"error": "Invalid authentication method"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

async def connect_via_kubeconfig(env_name):
    files = await request.files
    if "file" not in files:
        return jsonify({"error": "No kubeconfig file provided"}), 400

    kube_file = files["file"]
    kube_path = os.path.join(UPLOAD_FOLDER, "uploaded_kubeconfig.yaml")
    await kube_file.save(kube_path)

    try:
        config.load_kube_config(kube_path)
        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", True)
        return jsonify({"message": "Kubeconfig loaded successfully"}), 200
    except Exception as e:
        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", False)
        return jsonify({"error": str(e)}), 500

async def connect_via_token(env_name, cluster_url):
    form = await request.form
    token = form.get("token")

    if not token:
        return jsonify({"error": "Token is required"}), 400

    kube_config = client.Configuration()
    kube_config.host = cluster_url
    kube_config.verify_ssl = False
    kube_config.api_key = {"authorization": f"Bearer {token}"}
    client.Configuration.set_default(kube_config)

    try:
        v1 = client.CoreV1Api()
        v1.list_namespace()
        await save_cluster_state(env_name, cluster_url, "token", True)
        return jsonify({"message": "Token authentication set"}), 200
    except Exception as e:
        await save_cluster_state(env_name, cluster_url, "token", False)
        return jsonify({"error": str(e)}), 500

async def save_cluster_state(env_name, cluster_url, auth_method, is_connected):
    try:
        conn = await get_db_connection()
        await conn.execute(
            """
            INSERT INTO clusters (env_name, cluster_url, auth_method, is_connected, last_checked)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (env_name) 
            DO UPDATE SET is_connected = EXCLUDED.is_connected, last_checked = NOW();
            """,
            env_name, cluster_url, auth_method, is_connected
        )
        await conn.close()
    except Exception as e:
        print(f"❌ Error saving cluster state for {env_name}: {e}")

@app.route("/api/check-connection", methods=["GET"])
async def check_cluster_connection():
    env_name = request.args.get("env_name")

    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    try:
        conn = await get_db_connection()
        result = await conn.fetchrow(
            "SELECT is_connected FROM clusters WHERE env_name = $1", env_name
        )
        await conn.close()

        if result:
            return jsonify({"env": env_name, "connected": result["is_connected"]}), 200
        else:
            return jsonify({"env": env_name, "connected": False}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ New endpoint to save YAML to GCS
@app.route("/api/save-yaml", methods=["POST"])
async def save_yaml():
    try:
        data = await request.get_json()
        env_name = data.get("envName")
        filename = data.get("configFileName")
        yaml_content = data.get("yamlContent")

        if not all([env_name, filename, yaml_content]):
            return jsonify({"error": "Missing fields"}), 400

        bucket_name = os.getenv("GCS_BUCKET_NAME")
        if not bucket_name:
            return jsonify({"error": "GCS_BUCKET_NAME not set"}), 500

        gcs_path = save_yaml_to_gcs(bucket_name, env_name, filename, yaml_content)
        return jsonify({"message": f"YAML saved to {gcs_path}"}), 200

    except Exception as e:
        print(f"❌ Error saving YAML to GCS: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
