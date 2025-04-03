from google.cloud import storage
import os

def save_yaml_to_gcs(bucket_name, env_name, filename, yaml_content):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    blob_path = f"{env_name}/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(yaml_content, content_type="text/yaml")

    print(f"✅ Saved YAML to GCS: gs://{bucket_name}/{blob_path}")
    return f"gs://{bucket_name}/{blob_path}"
