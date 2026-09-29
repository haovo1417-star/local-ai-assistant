import urllib.request
import json

data = json.dumps({
    'model': 'qwen3:4b-q4_K_M',
    'messages': [{'role': 'user', 'content': 'Say 123'}],
    'stream': True
}).encode('utf-8')

req = urllib.request.Request(
    'http://localhost:11434/api/chat',
    data=data,
    headers={'Content-Type': 'application/json'}
)

with urllib.request.urlopen(req, timeout=10) as res:
    for line in res:
        chunk = json.loads(line.decode('utf-8'))
        content = chunk.get('message', {}).get('content', '')
        print(content, end='', flush=True)
print('\n[DONE STREAM TEST]')
