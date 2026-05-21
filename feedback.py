import json
from datetime import datetime
from pathlib import Path

FEEDBACK_FILE = "feedback_log.jsonl"

def save(query, intent, device, params, commands, success, correction=""):
    record = {
        "ts":         datetime.now().isoformat(),
        "query":      query,
        "intent":     intent,
        "device":     device,
        "params":     params,
        "commands":   commands,
        "success":    success,
        "correction": correction,
    }
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def load_good_examples(n=8):
    examples = []
    try:
        with open(FEEDBACK_FILE) as f:
            for line in f:
                rec = json.loads(line)
                if rec["success"] and rec["intent"]:
                    examples.append(rec)
    except FileNotFoundError:
        pass
    return examples[-n:]

def stats():
    total, good, bad = 0, 0, 0
    try:
        with open(FEEDBACK_FILE) as f:
            for line in f:
                rec = json.loads(line)
                total += 1
                if rec["success"]:
                    good += 1
                else:
                    bad += 1
    except FileNotFoundError:
        pass
    print(f"Всего: {total} | Успешных: {good} | Ошибок: {bad}")
    if total:
        print(f"Точность: {good/total*100:.1f}%")
