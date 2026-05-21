import json
from pathlib import Path

LEARNED_FILE = "learned_commands.json"

def load_learned() -> dict:
    try:
        with open(LEARNED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_learned(data: dict):
    with open(LEARNED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def find_learned(query: str) -> dict | None:
    """Ищем похожий запрос в выученных командах."""
    learned = load_learned()
    query_words = set(query.lower().split())
    best, best_score = None, 0
    for stored_query, data in learned.items():
        stored_words = set(stored_query.lower().split())
        score = len(query_words & stored_words) / max(len(query_words), 1)
        if score > 0.6 and score > best_score:
            best_score = score
            best = data
    return best

def teach(query: str, device: str, commands: list, description: str = ""):
    """Сохраняем новую команду в базу."""
    learned = load_learned()
    key = query.lower().strip()
    learned[key] = {
        "query":       query,
        "device":      device,
        "commands":    commands,
        "description": description,
        "times_used":  0,
    }
    save_learned(learned)
    print(f"[LEARN] Сохранено: '{query}' → {commands}")

def increment_usage(query: str):
    learned = load_learned()
    key = query.lower().strip()
    if key in learned:
        learned[key]["times_used"] = learned[key].get("times_used", 0) + 1
        save_learned(learned)

def list_learned():
    learned = load_learned()
    if not learned:
        print("База выученных команд пуста")
        return
    print(f"\nВыучено команд: {len(learned)}\n")
    for q, data in learned.items():
        print(f"  запрос:   {data['query']}")
        print(f"  команды:  {data['commands']}")
        print(f"  исп-й:    {data.get('times_used', 0)}")
        if data.get("description"):
            print(f"  описание: {data['description']}")
        print()
