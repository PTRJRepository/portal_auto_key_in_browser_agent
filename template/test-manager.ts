import { MultiAgentManager } from './apps/local-agent/src/runner/multi-agent-manager.js';

async function main() {
  console.log('Starting test...');
  const manager = new MultiAgentManager({ intervalMs: 500, maxConcurrent: 3, headless: true });

  process.on('SIGINT', () => {
    console.log('Received SIGINT');
    manager.stop();
  });

  const result = await manager.run(3);
  console.log('Final result:', result);
}

main().catch(e => console.error('Error:', e));