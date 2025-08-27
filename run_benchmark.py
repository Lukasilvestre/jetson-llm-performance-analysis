# run_benchmark.py (versão modificada)
import subprocess
import yaml
import csv
import re
from datetime import datetime
import os

def parse_ollama_cli_output(stderr_output):
    """Analisa a saída de erro do Ollama para extrair métricas de desempenho."""
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
    """Executa o benchmark de forma automatizada com base no arquivo de configuração."""
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("ERRO: Arquivo 'config.yaml' não encontrado. Certifique-se de que ele existe no mesmo diretório.")
        return
    except Exception as e:
        print(f"ERRO ao ler ou interpretar o arquivo 'config.yaml': {e}")
        return

    # --- 1. Montar e exibir o plano de execução ---
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
        print(f"Teste {i}:")
        print(f"  - Modelo:          {test['model']}")
        print(f"  - Modo de Energia: {test['power_mode']}")
        print(f"  - Swap:            {test['swap']}")
    print("-"*60)
    
    # --- 2. Confirmação Única ---
    try:
        confirm = input("--> Revise o plano acima. Pressione Enter para iniciar todos os testes ou digite 'n' para cancelar: ")
        if confirm.lower() == 'n':
            print("Execução cancelada pelo usuário.")
            return
    except KeyboardInterrupt:
        print("\nExecução cancelada pelo usuário.")
        return

    # --- 3. Preparar arquivo de saída e executar os testes ---
    output_file = config['output_csv_file']
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    fieldnames = [
        'timestamp', 'model', 'power_mode', 'swap_enabled', 'status', 'error_message',
        'total_duration_s', 'load_duration_s', 'prompt_eval_count', 'prompt_eval_duration_s', 
        'prompt_eval_rate_tps', 'eval_count', 'eval_duration_s', 'eval_rate_tps'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for i, test in enumerate(test_plan, 1):
            model = test['model']
            power_mode = test['power_mode']
            swap = test['swap']
            
            print("\n" + "="*60)
            print(f"EXECUTANDO TESTE {i}/{len(test_plan)}:")
            print(f"  - Modelo:          {model}")
            print(f"  - Modo de Energia: {power_mode}")
            print(f"  - Swap:            {swap}")
            print("="*60)
            
            # Pausa para configuração manual
            #input(f"--> AÇÃO NECESSÁRIA: Configure manualmente o MODO DE ENERGIA para '{power_mode}' e o SWAP para '{swap}'.\n    Pressione Enter para iniciar este teste...")
            
            print(f"\nIniciando o comando para o modelo {model}. Isso pode levar alguns minutos...")
            
            command = ["ollama", "run", model, config['prompt'], "--verbose"]
            
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=600) # Timeout de 10 min
                
                base_row = {
                    'timestamp': datetime.now().isoformat(),
                    'model': model,
                    'power_mode': power_mode,
                    'swap_enabled': swap,
                }

                if result.returncode == 0:
                    metrics = parse_ollama_cli_output(result.stderr)
                    base_row.update(metrics)
                    base_row['status'] = 'success'
                    base_row['error_message'] = ''
                    writer.writerow(base_row)
                    print(f"--> SUCESSO: Teste com {model} concluído e resultados salvos.")
                else:
                    error_msg = result.stderr.strip().split('\n')[-1] # Pega a última linha do erro
                    base_row['status'] = 'failure'
                    base_row['error_message'] = error_msg
                    writer.writerow(base_row)
                    print(f"--> ERRO ao executar o teste com {model}. Detalhes salvos no CSV.")
                    print(f"    Erro: {error_msg}")

            except FileNotFoundError:
                print(f"--> ERRO CRÍTICO: O comando 'ollama' não foi encontrado. Verifique se ele está instalado e no PATH do sistema.")
                # Escreve o erro no CSV e para a execução
                base_row['status'] = 'failure'
                base_row['error_message'] = "Comando 'ollama' não encontrado."
                writer.writerow(base_row)
                break 
            except subprocess.TimeoutExpired:
                print(f"--> ERRO: O teste com o modelo {model} excedeu o tempo limite de 10 minutos e foi encerrado.")
                base_row['status'] = 'failure'
                base_row['error_message'] = 'TimeoutExpired (10 minutes)'
                writer.writerow(base_row)

            csvfile.flush() # Força a escrita dos dados no disco após cada teste

    print("\nBenchmark concluído! Todos os resultados foram salvos em:", output_file)

if __name__ == "__main__":
    run_automated_benchmark()
