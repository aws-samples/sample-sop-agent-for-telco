#!/usr/bin/env python3
"""WebSocket adapter for srsRAN gNB metrics → Telegraf execd input."""
import json
import sys
import time

try:
    import websocket
except ImportError:
    # Fallback: generate synthetic metrics for demo
    import random
    while True:
        ts = int(time.time() * 1e9)
        metrics = {
            "du_du_high_mac_dl_0_cpu_usage_percent": random.uniform(10, 80),
            "du_du_high_mac_ul_0_cpu_usage_percent": random.uniform(10, 70),
            "du_dl_throughput_mbps": random.uniform(50, 500),
            "du_ul_throughput_mbps": random.uniform(10, 100),
            "du_cqi_average": random.uniform(8, 15),
            "du_harq_ack_percent": random.uniform(85, 99),
            "du_bler_percent": random.uniform(0.1, 10),
            "du_pusch_snr_db": random.uniform(10, 35),
            "du_pucch_snr_db": random.uniform(8, 30),
            "du_ta_us": random.uniform(0.5, 5.0),
        }
        fields = ",".join(f"{k}={v:.2f}" for k, v in metrics.items())
        print(f"srsran {fields} {ts}", flush=True)
        time.sleep(1)

GNB_WS_URL = "ws://srsran-gnb.srsran.svc:55555"

def main():
    ws = websocket.WebSocket()
    while True:
        try:
            ws.connect(GNB_WS_URL, timeout=5)
            while True:
                msg = ws.recv()
                data = json.loads(msg)
                ts = int(time.time() * 1e9)
                fields = ",".join(f"{k}={v}" for k, v in data.items() if isinstance(v, (int, float)))
                if fields:
                    print(f"srsran {fields} {ts}", flush=True)
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    main()
