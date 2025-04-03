from sentence_transformers import SentenceTransformer, util

TYPE_EXAMPLES = {
    "API": ["auth-service", "api-gateway", "user-api"],
    "DB": ["postgres", "mysql", "mongo-db"],
    "Cache": ["redis", "memcached"],
    "Frontend": ["react-ui", "web-frontend", "nextjs-ui"],
    "Worker": ["cronjob-runner", "job-processor", "queue-worker"],
    "Proxy": ["nginx", "haproxy", "reverse-proxy"]
}

VALID_TYPES = list(TYPE_EXAMPLES.keys())

embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

example_texts = [(t, name) for t, names in TYPE_EXAMPLES.items() for name in names]
example_embeddings = [(t, embedding_model.encode(name)) for t, name in example_texts]

def embed_classify(name, image=None):
    try:
        query = name
        if image:
            query += f" {image}"
        query_embedding = embedding_model.encode(query)

        best_score = -1
        best_type = "Unknown"
        for t, emb in example_embeddings:
            score = util.cos_sim(query_embedding, emb).item()
            if score > best_score:
                best_score = score
                best_type = t

        return best_type
    except Exception as e:
        print("[Embedding Classification Error]", e)
        return "Unknown"