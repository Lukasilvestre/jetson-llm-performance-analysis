import subprocess
import yaml
import csv
import re
from datetime import datetime
import os
import requests
import time
import statistics

# =========================
# UTIL
# =========================
def percentile(data, p):
    if not data:
        return 0
    data = sorted(data)
    k = int(len(data) * (p / 100))
    return data[min(k, len(data) - 1)]

# =========================
# CONTROLE DE HARDWARE
# =========================
def set_power_mode(mode):
    print(f"[INFO] Setting power mode: {mode}")
    try:
        subprocess.run(f"sudo nvpmodel -m {mode}", shell=True)
        subprocess.run("sudo jetson_clocks", shell=True)
    except:
        print("[WARN] Falha ao configurar modo de energia")

def set_swap(enabled):
    print(f"[INFO] Swap: {enabled}")
    try:
        if enabled == "enabled":
            subprocess.run("sudo swapon -a", shell=True)
        else:
            subprocess.run("sudo swapoff -a", shell=True)
    except:
        print("[WARN] Falha ao configurar swap")

# =========================
# TEGRASTATS
# =========================
def start_tegrastats(log_file):
    return subprocess.Popen(f"tegrastats --interval 100 > {log_file}", shell=True)

def stop_tegrastats(proc):
    proc.terminate()

# =========================
# PARSERS
# =========================
def parse_power_log(file_path):
    power = []
    with open(file_path) as f:
        for line in f:
            if "POM_5V_IN" in line:
                try:
                    val = int(line.split("POM_5V_IN")[1].split()[0].replace("mW", ""))
                    power.append(val / 1000)
                except:
                    pass
    return power

def parse_emc(file_path):
    emc = []
    with open(file_path) as f:
        for line in f:
            if "EMC_FREQ" in line:
                try:
                    percent = int(line.split("@")[1].replace("%", "").split()[0])
                    emc.append(percent)
                except:
                    pass
    return {
        "emc_avg": statistics.mean(emc) if emc else 0,
        "emc_std": statistics.stdev(emc) if len(emc) > 1 else 0
    }

# =========================
# OLLAMA PARSER (SEU ORIGINAL)
# =========================
def parse_ollama_cli_output(stderr_output):
    metrics = {
        'total_duration_s': None, 'load_duration_s': None, 'prompt_eval_count': None,
        'prompt_eval_duration_s': None, 'prompt_eval_rate_tps': None, 'eval_count': None,
        'eval_duration_s': None, 'eval_rate_tps': None
    }

    def duration_to_seconds(d_str):
        if not d_str: return None
        d_str = d_str.strip()
        if 'm' in d_str:
            parts = d_str.replace('s', '').split('m')
            minutes = float(parts[0])
            seconds = float(parts[1]) if parts[1] else 0
            return minutes * 60 + seconds
        if 'ms' in d_str: return float(d_str.replace('ms', '')) / 1000
        if 'µs' in d_str: return float(d_str.replace('µs', '')) / 1_000_000
        if 's' in d_str: return float(d_str.replace('s', ''))
        return None

    patterns = {
        'total_duration_s': r"total duration:\s*([\d\.msµs]+m?)",
        'load_duration_s': r"load duration:\s*([\d\.msµs]+m?)",
        'prompt_eval_count': r"prompt eval count:\s*(\d+)\s*tokens",
        'prompt_eval_duration_s': r"prompt eval duration:\s*([\d\.msµs]+m?)",
        'prompt_eval_rate_tps': r"prompt eval rate:\s*([\d\.]+)\s*tokens/s",
        'eval_count': r"eval count:\s*(\d+)\s*tokens",
        'eval_duration_s': r"eval duration:\s*([\d\.msµs]+m?)",
        'eval_rate_tps': r"eval rate:\s*([\d\.]+)\s*tokens/s"
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, stderr_output)
        if match:
            value = match.group(1)
            if 'duration' in key: metrics[key] = duration_to_seconds(value)
            elif 'count' in key: metrics[key] = int(value)
            elif 'rate' in key: metrics[key] = float(value)

    return metrics

# =========================
# STREAMING (TTFT + FLUIDEZ)
# =========================
def measure_streaming(model, prompt):

    timestamps = []
    start = time.time()

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": True},
        stream=True
    )

    first_token_time = None

    for line in response.iter_lines():
        if line:
            t = time.time()

            if first_token_time is None:
                first_token_time = t

            timestamps.append(t)

    inter_token = [
        timestamps[i] - timestamps[i-1]
        for i in range(1, len(timestamps))
    ]

    return {
        "ttft_real": first_token_time - start if first_token_time else None,
        "tokens_stream": len(timestamps),
        "inter_token_avg": statistics.mean(inter_token) if inter_token else 0,
        "inter_token_p95": percentile(inter_token, 95),
        "inter_token_p99": percentile(inter_token, 99)
    }

# =========================
# ENERGIA
# =========================
def compute_energy_metrics(power, total_time, tokens):

    if not power:
        return {}

    avg_power = sum(power) / len(power)
    energy = avg_power * total_time

    return {
        "avg_power_w": avg_power,
        "energy_j": energy,
        "joules_per_token": energy / tokens if tokens else 0,
        "tokens_per_watt": tokens / avg_power if avg_power else 0,
        "edp": energy * total_time
    }

# =========================
# MAIN
# =========================
def run_automated_benchmark():

    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    test_plan = []
    for model in config['models_to_test']:
        for power_mode in config['power_modes']:
            for swap in config['swap_configurations']:
                test_plan.append({
                    "model": model,
                    "power_mode": power_mode,
                    "swap": swap
                })

    print("="*60)
    print("PLANO DE EXECUÇÃO DO BENCHMARK")
    print("="*60)

    for i, test in enumerate(test_plan, 1):
        print(f"Teste {i}: {test}")

    input("\nPressione Enter para iniciar...")

    output_file = config['output_csv_file']
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    fieldnames = [
        'timestamp', 'model', 'power_mode', 'swap_enabled', 'status', 'error_message',
        'total_duration_s', 'load_duration_s', 'prompt_eval_count', 'prompt_eval_duration_s',
        'prompt_eval_rate_tps', 'eval_count', 'eval_duration_s', 'eval_rate_tps',
        'ttft_real', 'tokens_stream',
        'inter_token_avg', 'inter_token_p95', 'inter_token_p99',
        'avg_power_w', 'energy_j', 'joules_per_token',
        'tokens_per_watt', 'edp',
        'emc_avg', 'emc_std'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for i, test in enumerate(test_plan, 1):

            model = test['model']
            power_mode = test['power_mode']
            swap = test['swap']

            print(f"\n[RUN] {i}/{len(test_plan)} | {model}")

            set_power_mode(power_mode)
            set_swap(swap)

            log_file = f"tegra_{model}_{i}.log"
            tegra_proc = start_tegrastats(log_file)

            stream_metrics = measure_streaming(model, config['prompt'])

            command = ["ollama", "run", model, config['prompt'], "--verbose"]

            result = subprocess.run(command, capture_output=True, text=True)

            stop_tegrastats(tegra_proc)

            base_row = {
                'timestamp': datetime.now().isoformat(),
                'model': model,
                'power_mode': power_mode,
                'swap_enabled': swap,
            }

            if result.returncode == 0:

                metrics = parse_ollama_cli_output(result.stderr)

                power = parse_power_log(log_file)
                emc = parse_emc(log_file)

                energy = compute_energy_metrics(
                    power,
                    metrics.get("total_duration_s", 0),
                    metrics.get("eval_count", 0)
                )

                base_row.update(metrics)
                base_row.update(stream_metrics)
                base_row.update(emc)
                base_row.update(energy)

                base_row['status'] = 'success'
                base_row['error_message'] = ''

            else:
                base_row['status'] = 'failure'
                base_row['error_message'] = result.stderr

            writer.writerow(base_row)
            csvfile.flush()

    print("\nBenchmark finalizado!")

if __name__ == "__main__":
    run_automated_benchmark()
