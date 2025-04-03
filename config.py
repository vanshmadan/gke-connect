import os
from dotenv import load_dotenv

load_dotenv()  # Loads .env variables

class Config:
    DEBUG = True
    UPLOAD_FOLDER = "./saved_configs"

    # Cluster DB
    CLUSTER_DB_CONFIG = {
        "user": os.getenv("CLUSTER_DB_USER"),
        "password": os.getenv("CLUSTER_DB_PASSWORD"),
        "database": os.getenv("CLUSTER_DB_NAME"),
        "host": os.getenv("CLUSTER_DB_HOST", "localhost"),
        "port": int(os.getenv("CLUSTER_DB_PORT", 5432)),
    }

    # Environment DB
    ENVIRONMENT_DB_CONFIG = {
        "user": os.getenv("ENVIRONMENT_DB_USER"),
        "password": os.getenv("ENVIRONMENT_DB_PASSWORD"),
        "database": os.getenv("ENVIRONMENT_DB_NAME"),
        "host": os.getenv("ENVIRONMENT_DB_HOST", "localhost"),
        "port": int(os.getenv("ENVIRONMENT_DB_PORT", 5432)),
    }

    CLUSTER_URL = os.getenv("CLUSTER_URL", "")