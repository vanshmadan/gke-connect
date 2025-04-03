from kubernetes import client, config
from kubernetes.utils import create_from_yaml
import os

async def deploy_to_namespace(env_name: str, yaml_content: str):
    """
    Deploys Kubernetes objects to the namespace corresponding to the given environment.
    """
    try:
        # Load kubeconfig or in-cluster config
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        # Save the YAML to a temporary file
        temp_yaml_path = f"/tmp/{env_name}_deployment.yaml"
        with open(temp_yaml_path, "w") as f:
            f.write(yaml_content)

        # Deploy using Kubernetes utils
        k8s_client = client.ApiClient()
        created_objects = create_from_yaml(k8s_client, temp_yaml_path, namespace=env_name)

        os.remove(temp_yaml_path)  # Clean up the temp file
        messages = [
            f"📦 Deployment to {env_name}...",
            f"✅ Success: ✅ Deployed {len(created_objects)} objects to namespace '{env_name}'"
        ]
        return {"logs": messages}

    except Exception as e:
        return {"logs": [f"📦 Deployment to {env_name}...", f"❌ Error: {str(e)}"]}
