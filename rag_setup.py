import json, os, glob
import chromadb
from sentence_transformers import SentenceTransformer

EMBED_MODEL = "all-MiniLM-L6-v2"
CHROMA_DIR  = "./chroma_db"

client     = chromadb.PersistentClient(path=CHROMA_DIR)
embedder   = SentenceTransformer(EMBED_MODEL)

def chunk_config(text, chunk_size=500):
    lines, chunks, current = text.split("\n"), [], []
    for line in lines:
        current.append(line)
        if len("\n".join(current)) >= chunk_size:
            chunks.append("\n".join(current))
            current = []
    if current:
        chunks.append("\n".join(current))
    return chunks

def rebuild_device(collection, device_file):
    with open(device_file) as f:
        data = json.load(f)

    device = data["device"]
    name   = device["name"]

    # Удаляем старые записи этого устройства
    existing = collection.get(where={"device": name})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        print(f"  [{name}] удалено {len(existing['ids'])} старых записей")

    docs, ids, metas = [], [], []

    docs.append(
        f"Device: {name}, role: {device['role']}, "
        f"platform: {device['platform']}, mgmt IP: {device['mgmt_ip']}"
    )
    ids.append(f"{name}_info")
    metas.append({"device": name, "type": "device_info"})

    for cmd, output in data.get("outputs", {}).items():
        for i, chunk in enumerate(chunk_config(output)):
            doc_id = f"{name}_{cmd.replace(' ','_')}_{i}"
            docs.append(f"# {name} — {cmd}\n{chunk}")
            ids.append(doc_id)
            metas.append({"device": name, "command": cmd, "type": "config"})

    embeddings = embedder.encode(docs).tolist()
    collection.add(documents=docs, ids=ids, metadatas=metas, embeddings=embeddings)
    print(f"  [{name}] добавлено {len(docs)} новых записей")

def main():
    # Пересоздаём коллекцию полностью при full rebuild
    import sys
    full_rebuild = "--full" in sys.argv

    if full_rebuild:
        try:
            client.delete_collection("network_configs")
            print("Коллекция удалена, пересоздаём...")
        except:
            pass

    collection = client.get_or_create_collection("network_configs")

    files = glob.glob("collected_configs/*.json")
    if not files:
        print("Нет файлов в collected_configs/")
        return

    for f in files:
        rebuild_device(collection, f)

    print(f"\nВсего в базе: {collection.count()} записей")

if __name__ == "__main__":
    main()
