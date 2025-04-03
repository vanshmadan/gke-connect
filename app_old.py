from flask_cors import CORS
from flask import Flask, request, jsonify
import kubernetes
from kubernetes import client, config
import os

app = Flask(__name__)
CORS(app)  # 🔥 Enable CORS for all routes
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/api/connect-gke", methods=["POST"])
def connect_gke():
    """Handles kubeconfig or token authentication."""
    upload_type = request.form.get("upload_type")
    
    if upload_type == "kubeconfig":
        return connect_via_kubeconfig()
    elif upload_type == "token":
        return connect_via_token()
    else:
        return jsonify({"error": "Invalid authentication method"}), 400

def connect_via_kubeconfig():
    """Handles kubeconfig authentication."""
    if "file" not in request.files:
        return jsonify({"error": "No kubeconfig file provided"}), 400
    
    kube_file = request.files["file"]
    kube_path = os.path.join(UPLOAD_FOLDER, "kubeconfig.yaml")
    kube_file.save(kube_path)

    try:
        config.load_kube_config(kube_path)
        return jsonify({"message": "Kubeconfig loaded successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def connect_via_token():
    """Handles token authentication."""
    token = request.form.get("token")
    cluster_url = request.form.get("cluster_url")

    if not token or not cluster_url:
        return jsonify({"error": "Token and Cluster URL are required"}), 400

    kube_config = client.Configuration()
    kube_config.host = cluster_url
    kube_config.verify_ssl = False  # Disable SSL verification (if needed)
    kube_config.api_key = {"authorization": f"Bearer {token}"}

    client.Configuration.set_default(kube_config)

    return jsonify({"message": "Token authentication set"}), 200

@app.route("/api/check-connection", methods=["POST"])
def check_cluster_connection():
    """Checks if Kubernetes API is accessible."""
    try:
        v1 = client.CoreV1Api()
        v1.list_node()
        return jsonify({"status": "success", "message": "Cluster is reachable"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)
