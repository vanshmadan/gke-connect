# auth_loader.py

import os
from kubernetes import config, client
import asyncpg
from config import Config

async def get_cluster_auth(env_name):
    conn = await asyncpg.connect(**Config.CLUSTER_DB_CONFIG)
    row = await conn.fetchrow(
        "SELECT cluster_url, auth_method FROM clusters WHERE env_name = $1",
        env_name
    )
    await conn.close()
    return row

async def load_k8s_auth(env_name):
    row = await get_cluster_auth(env_name)
    if not row:
        raise Exception("Cluster auth not found for this environment")

    auth_method = row["auth_method"]
    cluster_url = row["cluster_url"]

    if auth_method == "kubeconfig":
        kubeconfig_path = os.path.join(Config.UPLOAD_FOLDER, "uploaded_kubeconfig.yaml")
        config.load_kube_config(config_file=kubeconfig_path)
    elif auth_method == "token":
        token_path = os.path.join(Config.UPLOAD_FOLDER, f"{env_name}_token.txt")
        if not os.path.exists(token_path):
            raise Exception("Token file not found")

        with open(token_path, "r") as f:
            token = f.read().strip()

        kube_config = client.Configuration()
        kube_config.host = cluster_url
        kube_config.verify_ssl = False
        kube_config.api_key = {"authorization": f"Bearer {token}"}
        client.Configuration.set_default(kube_config)
    else:
        raise Exception(f"Unsupported auth method: {auth_method}")