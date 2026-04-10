module.exports = {
  apps: [
    {
      name: 'vllm-model',
      script: '/opt/vllm-env/bin/python',
      args: '-m vllm.entrypoints.openai.api_server --model QuantTrio/gemma-4-26b-a4b-it-AWQ --quantization awq --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.85 --host 0.0.0.0 --port 8000 --served-model-name gemma-4-26b-a4b --trust-remote-code --enforce-eager',
      interpreter: 'none',
      cwd: '/root/gemma4-gateway',
      env: {
        PATH: '/opt/vllm-env/bin:/usr/local/bin:/usr/bin:/bin',
      }
    },
    {
      name: 'gemma-gateway',
      script: '/opt/vllm-env/bin/python',
      args: 'app/main.py',
      interpreter: 'none',
      cwd: '/root/gemma4-gateway',
      env: {
        PATH: '/opt/vllm-env/bin:/usr/local/bin:/usr/bin:/bin',
      }
    }
  ]
};
