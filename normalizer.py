import re, json

with open("netbox_mock.json") as f:
    _nb = json.load(f)

IFACE_MAP = [
    (r'\bfa\s*(\d+/\d+)\b', lambda m: f'FastEthernet{m.group(1)}'),
    (r'\bgi\s*(\d+/\d+)\b', lambda m: f'GigabitEthernet{m.group(1)}'),
    (r'\bge\s*(\d+/\d+)\b', lambda m: f'GigabitEthernet{m.group(1)}'),
    (r'\bte\s*(\d+/\d+)\b', lambda m: f'TenGigabitEthernet{m.group(1)}'),
    (r'\blo\s*(\d+)\b',     lambda m: f'Loopback{m.group(1)}'),
    (r'\bvlan\s*(\d+)\b',   lambda m: f'Vlan{m.group(1)}'),
]

DEVICE_MAP = [
    (r'\br\s*(\d+)\b',   lambda m: f'R{m.group(1)}'),
    (r'\bsw\s*(\d+)\b',  lambda m: f'SW{m.group(1)}'),
    (r'\bmes\s*(\d+)\b', lambda m: f'MES{m.group(1)}'),
]

ACTION_MAP = [
    (r'\bпокажи\b|\bпоказывай\b|\bвыведи\b|\bпроверь\b|\bдай\b|\bпосмотри\b', 'показать'),
    (r'\bдобавь\b|\bпоставь\b|\bнастрой\b|\bпропиши\b|\bвбей\b|\bсоздай\b',   'добавить'),
    (r'\bудали\b|\bубери\b|\bсними\b',                'удалить'),
    (r'\bвыключи\b|\bзагаси\b|\bотключи\b',           'shutdown выключить'),
    (r'\bвключи\b|\bподними\b|\bзапусти интерфейс\b', 'no shutdown включить'),
    (r'\bсохрани\b|\bзапиши конфиг\b',                'сохранить конфигурацию write memory'),
]

def _stem(word):
    return word[:5] if len(word) >= 5 else word

def resolve_site(text):
    text_low = text.lower()
    matched = []
    for site in _nb.get("sites", []):
        raw = " ".join([
            site.get("name", ""),
            site.get("city", ""),
            site.get("address", ""),
            site.get("region", ""),
        ])
        keywords = [w.lower() for w in re.split(r"[\s,.\-/]+", raw) if len(w) > 3]
        stems    = [_stem(kw) for kw in keywords]
        hits     = sum(1 for s in stems if s in text_low)
        if hits >= 1:
            matched.append(site["id"])
    if not matched:
        return []
    return [d["name"] for d in _nb["devices"] if d.get("site_id") in matched]

def normalize(text):
    result = text.strip()
    for pattern, replacement in ACTION_MAP:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    for pattern, replacement in IFACE_MAP:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    for pattern, replacement in DEVICE_MAP:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result

if __name__ == "__main__":
    print("=== Тест нормализатора ===\n")
    tests = [
        ("Покажи ACL на всех устройствах на Тестовой 1 в Москве", True),
        ("покажи интерфейсы на всех устройствах в Москве",        True),
        ("дай конфиг на всех в Московской области",               True),
        ("показать ospf на r1",                                    False),
        ("покажи fa 0/0 на r2",                                    False),
    ]
    for text, expect_site in tests:
        devices  = resolve_site(text)
        norm     = normalize(text)
        site_ok  = bool(devices) == expect_site
        print(f"  вход:    {text}")
        print(f"  выход:   {norm}")
        print(f"  сайт:    {devices or 'не найден'} {'OK' if site_ok else 'ОШИБКА'}\n")
