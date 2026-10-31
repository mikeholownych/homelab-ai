/** Exercise the installed Nexus client without starting an agent or modifying its checkout. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
const [clientPath, output] = process.argv.slice(2);
if (!clientPath || !output) throw new Error('usage: node qualify_nexus_client.mjs CLIENT_MODULE OUTPUT; JSON credentials on stdin');
process.on('warning', (warning) => { throw warning; });
let input = '';
for await (const part of process.stdin) input += part;
const { token, endpoint, release } = JSON.parse(input);
const { LocalLlmClient } = await import(pathToFileURL(clientPath).href);
const sha = (value) => crypto.createHash('sha256').update(value).digest('hex');
const record = { started_at: new Date().toISOString(), release_id: release, node: process.version,
  client_module_sha256: sha(fs.readFileSync(clientPath)), profile: 'installed Nexus client library; no agent loop', cases: [] };
const tools = [{ type: 'function', function: { name: 'lookup_service', description: 'Inspect service status on a host',
  parameters: { type: 'object', properties: { host: { type: 'string' }, service: { type: 'string' } }, required: ['host', 'service'] } } }];
try {
  for (const model of ['engineering/lead', 'engineering/deep']) {
    const client = new LocalLlmClient({ endpoint, apiKey: token, credentialOrigin: new URL(endpoint).origin,
      model, maxSteps: 1, temperature: 0, workspace: process.cwd(), shell: 'bash',
      readOnly: true, pinEndpoint: true, authorizedDisclosureOrigins: [new URL(endpoint).origin] });
    client.setOutputAllowance(128);
    const run = async (name, callback) => {
      const started = performance.now();
      try {
        const result = await callback();
        record.cases.push({ model, case: name, passed: result.passed, seconds: (performance.now() - started) / 1000,
          ...result.evidence });
      } catch (error) {
        record.cases.push({ model, case: name, passed: false, error_type: error.name, kind: error.kind });
      }
      fs.writeFileSync(output, JSON.stringify(record, null, 2) + '\n', { mode: 0o600 });
    };
    await run('model_discovery', async () => {
      const models = await client.listModels();
      return { passed: models.includes(model), evidence: { model_count: models.length } };
    });
    const messages = [{ role: 'user', content: `Qualification ${crypto.randomUUID()}: Reply with one word READY.` }];
    await run('exact_request_token_count', async () => {
      const count = await client.countRequestTokens(messages, [], crypto.randomUUID(), AbortSignal.timeout(40000));
      return { passed: typeof count.promptTokens === 'number' && count.promptTokens > 0,
        evidence: { count } };
    });
    await run('nonstream_completion', async () => {
      const answer = await client.chatCompletion(messages, [], crypto.randomUUID(), AbortSignal.timeout(40000));
      return { passed: typeof answer.content === 'string' && answer.content.length > 0,
        evidence: { answer_sha256: sha(JSON.stringify(answer)) } };
    });
    await run('stream_completion', async () => {
      const chunks = [];
      const answer = await client.chatCompletionStream(messages, [], (chunk) => chunks.push(chunk), crypto.randomUUID(), AbortSignal.timeout(40000));
      return { passed: typeof answer.content === 'string' && answer.content.length > 0 && chunks.length > 0,
        evidence: { callbacks: chunks.length, answer_sha256: sha(JSON.stringify(answer)) } };
    });
    await run('tool_call_and_result', async () => {
      const query = [{ role: 'user', content: `Qualification ${crypto.randomUUID()}: You must call lookup_service for host ai-5820-01 and service gateway. Do not answer from memory.` }];
      const answer = await client.chatCompletion(query, tools, crypto.randomUUID(), AbortSignal.timeout(40000));
      const call = answer.tool_calls?.[0];
      const args = call ? JSON.parse(call.function.arguments) : {};
      if (!call?.id || call.function.name !== 'lookup_service' || args.host !== 'ai-5820-01' || args.service !== 'gateway') return { passed: false, evidence: { answer_sha256: sha(JSON.stringify(answer)) } };
      const final = await client.chatCompletion([...query, answer, { role: 'tool', tool_call_id: call.id, content: '{"state":"active"}' },
        { role: 'user', content: 'Report the returned service state in one sentence. Do not call another tool.' }], tools, crypto.randomUUID(), AbortSignal.timeout(40000));
      return { passed: typeof final.content === 'string' && /active/i.test(final.content),
        evidence: { answer_sha256: sha(JSON.stringify(answer)), final_sha256: sha(JSON.stringify(final)) } };
    });
  }
} finally {
  record.finished_at = new Date().toISOString();
  record.passed = record.cases.length === 10 && record.cases.every((item) => item.passed);
  fs.writeFileSync(output, JSON.stringify(record, null, 2) + '\n', { mode: 0o600 });
}
console.log(JSON.stringify({ passed: record.passed, cases: record.cases.length }));
if (!record.passed) process.exitCode = 1;
