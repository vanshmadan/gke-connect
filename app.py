from quart import Quart, request, jsonify
from save_config import save_config_bp
from quart_cors import cors
import asyncio
import asyncpg
import os
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Quart(__name__)
app = cors(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database configuration from .env
DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}

async def get_db_connection():
    """Returns an async database connection."""
    return await asyncpg.connect(**DB_CONFIG)

@app.route("/api/connect-gke", methods=["POST"])
async def connect_gke():
    """Handles cluster authentication via kubeconfig or token."""
    form = await request.form
    upload_type = form.get("upload_type")
    env_name = form.get("env_name")
    cluster_url = form.get("cluster_url") or os.getenv("CLUSTER_URL")

    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    if not cluster_url:
        print(f"⚠️ No cluster_url provided. Marking {env_name} as connected.")

        namespace_created = await create_namespace(env_name)

        await save_cluster_state(env_name, "UNKNOWN", "token", namespace_created)
        return jsonify({"message": f"Cluster state saved, Namespace Created: {namespace_created}"}), 200

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
    """Handles kubeconfig authentication."""
    files = await request.files
    if "file" not in files:
        return jsonify({"error": "No kubeconfig file provided"}), 400

    kube_file = files["file"]
    kube_path = os.path.join(UPLOAD_FOLDER, "uploaded_kubeconfig.yaml")
    await kube_file.save(kube_path)

    try:
        config.load_kube_config(kube_path)

        namespace_created = await create_namespace(env_name)

        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", namespace_created)
        return jsonify({"message": "Kubeconfig loaded successfully", "namespace_created": namespace_created}), 200
    except Exception as e:
        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", False)
        return jsonify({"error": str(e)}), 500

async def connect_via_token(env_name, cluster_url):
    """Handles token authentication."""
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
        v1.list_namespace()  # Test connection

        namespace_created = await create_namespace(env_name)

        await save_cluster_state(env_name, cluster_url, "token", namespace_created)
        return jsonify({"message": "Token authentication set", "namespace_created": namespace_created}), 200
    except Exception as e:
        await save_cluster_state(env_name, cluster_url, "token", False)
        return jsonify({"error": str(e)}), 500

async def create_namespace(env_name):
    """Creates a namespace in the Kubernetes cluster."""
    try:
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        v1 = client.CoreV1Api()
        namespace_metadata = client.V1ObjectMeta(name=env_name)
        namespace_body = client.V1Namespace(metadata=namespace_metadata)

        v1.create_namespace(body=namespace_body)
        print(f"✅ Namespace '{env_name}' created successfully.")
        return True
    except ApiException as e:
        if e.status == 409:
            print(f"⚠️ Namespace '{env_name}' already exists.")
            return True
        else:
            return False

async def save_cluster_state(env_name, cluster_url, auth_method, is_connected):
    """Saves cluster connectivity state in PostgreSQL, including creation_date."""
    try:
        conn = await get_db_connection()
        await conn.execute(
            """
            INSERT INTO clusters (env_name, cluster_url, auth_method, is_connected, creation_date, last_checked)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            ON CONFLICT (env_name) 
            DO UPDATE SET 
                is_connected = EXCLUDED.is_connected, 
                last_checked = NOW();
            """,
            env_name, cluster_url, auth_method, is_connected
        )
        print(f"✅ Cluster state updated: {env_name}, is_connected={is_connected}")
        await conn.close()
    except Exception as e:
        print(f"❌ Error saving cluster state for {env_name}: {e}")

@app.route("/api/check-connection", methods=["GET"])
async def check_cluster_connection():
    """Returns cluster connection state from PostgreSQL."""
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

@app.route("/environments/<env_name>", methods=["GET"])
async def get_environment_details(env_name):
    """Fetch details for a specific environment."""
    try:
        conn = await get_db_connection()
        query = """
            SELECT env_name, creation_date, namespace, cluster_url 
            FROM clusters WHERE env_name = $1
        """
        row = await conn.fetchrow(query, env_name)
        await conn.close()

        if not row:
            return jsonify({"error": "Environment not found"}), 404

        return jsonify({
            "env_name": row["env_name"],
            "creation_date": row["creation_date"],
            "namespace": row["env_name"],
            "url": row["cluster_url"]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
