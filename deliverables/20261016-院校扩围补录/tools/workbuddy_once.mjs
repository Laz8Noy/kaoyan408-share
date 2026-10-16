/**
 * One WorkBuddy gateway call from the currently logged-in desktop app.
 * Usage: node workbuddy_once.mjs <public-prompt.txt> <result.json>
 * The dynamically discovered endpoint and session token are never logged.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

const [promptFile, resultFile] = process.argv.slice(2);
if (!promptFile || !resultFile) {
  throw new Error('Usage: workbuddy_once.mjs <public-prompt.txt> <result.json>');
}
const bridgeRoot = process.env.WB_BRIDGE_ROOT || path.join(
  os.homedir(), '.dsh', 'profiles', 'desktop', 'node_modules',
  'workbuddy-codeg-bridge', 'src');
const { GatewayDiscovery } = await import(pathToFileURL(path.join(bridgeRoot, 'gateway.js')).href);
const { WorkBuddyAcpClient } = await import(pathToFileURL(path.join(bridgeRoot, 'acp_client.js')).href);
const home = process.env.WORKBUDDY_HOME || path.join(os.homedir(), '.workbuddy-ai');
const prompt = (await fs.readFile(promptFile, 'utf8')).trim();
if (!prompt) throw new Error('Prompt is empty');
const modelId = 'deepseek-v4.1-flash';
const started = new Date().toISOString();
let client;
const result = { started, model_requested: modelId, permission_mode: 'allow_once',
  prompt_file: path.relative(process.cwd(), path.resolve(promptFile)), success: false };
try {
  const gateway = await new GatewayDiscovery(home).discover();
  client = new WorkBuddyAcpClient(gateway, { permission_mode: 'allow_once' });
  await client.connect();
  const reply = await client.run({ prompt, cwd: process.cwd(), sessionId: null,
    timeoutSeconds: 240, modelId, thoughtLevel: 'disabled' });
  result.model_reported = reply.model_id;
  result.stop_reason = reply.stop_reason;
  result.text = reply.text || '';
  result.permissions = reply.permissions;
  result.success = reply.stop_reason === 'end_turn' && !!result.text.trim()
    && reply.model_id === modelId;
} catch (error) {
  result.error = String(error?.message || error);
} finally {
  if (client) await client.close().catch(() => {});
  result.finished = new Date().toISOString();
  await fs.mkdir(path.dirname(path.resolve(resultFile)), { recursive: true });
  await fs.writeFile(resultFile, JSON.stringify(result, null, 2) + '\n', 'utf8');
  process.stdout.write(JSON.stringify({ success: result.success, model: result.model_reported || null,
    stop: result.stop_reason || null, chars: (result.text || '').length,
    error: result.error || null }) + '\n');
  if (!result.success) process.exitCode = 1;
}
