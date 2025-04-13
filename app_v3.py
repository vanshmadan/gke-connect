from quart import Quart, request, jsonify
from quart_cors import cors
import asyncio
import asyncpg
import os
from kubernetes import client, config
from k8s_deploy_handler import deploy_to_namespace
from kubernetes.client.exceptions import ApiException
from config import Config
from k8s_resource_api import resource_api
from k8s_service_actions import service_actions
from logs_api import logs_api 
from  delete_namespace_route import delete_environment
from github_oauth import github_bp


os.environ["TOKENIZERS_PARALLELISM"] = "false"

app = Quart(__name__)
app = cors(app, allow_origin="http://localhost:3000", allow_credentials=True)

app.secret_key = os.getenv("SECRET_KEY", "change-me")  # Needed for session
app.register_blueprint(github_bp)
app.register_blueprint(resource_api)
app.register_blueprint(service_actions)
app.register_blueprint(delete_environment)

app.register_blueprint(logs_api)

# Database connections
def get_cluster_db():
    return asyncpg.connect(**Config.CLUSTER_DB_CONFIG)

def get_environment_db():
    return asyncpg.connect(**Config.ENVIRONMENT_DB_CONFIG)

# --- API ROUTES ---
@app.route("/api/connect-gke", methods=["POST"])
async def connect_gke():
    form = await request.form
    upload_type = form.get("upload_type")
    env_name = form.get("env_name")
    cluster_url = form.get("cluster_url") or Config.CLUSTER_URL

    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    try:
        if upload_type == "token":
            if not cluster_url:
                return jsonify({"error": "Cluster URL required for token auth"}), 400
            return await connect_via_token(env_name, cluster_url)
        elif upload_type == "kubeconfig":
            return await connect_via_kubeconfig(env_name)
        else:
            return jsonify({"error": "Invalid authentication method"}), 400
    except Exception as e:
        print("❌ connect-gke error:", e)
        return jsonify({"error": str(e)}), 500

async def connect_via_kubeconfig(env_name):
    files = await request.files
    if "file" not in files:
        return jsonify({"error": "No kubeconfig file provided"}), 400

    kube_file = files["file"]
    kube_path = os.path.join(Config.UPLOAD_FOLDER, "uploaded_kubeconfig.yaml")
    await kube_file.save(kube_path)

    try:
        config.load_kube_config(kube_path)
        contexts, active_context = config.list_kube_config_contexts()
        cluster_name = active_context["context"]["cluster"]

        namespace_created = await create_namespace(env_name)
        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", namespace_created, cluster_name)

        return jsonify({
            "message": "Kubeconfig loaded successfully",
            "namespace_created": namespace_created,
            "cluster_name": cluster_name
        }), 200
    except Exception as e:
        await save_cluster_state(env_name, "UNKNOWN", "kubeconfig", False, None)
        return jsonify({"error": str(e)}), 500


async def connect_via_token(env_name, cluster_url):
    form = await request.form
    token = form.get("token")

    if not token:
        return jsonify({"error": "Token is required"}), 400

    if not cluster_url:
        return jsonify({"error": "Cluster URL is required for token-based auth"}), 400

    kube_config = client.Configuration()
    kube_config.host = cluster_url
    kube_config.verify_ssl = False
    kube_config.api_key = {"authorization": f"Bearer {token}"}
    client.Configuration.set_default(kube_config)

    try:
        v1 = client.CoreV1Api()
        v1.list_namespace()

        cluster_name = cluster_url.split("/")[-1]
        namespace_created = await create_namespace(env_name)
        await save_cluster_state(env_name, cluster_url, "token", namespace_created, cluster_name)

        return jsonify({
            "message": "Token authentication set",
            "namespace_created": namespace_created,
            "cluster_name": cluster_name
        }), 200
    except Exception as e:
        await save_cluster_state(env_name, cluster_url, "token", False, None)
        return jsonify({"error": str(e)}), 500


async def create_namespace(env_name):
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
            print(f"❌ Namespace error: {e}")
            return False


async def save_cluster_state(env_name, cluster_url, auth_method, is_connected, cluster_name):
    try:
        conn = await get_cluster_db()
        await conn.execute(
            """
            INSERT INTO clusters (env_name, cluster_url, auth_method, is_connected, cluster_name, creation_date, last_checked)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            ON CONFLICT (env_name) DO UPDATE SET
                is_connected = EXCLUDED.is_connected,
                cluster_name = EXCLUDED.cluster_name,
                last_checked = NOW();
            """,
            env_name, cluster_url, auth_method, is_connected, cluster_name
        )
        await conn.close()
    except Exception as e:
        print(f"❌ Failed to save cluster state: {e}")


@app.route("/api/check-connection", methods=["GET"])
async def check_cluster_connection():
    env_name = request.args.get("env_name")
    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    try:
        conn = await get_cluster_db()
        row = await conn.fetchrow(
            "SELECT is_connected FROM clusters WHERE env_name = $1", env_name
        )
        await conn.close()

        return jsonify({
            "env": env_name,
            "connected": row["is_connected"] if row else False
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/environments/<env_name>", methods=["GET"])
async def get_environment_details(env_name):
    try:
        conn = await get_cluster_db()
        row = await conn.fetchrow(
            "SELECT env_name, creation_date, cluster_url FROM clusters WHERE env_name = $1",
            env_name
        )
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


@app.route("/api/cluster-details", methods=["GET"])
async def get_cluster_details():
    env_name = request.args.get("env_name")
    if not env_name:
        return jsonify({"error": "Environment name is required"}), 400

    try:
        conn = await get_cluster_db()
        row = await conn.fetchrow(
            "SELECT cluster_name FROM clusters WHERE env_name = $1", env_name
        )
        await conn.close()

        return jsonify({
            "cluster_name": row["cluster_name"] if row and row["cluster_name"] else "N/A"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save-yaml", methods=["POST"])
async def save_yaml_config():
    try:
        data = await request.get_json()
        env_name = data.get("envName")
        config_file_name = data.get("configFileName")
        yaml_content = data.get("yamlContent")
        metadata = data.get("metadata", [])

        if not env_name or not config_file_name:
            return jsonify({"error": "Missing required fields"}), 400

        if yaml_content:
            save_path = os.path.join(Config.UPLOAD_FOLDER, config_file_name)
            os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
            async with await asyncio.to_thread(open, save_path, "w") as f:
                await asyncio.to_thread(f.write, yaml_content)

        conn = await get_environment_db()
        insert_query = """
            INSERT INTO service_deployments (
                env_name, config_file_name, service_name, kind, user_name, customer_id
            ) VALUES ($1, $2, $3, $4, $5, $6)
        """
        for entry in metadata:
            await conn.execute(
                insert_query,
                env_name,
                config_file_name,
                entry.get("service_name"),
                entry.get("kind"),
                entry.get("user"),
                entry.get("customer_id")
            )
        await conn.close()

        return jsonify({"message": "YAML and metadata saved successfully"}), 200

    except Exception as e:
        print("❌ Exception in /api/save-yaml:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/deploy", methods=["POST"])
async def deploy_to_cluster():
    data = await request.get_json()
    env_name = data.get("envName")
    yaml_content = data.get("yamlContent")
    metadata = data.get("metadata", [])

    if not env_name or not yaml_content:
        return jsonify({"error": "envName and yamlContent are required"}), 400

    result = await deploy_to_namespace(env_name, yaml_content)

    if "error" in result:
        return jsonify(result), 500

    try:
        conn = await get_environment_db()
        insert_query = """
            INSERT INTO service_deployments (
                env_name, config_file_name, service_name, kind, user_name, customer_id
            ) VALUES ($1, $2, $3, $4, $5, $6)
        """

        config_file_name = f"deploy_{env_name}_{int(asyncio.get_event_loop().time())}.yaml"

        for entry in metadata:
            await conn.execute(
                insert_query,
                env_name,
                config_file_name,
                entry.get("service_name"),
                entry.get("kind"),
                entry.get("user"),
                entry.get("customer_id")
            )

        await conn.close()

    except Exception as e:
        print(f"❌ Failed to insert deployment metadata: {e}")

    return jsonify(result), 200


if __name__ == "__main__":
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=5001)
