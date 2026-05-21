import json, requests
import chromadb
from sentence_transformers import SentenceTransformer
from netmiko import ConnectHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from normalizer import normalize, resolve_site
from feedback import save, load_good_examples, stats
from learning import find_learned, teach, increment_usage, list_learned

OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "qwen2.5:3b"
CHROMA_DIR  = "./chroma_db"
EMBED_MODEL = "all-MiniLM-L6-v2"
NETBOX_FILE = "netbox_mock.json"
COMMANDS_DB = "commands_db.json"

client     = chromadb.PersistentClient(path=CHROMA_DIR)
collection = client.get_collection("network_configs")
embedder   = SentenceTransformer(EMBED_MODEL)

with open(NETBOX_FILE, encoding="utf-8") as f:
    netbox_data = json.load(f)
with open(COMMANDS_DB, encoding="utf-8") as f:
    commands_db = json.load(f)

SYSTEM_BASE = """You are a network assistant. Respond ONLY with JSON, no explanation.
Format: {"device":"R1","intent":"...","params":{}}

Examples:
{"device":"R1","intent":"показать маршруты ospf","params":{}}
{"device":"R1","intent":"показать интерфейсы ip interface brief","params":{}}
{"device":"R1","intent":"показать acl access-list","params":{}}
{"device":"R1","intent":"показать running config конфигурацию","params":{}}
{"device":"R1","intent":"показать nat трансляции","params":{}}
{"device":"R1","intent":"показать ospf соседей neighbor","params":{}}
{"device":"R1","intent":"добавить description описание на интерфейс","params":{"iface":"FastEthernet0/0","value":"WAN"}}
{"device":"R1","intent":"добавить хост в acl access-list разрешить permit","params":{"acl_name":"MGMT-IN","host":"10.10.10.10"}}
{"device":"R1","intent":"добавить хост в acl access-list запретить deny","params":{"acl_name":"MGMT-IN","host":"12.12.12.12"}}
{"device":"R1","intent":"добавить хост в vty acl access-class разрешить","params":{"host":"10.0.0.1"}}
{"device":"R1","intent":"добавить статический маршрут route","params":{"network":"10.10.10.0","mask":"255.255.255.0","gateway":"10.0.0.1"}}
{"device":"R1","intent":"no shutdown включить поднять интерфейс","params":{"iface":"FastEthernet0/1"}}
{"device":"R1","intent":"shutdown выключить интерфейс","params":{"iface":"FastEthernet0/1"}}
{"device":"SW1","intent":"показать vlan","params":{}}

IMPORTANT: Copy IP addresses and names EXACTLY as user wrote. Never change them."""

def build_system():
    system = SYSTEM_BASE
    good = load_good_examples(n=5)
    if good:
        extra = "\n".join(
            f'{{"device":"{e["device"]}","intent":"{e["intent"]}","params":{json.dumps(e["params"])}}}'
            f'  # {e["query"]}'
            for e in good
        )
        system += f"\n\nRecent successful examples:\n{extra}"
    return system

def get_context(query, n=2):
    emb = embedder.encode([query]).tolist()
    res = collection.query(query_embeddings=emb, n_results=n)
    if not res["documents"][0]:
        return ""
    parts = []
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        parts.append(f"[{meta.get('device','?')}]\n{doc[:200]}")
    return "\n".join(parts)

def ask_model(query, context, device_hint=None):
    hint     = f" Target device: {device_hint}." if device_hint else ""
    user_msg = f"Context:\n{context}\n\nRequest: {query}{hint}"
    prompt   = f"{build_system()}\n\nUser: {user_msg}\nAssistant:"
    r = requests.post(OLLAMA_URL, json={
        "model":      MODEL,
        "prompt":     prompt,
        "stream":     False,
        "keep_alive": "60m",
        "options":    {"temperature": 0.0, "num_predict": 80, "num_ctx": 2048}
    }, timeout=300)
    data = r.json()
    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return ""
    return data.get("response", "").strip()

def extract_json(text):
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    start = None
    return None

def resolve_commands(intent, action, params):
    items = commands_db.get(action, [])
    best, best_score = None, 0
    for item in items:
        score = len(set(item["intent"].split()) & set(intent.split()))
        if score > best_score:
            best_score, best = score, item
    if not best:
        return None, f"Intent не найден: {intent}"
    if "commands" in best:
        return best["commands"], None
    if "template" in best:
        cmds = []
        for cmd in best["template"]:
            try:
                cmds.append(cmd.format(**params))
            except KeyError as e:
                return None, f"Не хватает параметра {e}"
        return cmds, None
    return None, "Нет команд"

def execute(device_name, commands, configure=False):
    dev = next((d for d in netbox_data["devices"] if d["name"] == device_name), None)
    if not dev:
        return f"Устройство {device_name} не найдено"
    try:
        with ConnectHandler(
            device_type=dev["platform"], host=dev["mgmt_ip"],
            username="admin", password="admin123", secret="admin123"
        ) as conn:
            conn.enable()
            output = []
            if configure:
                conn.config_mode()
                for cmd in commands:
                    result = conn.send_command_timing(cmd)
                    output.append(
                        f"OK: {cmd}" if "Invalid" not in result
                        else f"WARN: {cmd}: {result.strip()}"
                    )
                conn.exit_config_mode()
                conn.save_config()
                output.append("Сохранено")
            else:
                for cmd in commands:
                    output.append(f"--- {cmd} ---\n{conn.send_command(cmd)}")
            return "\n".join(output)
    except Exception as e:
        return f"Ошибка подключения: {e}"

def ask_user_to_teach(query, device_hint=None):
    """Режим обучения — пользователь вводит команды вручную."""
    print("\n[?] Не знаю как выполнить этот запрос.")
    print("    Вы можете научить меня:")
    print("    1. Введите устройство и команды вручную")
    print("    2. Нажмите Enter для отмены\n")

    # Устройство
    if device_hint:
        device = device_hint
        print(f"    Устройство: {device}")
    else:
        device = input("    Устройство (например R1): ").strip()
        if not device:
            return None

    # Проверяем что устройство существует
    dev = next((d for d in netbox_data["devices"] if d["name"] == device), None)
    if not dev:
        print(f"    Устройство {device} не найдено в netbox")
        return None

    # Команды
    print("    Введите команды через запятую:")
    print("    Пример: show ip access-lists")
    print("    Пример конфига: interface Fa0/0, description TEST")
    raw = input("    Команды: ").strip()
    if not raw:
        return None

    commands = [c.strip() for c in raw.split(",")]

    # Тип — show или configure
    is_conf = input("    Это конфигурация? [y/N]: ").strip().lower() == "y"

    # Показываем что будет выполнено
    print(f"\n[!] Выполнить на {device}:")
    for cmd in commands:
        print(f"    {cmd}")

    if input("Подтвердить? [y/N]: ").strip().lower() != "y":
        return None

    # Выполняем
    result = execute(device, commands, configure=is_conf)
    print("\n" + result)

    # Если всё хорошо — сохраняем
    ok = input("\nРезультат верный? Сохранить в память? [y/N]: ").strip().lower()
    if ok == "y":
        desc = input("Краткое описание (необязательно): ").strip()
        teach(query, device, commands, description=desc)
        # Добавляем в feedback как успешный
        save(query, f"learned:{query[:30]}", device, {}, commands, success=True)
        print("[LEARN] Запомнил! Следующий раз выполню автоматически.")

    return result

def run_single(query, device_hint=None):
    # Сначала проверяем выученные команды
    learned = find_learned(query)
    if learned:
        device = device_hint or learned["device"]
        print(f"[LEARN] Знаю этот запрос! Команды: {learned['commands']}")
        result = execute(device, learned["commands"])
        increment_usage(query)
        print("\n" + result)
        return result

    # Обычный путь через AI
    context  = get_context(query)
    response = ask_model(query, context, device_hint)
    print(f"[AI]   ответ: {response[:150]}")

    if not response:
        return ask_user_to_teach(query, device_hint) or "Отменено"

    parsed = extract_json(response)
    if not parsed:
        print(f"[AI]   не удалось распарсить JSON")
        return ask_user_to_teach(query, device_hint) or "Отменено"

    device = device_hint or parsed.get("device", "")
    intent = parsed.get("intent", "")
    params = parsed.get("params", {})

    action = "show"
    for item in commands_db["configure"]:
        if item["intent"] == intent:
            action = "configure"
            break

    commands, error = resolve_commands(intent, action, params)

    # Если не нашли команды — предлагаем научить
    if error:
        print(f"[AI]   {error}")
        return ask_user_to_teach(query, device_hint) or "Отменено"

    if action == "configure":
        print(f"\n[!] Выполнить на {device}:")
        for cmd in commands:
            print(f"    {cmd}")
        if input("Подтвердить? [y/N]: ").strip().lower() != "y":
            save(query, intent, device, params, commands, success=False, correction="отменено")
            return "Отменено"

    result = execute(device, commands, configure=(action == "configure"))
    print("\n" + result)

    ok = input("\nРезультат верный? [Y/n]: ").strip().lower()
    if ok == "n":
        correction = input("Как должно было быть? (опционально): ").strip()
        save(query, intent, device, params, commands, success=False, correction=correction)
        # Предлагаем сразу научить правильному
        print("\nХотите научить меня правильному варианту?")
        if input("[y/N]: ").strip().lower() == "y":
            ask_user_to_teach(query, device_hint)
    else:
        save(query, intent, device, params, commands, success=True)

    return result

def run(query):
    query_raw = query
    query     = normalize(query)

    site_devices = resolve_site(query_raw)
    if site_devices:
        print(f"[SITE] устройства на площадке: {site_devices}")
        results = []
        for dev in site_devices:
            print(f"\n{'='*30}\n Опрашиваю: {dev}\n{'='*30}")
            result = run_single(query, device_hint=dev)
            results.append(f"=== {dev} ===\n{result}")
        return "\n\n".join(results)

    return run_single(query)

if __name__ == "__main__":
    print("=== Network AI Agent ===")
    print("Команды: stats, learned, exit\n")
    print("Прогрев модели...")
    requests.post(OLLAMA_URL, json={
        "model": MODEL, "prompt": "ready",
        "stream": False, "keep_alive": "60m"
    }, timeout=300)
    print("Готово\n")

    while True:
        query = input(">> ").strip()
        if not query:
            continue
        if query.lower() in ("exit", "quit"):
            break
        if query.lower() == "stats":
            stats()
            continue
        if query.lower() == "learned":
            list_learned()
            continue
        print("\n" + (run(query) or "") + "\n")
