#!/bin/bash

# Interrompe o script se ocorrer algum erro crítico
set -e

echo "================================================="
echo "   PREPARAÇÃO DE AMBIENTE BENCHMARK - JETSON"
echo "================================================="

# 1. Verifica e instala o Ollama
if ! command -v ollama &> /dev/null; then
    echo "[INFO] Ollama não encontrado. Iniciando instalação..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "[INFO] Ollama já está instalado."
fi

# Garante que o serviço do Ollama está rodando
echo "[INFO] Verificando serviço do Ollama..."
sudo systemctl start ollama || true
sleep 2

# 2. Lista de modelos para baixar
MODELS=(
    "deepseek-r1:1.5b"
    "gemma3:4b"
    "gemma3:1b"
    "llama3.2:1b"
    "llama3.2:3b"
)

echo "[INFO] Iniciando o download dos modelos..."
for model in "${MODELS[@]}"; do
    echo " -> Baixando $model..."
    ollama pull "$model"
done

# 3. Instala dependências do Python
echo "[INFO] Verificando e instalando dependências do Python (pyyaml, requests)..."
# Usa apt-get para garantir que o pip está instalado (comum não vir por padrão em algumas imagens)
sudo apt-get update -y > /dev/null 2>&1
sudo apt-get install -y python3-pip > /dev/null 2>&1

# Instala os pacotes necessários
pip3 install pyyaml requests

# 4. Libera RAM desativando a interface gráfica (Opcional, mas recomendado)
# Descomente a linha abaixo se quiser que o script mate a interface visual automaticamente
# echo "[INFO] Desativando interface gráfica para liberar VRAM..."
# sudo systemctl isolate multi-user.target

echo "================================================="
echo "[INFO] Ambiente pronto! Iniciando o Benchmark..."
echo "================================================="

# 5. Executa o script Python
sudo python3 analise.py
