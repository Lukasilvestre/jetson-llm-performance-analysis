📊 Análise de Performance de LLMs na NVIDIA Jetson

<p align="center">
<img src="results/plots/benchmark_chart.png" alt="Gráfico de Benchmark de LLMs na Jetson" width="90%">
</p>

📜 Sobre o Projeto

Este repositório contém uma suíte de benchmark automatizada para analisar a performance de Modelos de Linguagem de Grande Escala (LLMs) na plataforma embarcada NVIDIA Jetson. O objetivo é fornecer dados quantitativos sobre como diferentes modelos se comportam sob restrições de hardware, especialmente ao variar os modos de consumo de energia e o uso de memória swap.

O projeto utiliza um script Python para automatizar a execução, a coleta de métricas e o armazenamento dos resultados, garantindo a reprodutibilidade dos testes.

🎯 Objetivos

    Automatizar o Benchmark: Executar testes de forma sistemática para diferentes LLMs e configurações de sistema.

    Analisar Modelos: Avaliar a performance de inferência (tokens/segundo) de modelos como Llama3, Gemma, DeepSeek e TinyLlama.

    Medir o Impacto do Hardware: Quantificar a influência dos modos de energia da Jetson e da ativação da memória swap.

    Coletar Dados Estruturados: Salvar todas as métricas de performance em um formato .csv para fácil análise e visualização.

🛠️ Stack de Tecnologias

    Hardware: NVIDIA Jetson (Orin, Xavier, etc.)

    Software: Python 3, Ollama

    Bibliotecas Python: PyYAML (para configuração), Pandas/Matplotlib (para análise e visualização de dados).

🚀 Como Executar o Benchmark

Para replicar esta análise, siga os passos abaixo.

Pré-requisitos

    Um dispositivo NVIDIA Jetson com JetPack instalado.

    Ollama instalado e funcionando no dispositivo. (Guia de instalação: https://ollama.com/)

Passos

    Clone o repositório:
    Bash

git clone https://github.com/Lukasilvestre/jetson-llm-performance-analysis.git
cd jetson-llm-performance-analysis

Instale as dependências Python:
Bash

pip install -r requirements.txt

Configure seus testes (opcional):
Edite o arquivo config.yaml para mudar os modelos a serem testados, o prompt, ou os modos de energia.

Execute o script de benchmark:
Bash

    python run_benchmark.py

    Siga as instruções no terminal: O script irá pausar e solicitar que você configure manualmente o modo de energia e o estado do swap antes de cada bateria de testes. Isso é crucial para garantir a precisão dos resultados.

📊 Resultados

Esta seção será preenchida com as conclusões após a análise do arquivo benchmark_results.csv gerado pelo script.

Exemplo de Tabela de Análise:
Modelo	Modo de Energia	Swap Ativado	Tokens/Segundo (eval_rate_tps)
gemma:2b	10W	Não	25.4
gemma:2b	MAXN	Não	38.1
llama3:8b	MAXN	Sim	11.2
llama3:8b	MAXN	Não	(Falhou ou muito lento)

Principais Conclusões Preliminares:

    Conclusão 1 sobre o impacto do modo de energia...

    Conclusão 2 sobre a necessidade de swap para modelos maiores...

    Conclusão 3 sobre qual modelo teve o melhor custo-benefício de performance...

📄 Licença

Este projeto está distribuído sob a licença MIT. Veja o arquivo LICENSE para mais detalhes.
