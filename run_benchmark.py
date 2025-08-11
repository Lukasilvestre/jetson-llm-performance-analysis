# run_benchmark.py
from src.parsing_utils import parse_ollama_cli_output
import subprocess
import yaml
import csv
import re
from datetime import datetime
import os

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

def run_automated_benchmark():
  
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("ERRO: Arquivo 'config.yaml' não encontrado. Certifique-se de que ele existe no mesmo diretório.")
        return

    output_file = config['output_csv_file']
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    file_exists = os.path.isfile(output_file)
    with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'timestamp', 'model', 'power_mode', 'swap_enabled', 'total_duration_s', 'load_duration_s', 
            'prompt_eval_count', 'prompt_eval_duration_s', 'prompt_eval_rate_tps', 
            'eval_count', 'eval_duration_s', 'eval_rate_tps'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for model in config['models_to_test']:
            for power_mode in config['power_modes']:
                for swap in config['swap_configurations']:
                    print("\n" + "="*60)
                    print(f"Preparando para o próximo teste:")
                    print(f"  - Modelo:          {model}")
                    print(f"  - Modo de Energia: {power_mode}")
                    print(f"  - Swap:            {swap}")
                    print("="*60)
                    
                    input(f"--> AÇÃO NECESSÁRIA: Configure manualmente o MODO DE ENERGIA para '{power_mode}' e o SWAP para '{swap}'.\n    Pressione Enter para continuar o teste...")
                    
                    print(f"\nIniciando teste com o modelo {model}. Isso pode levar alguns minutos...")
                    
                    command = ["ollama", "run", model, config['prompt'], "--verbose"]
                    
                    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
                    
                    if result.returncode == 0:
                        metrics = parse_ollama_cli_output(result.stderr)
                        metrics.update({
                            'timestamp': datetime.now().isoformat(), 'model': model,
                            'power_mode': power_mode, 'swap_enabled': swap
                        })
                        writer.writerow(metrics)
                        print(f"--> SUCESSO: Teste com {model} concluído e resultados salvos.")
                    else:
                        print(f"--> ERRO ao executar o teste com {model}.")
                        print("    Saída de erro do Ollama:")
                        print(result.stderr)

    print("\nBenchmark concluído! Todos os resultados foram salvos em:", output_file)

if __name__ == "__main__":
    run_automated_benchmark()
