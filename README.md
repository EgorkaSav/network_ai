# Network AI Agent

Локальный ИИ-агент для управления сетевым оборудованием через естественный язык.
Работает полностью офлайн на базе Ollama + qwen2.5:7b + RAG (ChromaDB).

## Архитектура

```
Запрос пользователя
        │
        ▼
  normalizer.py          ← нормализация текста, определение площадки
        │
        ├─ resolve_site() → несколько устройств? → запуск по каждому
        │
        ▼
   learning.py           ← есть в памяти? → выполняем сразу
        │
        ▼
    agent.py             ← основной агент
        │
        ├─ ChromaDB RAG  ← контекст из реальных конфигов
        ├─ qwen2.5:7b    ← определяет intent + параметры
        ├─ commands_db   ← берёт готовые команды
        └─ reasoner.py   ← если не знает — думает сам
              │
              ▼
         Netmiko SSH     ← выполняет на реальном железе
              │
              ▼
         feedback.py     ← сохраняет результат для обучения
```

## Стек

| Компонент | Версия | Назначение |
|-----------|--------|------------|
| Python | 3.12 | Основной язык |
| Ollama | 0.18+ | Запуск LLM локально |
| qwen2.5:7b | latest | Языковая модель (офлайн) |
| ChromaDB | 0.5.x | Векторная база для RAG |
| sentence-transformers | 3.x | Эмбеддинги (all-MiniLM-L6-v2) |
| Netmiko | 4.x | SSH/Telnet к сетевому оборудованию |
| Paramiko | 2.9.5 | SSH транспорт (старые Cisco IOS) |

---

## Установка

```bash
# 1. Клонируем репозиторий
git clone https://github.com/EgorkaSav/network-ai.git
cd network-ai

# 2. Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Устанавливаем зависимости
pip install netmiko==4.3.0 chromadb==0.5.3 \
            sentence-transformers==3.0.1 requests paramiko==2.9.5

# 4. Устанавливаем Ollama и скачиваем модель
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
```

### Настройка SSH для старых Cisco IOS

Современный OpenSSH 9.x несовместим со старыми версиями Cisco SSH
из-за расширений `ext-info-c` и `kex-strict`. Добавьте в `~/.ssh/config`:

```
Host 192.168.*.*
    KexAlgorithms diffie-hellman-group1-sha1
    HostKeyAlgorithms ssh-rsa
    PubkeyAcceptedAlgorithms +ssh-rsa
    Ciphers aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc
    MACs hmac-sha1,hmac-md5
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

Host 10.*.*.*
    KexAlgorithms diffie-hellman-group1-sha1
    HostKeyAlgorithms ssh-rsa
    PubkeyAcceptedAlgorithms +ssh-rsa
    Ciphers aes128-cbc,3des-cbc,aes192-cbc,aes256-cbc
    MACs hmac-sha1,hmac-md5
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

> **Важно:** Агент использует Netmiko/Paramiko напрямую и не зависит
> от системного SSH. Конфиг выше нужен только для ручного тестирования.
> Для Paramiko используется версия 2.9.5 — она не отправляет `ext-info-c`.

---

## Запуск

```bash
# Шаг 1 — собрать конфиги с устройств
python3 collect_configs.py

# Шаг 2 — наполнить векторную базу
python3 rag_setup.py

# Шаг 3 — запустить агента
python3 agent.py
```

---

## Использование

```
>> Покажи ospf маршруты на R1
>> Покажи ACL на всех устройствах на Тестовой 1 в Москве
>> Добавь хост 10.10.10.10 в ACL MGMT-IN на R1
>> think: Почему не работает OSPF между R1 и R2
>> stats
>> learned
>> exit
```

### Специальные команды

| Команда | Описание |
|---------|----------|
| `stats` | Статистика успешных / неудачных запросов |
| `learned` | Список команд выученных агентом |
| `think: <запрос>` | Режим рассуждения — модель думает сама без commands_db |
| `exit` | Выход |

---

## Описание файлов

### `agent.py`
Главный файл — оркестрирует все компоненты.

- Принимает запрос от пользователя
- Вызывает `normalizer.py` для нормализации текста
- Определяет площадку через `resolve_site()` (мультидевайс запросы)
- Проверяет `learning.py` — не выучена ли уже эта команда
- Отправляет запрос в qwen2.5:7b через Ollama API (`/api/generate`)
- Парсит JSON-ответ модели (device + intent + params)
- Ищет команды в `commands_db.json`
- При неудаче — передаёт управление в `reasoner.py`
- Выполняет команды на железе через Netmiko
- Запрашивает обратную связь и сохраняет через `feedback.py`

### `collect_configs.py`
Сбор конфигураций с сетевых устройств по SSH.

- Читает список устройств из `netbox_mock.json`
- Подключается по SSH через Netmiko к каждому устройству
- Выполняет набор команд (`show running-config`, `show ip route` и др.)
- Сохраняет результат в `collected_configs/<device_name>.json`
- Запускать вручную при изменении конфигурации оборудования

**Команды по умолчанию:**

| Роль | Команды |
|------|---------|
| router | show running-config, show ip interface brief, show ip route, show ip ospf neighbor, show version |
| switch | show running-config, show interfaces status, show vlan brief, show spanning-tree |

### `rag_setup.py`
Индексация собранных конфигов в векторную базу ChromaDB.

- Читает файлы из `collected_configs/`
- Разбивает конфиги на чанки по 500 символов
- Генерирует эмбеддинги через `all-MiniLM-L6-v2` (90 MB, офлайн)
- Сохраняет в `chroma_db/`
- Поддерживает режим `--full` для полной пересборки базы
- При повторном запуске удаляет старые записи устройства и добавляет новые

```bash
python3 rag_setup.py          # обновить изменившиеся устройства
python3 rag_setup.py --full   # полная пересборка с нуля
```

### `normalizer.py`
Нормализация пользовательского ввода перед отправкой в модель.

Три группы замен:

1. **Действия** — синонимы глаголов:
   `покажи / выведи / дай / посмотри` → `показать`
   `добавь / пропиши / вбей / настрой` → `добавить`
   `выключи / загаси` → `shutdown выключить`

2. **Интерфейсы** — короткие формы в полные:
   `fa 0/0` → `FastEthernet0/0`
   `gi 0/1` → `GigabitEthernet0/1`
   `lo 0` → `Loopback0`

3. **Устройства** — опечатки в канонические имена:
   `r1` → `R1`, `sw 1` → `SW1`

Также содержит `resolve_site()` — определяет устройства по площадке.
Использует стемминг (первые 5 букв) для устойчивости к падежам:
`Москва / Москве / Москву` — всё матчится по корню `москв`.

### `reasoner.py`
Chain-of-Thought рассуждение для неизвестных запросов.

Используется когда `commands_db.json` не содержит нужного intent.

**Цикл работы (до 2 попыток):**

1. `think()` — модель получает запрос + контекст и отвечает JSON:
   ```json
   {
     "thinking": "пользователь хочет проверить CEF таблицу",
     "action": "show",
     "device": "R1",
     "commands": ["show ip cef"],
     "confidence": 0.85
   }
   ```
2. Если `confidence < 0.4` — запрашивает подтверждение у пользователя
3. Выполняет команды на устройстве
4. `verify()` — модель проверяет: ответил ли вывод на исходный вопрос?
5. Если нет — пробует `better_commands` из ответа verify

Активируется командой `think: <запрос>` принудительно.

### `learning.py`
Долгосрочная память агента — выученные команды.

- `teach()` — сохраняет новую связку запрос→команды в `learned_commands.json`
- `find_learned()` — ищет похожий запрос по пересечению слов (порог 60%)
- `increment_usage()` — считает сколько раз команда использовалась
- `list_learned()` — вывод всей базы памяти (команда `learned`)

Когда агент не знает команду, пользователь может ввести её вручную.
После успешного выполнения агент запоминает связку навсегда.

### `feedback.py`
Сбор обратной связи для анализа и улучшения.

- После каждого выполнения спрашивает "Результат верный?"
- Сохраняет запись в `feedback_log.jsonl`:
  ```json
  {"ts": "2026-03-25T10:00:00", "query": "...", "intent": "...",
   "device": "R1", "commands": [...], "success": true, "correction": ""}
  ```
- `load_good_examples()` — возвращает N последних удачных примеров
  для добавления в системный промпт (динамический few-shot)
- `stats()` — выводит статистику точности

### `commands_db.json`
База готовых команд — главный источник знаний агента.

Структура:
```json
{
  "show": [
    {"intent": "показать маршруты ospf", "commands": ["show ip route ospf"]}
  ],
  "configure": [
    {
      "intent": "добавить description описание на интерфейс",
      "template": ["interface {iface}", "description {value}"]
    }
  ]
}
```

- Секция `show` — команды без параметров или с `{iface}`
- Секция `configure` — шаблоны с подстановкой параметров `{param}`
- Модель выбирает intent по пересечению слов (нечёткий матчинг)
- **Расширять этот файл — основной способ обучить агента новым командам**

### `netbox_mock.json`
Инвентарь сетевых устройств — замена реального NetBox.

```json
{
  "sites": [
    {
      "id": 1,
      "name": "Тестовая-1",
      "region": "Московская область",
      "city": "Москва",
      "address": "ул. Тестовая, д. 1"
    }
  ],
  "devices": [
    {
      "name": "R1",
      "role": "router",
      "platform": "cisco_ios",
      "mgmt_ip": "192.168.0.101",
      "site_id": 1
    }
  ]
}
```

- `sites` — физические площадки с адресами (для мультидевайс запросов)
- `devices` — устройства с привязкой к площадке через `site_id`
- `platform` — тип устройства для Netmiko (`cisco_ios`, `cisco_ios_telnet`, `eltex_mes` и др.)
- В продакшне заменяется на запрос к реальному NetBox через `pynetbox`

### `few_shot_examples.json`
Примеры запрос→действие для улучшения промпта.

Используются как дополнительные few-shot примеры в системном промпте.
Чем больше разных формулировок — тем точнее модель определяет intent.

---

## Генерируемые файлы

### `collected_configs/`
Директория с JSON-файлами конфигураций каждого устройства.

```json
{
  "device": {"name": "R1", "platform": "cisco_ios", ...},
  "outputs": {
    "show running-config": "...",
    "show ip route": "..."
  }
}
```

Генерируется `collect_configs.py`. В git не коммитится.

### `chroma_db/`
Векторная база ChromaDB с эмбеддингами конфигов.

Генерируется `rag_setup.py`. В git не коммитится.
При запросе агент ищет топ-N похожих чанков и подаёт их как контекст модели.

### `feedback_log.jsonl`
Лог всех запросов с результатами (JSONL — одна запись на строку).

Накапливается в процессе работы. Используется для:
- Статистики точности (`stats`)
- Динамических few-shot примеров в промпте
- Анализа ошибок и улучшения `commands_db.json`

### `learned_commands.json`
База выученных агентом команд.

Пополняется когда пользователь учит агента новой команде вручную.
Имеет приоритет над `commands_db.json` и RAG — проверяется первым.

---

## Добавление нового устройства

```bash
# 1. Добавить в netbox_mock.json
# 2. Собрать конфиг
python3 collect_configs.py
# 3. Переиндексировать
python3 rag_setup.py
```

## Добавление нового вендора (Eltex, Huawei, Juniper...)

1. Добавить устройство в `netbox_mock.json` с нужной платформой Netmiko:
   - Eltex: `"platform": "eltex_mes"`
   - Huawei VRP: `"platform": "huawei_vrpv8"`
   - Juniper: `"platform": "juniper_junos"`
   - Arista: `"platform": "arista_eos"`

2. Добавить команды в `commands_db.json`

3. Запустить `collect_configs.py` и `rag_setup.py`

## Переход на реальный NetBox

```python
import pynetbox
nb = pynetbox.api("http://netbox.company.local", token="ВАШ_ТОКЕН")
devices = [
    {
        "name":     str(d),
        "role":     d.device_role.slug,
        "platform": d.platform.slug,
        "mgmt_ip":  str(d.primary_ip.address).split("/")[0],
        "site_id":  d.site.id,
    }
    for d in nb.dcim.devices.all() if d.primary_ip
]
```

---

## Что дальше

- [ ] Web UI (FastAPI + простой фронт)
- [ ] Поддержка Eltex MES / ESR
- [ ] Интеграция с реальным NetBox
- [ ] Автообновление RAG по расписанию (cron)
- [ ] LoRA fine-tuning на накопленных feedback данных
- [ ] Параллельный опрос устройств (Nornir)
- [ ] История диалога в рамках сессии

---

## Известные ограничения

- qwen2.5:7b требует минимум 5 GB RAM (рекомендуется 8 GB)
- Работает только на CPU (нет GPU в VirtualBox)
- Среднее время ответа: 15–30 секунд на CPU
- Cisco IOS старых версий требует Paramiko 2.9.5 из-за несовместимости SSH
- При выключении GNS3 без остановки роутеров RSA ключи теряются

## Лицензия

MIT
