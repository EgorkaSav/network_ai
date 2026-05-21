import json, os
from netmiko import ConnectHandler

DEVICES_FILE = "netbox_mock.json"
OUTPUT_DIR = "collected_configs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

COMMANDS = {
    "router": [
        "show running-config",
        "show ip interface brief",
        "show ip route",
        "show ip ospf neighbor",
        "show version",
    ],
    "switch": [
        "show running-config",
        "show interfaces status",
        "show vlan brief",
        "show spanning-tree",
    ],
}

SSH_CREDS = {
    "username": "admin",
    "password": "admin123",
    "secret":   "admin123",
}

def collect_device(device):
    conn_params = {
        "device_type": device["platform"],
        "host":        device["mgmt_ip"],
        **SSH_CREDS,
    }
    results = {}
    try:
        with ConnectHandler(**conn_params) as conn:
            conn.enable()
            for cmd in COMMANDS.get(device["role"], []):
                results[cmd] = conn.send_command(cmd)
                print(f"  [{device['name']}] {cmd} — OK")
    except Exception as e:
        print(f"  [{device['name']}] ОШИБКА: {e}")
    return results

def main():
    with open(DEVICES_FILE) as f:
        data = json.load(f)
    for device in data["devices"]:
        print(f"\nСобираю: {device['name']} ({device['mgmt_ip']})")
        outputs = collect_device(device)
        with open(f"{OUTPUT_DIR}/{device['name']}.json", "w") as f:
            json.dump({"device": device, "outputs": outputs}, f, indent=2, ensure_ascii=False)
        print(f"  Сохранено: {OUTPUT_DIR}/{device['name']}.json")

if __name__ == "__main__":
    main()
