import os
import asyncio
from quart import Blueprint, request, jsonify
from google.cloud import storage
import asyncpg
from dotenv import load_dotenv
import datetime

# Load environment variables
load_dotenv()

# Blueprint for modularity
save_config_bp = Blueprint("save_config", __name__)

# GCS Configuration
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")  # Set this in your .env
storage_client = storage.Client()

# Database Configuration
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

async def upload_yaml_to_gcs(env_name, yaml_data):
    """Uploads YAML content to GCS and returns the file URL."""
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    
    # Generate unique filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    blob_name = f"{env_name}/config-{timestamp}.yaml"

    blob = bucket.blob(blob_name)
    blob.upload_from_string(yaml_data, content_type="application/x-yaml")

    gcs_url = f"gs://{GCS_BUCKET_NAME}/{blob_name}"
    print(f"✅ YAML uploaded to {gcs_url}")
    return gcs_url

async def save_yaml_reference(env_name, gcs_url):
    """Stores the YAML file reference in PostgreSQL."""
    try:
        conn = await get_db_connection()
        await conn.execute(
            """
            INSERT INTO yaml_configs (env_name, gcs_url, created_at)
            VALUES ($1, $2, NOW())
            """,
            env_name, gcs_url
        )
        print(f"✅ YAML reference saved for {env_name}")
        await conn.close()
    except Exception as e:
        print(f"❌ Error saving YAML reference: {e}")

@save_config_bp.route("/api/save-config", methods=["POST"])
async def save_configuration():
    """API to save YAML configuration to GCS and store its reference."""
    data = await request.json
    env_name = data.get("env_name")
    yaml_data = data.get("yaml_data")

    if not env_name or not yaml_data:
        return jsonify({"error": "Missing env_name or yaml_data"}), 400

    try:
        gcs_url = await upload_yaml_to_gcs(env_name, yaml_data)
        await save_yaml_reference(env_name, gcs_url)

        return jsonify({"message": "YAML saved successfully", "gcs_url": gcs_url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
