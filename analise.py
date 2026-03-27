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

def strip_ansi(text):
    """Remove ALL terminal escape sequences (ANSI/VT100/xterm)."""
    text = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', text)
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b.', '', text)
    text = text.replace('\r', '')
    return text

def clean_stderr(stderr_text):
    """Remove ANSI escapes and spinner characters from Ollama stderr."""
    spinner_chars = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    text = strip_ansi(stderr_text)
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if all(c in spinner_chars or c == " " for c in stripped):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines).strip()

def drop_caches():
    """Drop Linux page/slab caches to free RAM before each test."""
    try:
        subprocess.run("sudo sysctl vm.drop_caches=3", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Page caches dropped")
    except Exception:
        print("[WARN] Falha ao liberar page caches")

def wait_for_vram(target_free_mb=2000, timeout=60):
    """
    Wait until enough unified memory is free.
    Reads /proc/meminfo (MemAvailable) — works reliably on Orin Nano.
    Gives up after `timeout` seconds and proceeds anyway.
    """
    print(f"[INFO] Aguardando RAM disponível >= {target_free_mb} MB...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open("/proc/meminfo") as f:
                meminfo = f.read()
            m = re.search(r"MemAvailable:\s+(\d+)\s+kB", meminfo)
            if m:
                available_mb = int(m.group(1)) // 1024
                print(f"[INFO]   RAM disponível: {available_mb} MB")
                if available_mb >= target_free_mb:
                    return True
        except Exception as e:
            print(f"[WARN] Erro lendo /proc/meminfo: {e}")
        time.sleep(1)
    print("[WARN] Timeout aguardando RAM — continuando mesmo assim")
    return False

# =========================
# CONTROLE DE HARDWARE
# =========================
def set_power_mode(mode):
    print(f"[INFO] Setting power mode: {mode}")
    try:
        subprocess.run(f"sudo nvpmodel -m {mode}", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run("sudo jetson_clocks", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # allow clocks to stabilize
    except Exception:
        print("[WARN] Falha ao configurar modo de energia")

def set_swap(enabled):
    print(f"[INFO] Swap: {enabled}")
    try:
        if enabled == "enabled":
            subprocess.run("sudo swapon -a", shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run("sudo swapoff -a", shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    except Exception:
        print("[WARN] Falha ao configurar swap")

# =========================
# OLLAMA
# =========================
def unload_ollama_model():
    """
    Force Ollama to unload any currently loaded model by sending a request
    with keep_alive=0. Frees unified memory for the next test.
    """
    try:
        requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "none", "keep_alive": 0},
            timeout=5
        )
    except Exception:
        pass
    time.sleep(2)

# =========================
# TEGRASTATS
# =========================
def start_tegrastats(log_file):
    proc = subprocess.Popen(
        f"tegrastats --interval 100 > {log_file} 2>&1",
        shell=True
    )
    return proc

def stop_tegrastats(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

# =========================
# PARSERS
# =========================
def parse_power_log(file_path):
    power = []
    try:
        with open(file_path) as f:
            for line in f:
                # Captura VDD_IN (Orin) ou POM_5V_IN (Nano antigo)
                match = re.search(r"(VDD_IN|POM_5V_IN)\s+(\d+)", line)
                if match:
                    val = int(match.group(2))
                    power.append(val / 1000.0) # Converte para Watts
    except FileNotFoundError:
        pass
    return power

def parse_emc(file_path):
    emc = []
    try:
        with open(file_path) as f:
            for line in f:
                # Captura o valor exato antes do %
                match = re.search(r"EMC_FREQ\s+(\d+)%", line)
                if match:
                    emc.append(int(match.group(1)))
    except FileNotFoundError:
        pass
    return {
        "emc_avg": round(statistics.mean(emc), 2) if emc else 0,
        "emc_std": round(statistics.stdev(emc), 2) if len(emc) > 1 else 0
    }

def parse_cpu_ram_gpu(file_path):
    cpu_loads = []
    ram_used = []
    ram_total_val = None
    gpu_loads = []
    gpu_freqs = []

    try:
        with open(file_path) as f:
            for line in f:
                # --- RAM ---
                m = re.search(r"RAM\s+(\d+)/(\d+)MB", line)
                if m:
                    ram_used.append(int(m.group(1)))
                    ram_total_val = int(m.group(2))

                # --- CPU ---
                m = re.search(r"CPU \[([^\]]+)\]", line)
                if m:
                    core_entries = m.group(1).split(",")
                    loads = []
                    for entry in core_entries:
                        entry = entry.strip()
                        if entry in ("off", "idle"):
                            continue
                        pct_match = re.match(r"(\d+)%", entry)
                        if pct_match:
                            loads.append(int(pct_match.group(1)))
                    if loads:
                        cpu_loads.append(statistics.mean(loads))

                # --- GPU (Suporta GR3D e GR3D_FREQ na Orin) ---
                m_gpu = re.search(r"GR3D(?:_FREQ)?\s+(\d+)%", line)
                if m_gpu:
                    gpu_loads.append(int(m_gpu.group(1)))
                
                m_freq = re.search(r"GR3D(?:_FREQ)?\s+\d+%@\[?(\d+)", line)
                if m_freq:
                    gpu_freqs.append(int(m_freq.group(1)))

    except FileNotFoundError:
        pass

    return {
        "cpu_avg": round(statistics.mean(cpu_loads), 2) if cpu_loads else 0,
        "cpu_std": round(statistics.stdev(cpu_loads), 2) if len(cpu_loads) > 1 else 0,
        "ram_used_avg_mb": round(statistics.mean(ram_used), 1) if ram_used else 0,
        "ram_used_max_mb": max(ram_used) if ram_used else 0,
        "ram_total_mb": ram_total_val or 0,
        "ram_usage_percent": round(
            statistics.mean(ram_used) / ram_total_val * 100, 1
        ) if ram_used and ram_total_val else 0,
        "gpu_avg": round(statistics.mean(gpu_loads), 2) if gpu_loads else 0,
        "gpu_std": round(statistics.stdev(gpu_loads), 2) if len(gpu_loads) > 1 else 0,
        "gpu_freq_avg_mhz": round(statistics.mean(gpu_freqs), 1) if gpu_freqs else 0,
    }

# =========================
# OLLAMA PARSER
# =========================
def parse_ollama_cli_output(stderr_output):
    stderr_output = strip_ansi(stderr_output)
    metrics = {
        'total_duration_s': None, 'load_duration_s': None,
        'prompt_eval_count': None, 'prompt_eval_duration_s': None,
        'prompt_eval_rate_tps': None, 'eval_count': None,
        'eval_duration_s': None, 'eval_rate_tps': None
    }

    def duration_to_seconds(d_str):
        if not d_str:
            return None
        d_str = d_str.strip()
        if 'm' in d_str and 's' in d_str:
            parts = d_str.replace('s', '').split('m')
            return float(parts[0]) * 60 + float(parts[1] if parts[1] else 0)
        if 'ms' in d_str:
            return float(d_str.replace('ms', '')) / 1000
        if 'µs' in d_str:
            return float(d_str.replace('µs', '')) / 1_000_000
        if 's' in d_str:
            return float(d_str.replace('s', ''))
        return None

    patterns = {
        'total_duration_s':      r"total duration:\s*([\d\.]+(?:µs|ms|m?s))",
        'load_duration_s':       r"load duration:\s*([\d\.]+(?:µs|ms|m?s))",
        'prompt_eval_count':     r"prompt eval count:\s*([\d,]+)",
        'prompt_eval_duration_s':r"prompt eval duration:\s*([\d\.]+(?:µs|ms|m?s))",
        'prompt_eval_rate_tps':  r"prompt eval rate:\s*([\d\.]+)",
        'eval_count':            r"eval count:\s*([\d,]+)",
        'eval_duration_s':       r"eval duration:\s*([\d\.]+(?:µs|ms|m?s))",
        'eval_rate_tps':         r"eval rate:\s*([\d\.]+)"
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, stderr_output, re.IGNORECASE)
        if match:
            value = match.group(1)
            if 'duration' in key:
                metrics[key] = duration_to_seconds(value)
            elif 'count' in key:
                metrics[key] = int(value.replace(',', ''))
            elif 'rate' in key:
                metrics[key] = float(value)

    return metrics

# =========================
# STREAMING (TTFT + FLUIDEZ)
# =========================
def measure_streaming(model, prompt, timeout=120):
    timestamps = []
    start = time.time()
    first_token_time = None

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": True},
            stream=True,
            timeout=timeout
        )
        for line in response.iter_lines():
            if line:
                t = time.time()
                if first_token_time is None:
                    first_token_time = t
                timestamps.append(t)
    except requests.exceptions.RequestException as e:
        print(f"[WARN] Streaming request falhou: {e}")
        return {
            "ttft_real": None, "tokens_stream": 0,
            "inter_token_avg": 0, "inter_token_p95": 0, "inter_token_p99": 0
        }

    inter_token = [
        timestamps[i] - timestamps[i - 1]
        for i in range(1, len(timestamps))
    ]

    return {
        "ttft_real": round(first_token_time - start, 4) if first_token_time else None,
        "tokens_stream": len(timestamps),
        "inter_token_avg": round(statistics.mean(inter_token), 4) if inter_token else 0,
        "inter_token_p95": round(percentile(inter_token, 95), 4) if inter_token else 0,
        "inter_token_p99": round(percentile(inter_token, 99), 4) if inter_token else 0
    }

# =========================
# ENERGIA
# =========================
def compute_energy_metrics(power, total_time, tokens):
    if not power or not total_time:
        return {
            "avg_power_w": 0, "energy_j": 0,
            "joules_per_token": 0, "tokens_per_watt": 0, "edp": 0
        }

    avg_power = statistics.mean(power)
    energy = avg_power * total_time

    return {
        "avg_power_w": round(avg_power, 3),
        "energy_j": round(energy, 3),
        "joules_per_token": round(energy / tokens, 4) if tokens else 0,
        "tokens_per_watt": round(tokens / avg_power, 4) if avg_power else 0,
        "edp": round(energy * total_time, 4)
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

    print("=" * 60)
    print("PLANO DE EXECUÇÃO DO BENCHMARK — Jetson Orin Nano")
    print("=" * 60)
    for i, test in enumerate(test_plan, 1):
        print(f"  Teste {i:02d}: {test}")

    input("\nPressione Enter para iniciar...")

    output_file = config['output_csv_file']
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    fieldnames = [
        'timestamp', 'model', 'power_mode', 'swap_enabled', 'status', 'error_message',
        'total_duration_s', 'load_duration_s',
        'prompt_eval_count', 'prompt_eval_duration_s', 'prompt_eval_rate_tps',
        'eval_count', 'eval_duration_s', 'eval_rate_tps',
        'ttft_real', 'tokens_stream',
        'inter_token_avg', 'inter_token_p95', 'inter_token_p99',
        'avg_power_w', 'energy_j', 'joules_per_token', 'tokens_per_watt', 'edp',
        'emc_avg', 'emc_std',
        'cpu_avg', 'cpu_std',
        'ram_used_avg_mb', 'ram_used_max_mb', 'ram_total_mb', 'ram_usage_percent',
        'gpu_avg', 'gpu_std', 'gpu_freq_avg_mhz'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for i, test in enumerate(test_plan, 1):
            model      = test['model']
            power_mode = test['power_mode']
            swap       = test['swap']

            print(f"\n{'='*60}")
            print(f"[RUN {i:02d}/{len(test_plan)}] modelo={model} | power_mode={power_mode} | swap={swap}")
            print(f"{'='*60}")

            # -- Preparar hardware --
            set_power_mode(power_mode)
            set_swap(swap)

            # -- Descarregar modelo anterior da VRAM --
            unload_ollama_model()

            # -- Liberar page caches --
            drop_caches()

            # -- Aguardar memória disponível --
            wait_for_vram(target_free_mb=config.get('min_free_ram_mb', 2500))

            log_file = f"/tmp/tegra_{re.sub(r'[:/]', '_', model)}_{i}.log"

            base_row = {
                'timestamp':    datetime.now().isoformat(),
                'model':        model,
                'power_mode':   power_mode,
                'swap_enabled': swap,
            }

            tegra_proc = start_tegrastats(log_file)

            try:
                # -- Medição de streaming (TTFT) --
                stream_metrics = measure_streaming(model, config['prompt'])

                # -- Inferência via CLI --
                # Nota: Não é possível passar num_ctx via CLI "run", o ideal é criar 
                # um Modelfile para os modelos maiores caso precise limitar a VRAM
                command = ["ollama", "run", model, config['prompt'], "--verbose"]
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=config.get('inference_timeout_s', 300),
                    env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
                )

            except subprocess.TimeoutExpired:
                stop_tegrastats(tegra_proc)
                base_row['status'] = 'timeout'
                base_row['error_message'] = 'Inferência excedeu o timeout configurado'
                writer.writerow(base_row)
                csvfile.flush()
                print(f"[ERROR] Timeout no teste {i}")
                continue

            finally:
                stop_tegrastats(tegra_proc)

            # -- Parse dos logs de hardware --
            power        = parse_power_log(log_file)
            emc_metrics  = parse_emc(log_file)
            hw_metrics   = parse_cpu_ram_gpu(log_file)

            if result.returncode == 0:
                ollama_metrics = parse_ollama_cli_output(result.stderr)
                energy_metrics = compute_energy_metrics(
                    power,
                    ollama_metrics.get("total_duration_s") or 0,
                    ollama_metrics.get("eval_count") or 0
                )

                base_row.update(ollama_metrics)
                base_row.update(stream_metrics)
                base_row.update(emc_metrics)
                base_row.update(hw_metrics)
                base_row.update(energy_metrics)
                base_row['status']        = 'success'
                base_row['error_message'] = ''

                print(f"[OK] eval_rate={ollama_metrics.get('eval_rate_tps')} tok/s | "
                      f"ttft={stream_metrics.get('ttft_real')} s | "
                      f"ram_max={hw_metrics.get('ram_used_max_mb')} MB")

            else:
                base_row['status']        = 'failure'
                base_row['error_message'] = clean_stderr(result.stderr)
                print(f"[FAIL] {base_row['error_message'][:120]}")

            writer.writerow(base_row)
            csvfile.flush()

            # Pausa entre testes
            cooldown = config.get('cooldown_between_tests_s', 5)
            print(f"[INFO] Aguardando {cooldown}s de cooldown...")
            time.sleep(cooldown)

    print("\n" + "="*60)
    print("Benchmark finalizado!")
    print(f"Resultados em: {output_file}")
    print("="*60)


if __name__ == "__main__":
    run_automated_benchmark()
