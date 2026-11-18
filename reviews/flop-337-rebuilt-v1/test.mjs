// Reconstructed v1: not the lost original runner. Synthetic public seed only.
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';import {join} from 'node:path';
import {Keyring} from '@polkadot/keyring';import {cryptoWaitReady} from '@polkadot/util-crypto';
import * as original from './generated/original.mjs';import * as candidate from './generated/candidate.mjs';
await cryptoWaitReady();
const seed='0x'+'11'.repeat(32); // Public fixture; NEVER fund or reuse.
const ed=new Keyring({type:'ed25519',ss58Format:42}).addFromUri(seed);
const sr=new Keyring({type:'sr25519',ss58Format:42}).addFromUri(seed);
assert.notDeepEqual(ed.publicKey,sr.publicKey);
let checks=0;const pass=name=>{checks++;console.log(`PASS ${checks}: ${name}`);};
for(const [type,pair] of [['ed25519',ed],['sr25519',sr]]) {
 const input=type+':'+seed,a=await candidate.agentSignerConfig(input),c=await candidate.createClient('mock://no-network',input);
 assert.equal(a.keypair.type,type);assert.deepEqual(a.keypair.publicKey,pair.publicKey);assert.equal(c.route,'pair');assert.deepEqual(c.pair.publicKey,pair.publicKey);
 pass(type+' identity and SDK keypair routing');
}
assert.deepEqual(await candidate.agentSignerConfig(seed),await original.agentSignerConfig(seed));
assert.deepEqual(await candidate.createClient('mock://no-network',seed),await original.createClient('mock://no-network',seed));
pass('unprefixed legacy parity');
await assert.rejects(candidate.agentSignerConfig('ed25519:'),/must not be empty/);
await assert.rejects(candidate.createClient('mock://no-network','sr25519:'),/must not be empty/);
pass('empty typed URI rejection');
await assert.rejects(candidate.sr25519KeyHex('ed25519:'+seed),/signed with sr25519/);
assert.equal(await candidate.sr25519KeyHex('ed25519:'+seed,false),undefined);
pass('DA sr25519-only required/optional policy');
assert.equal(await candidate.sr25519KeyHex('sr25519:'+seed),await original.sr25519KeyHex(seed));
pass('sr25519 DA byte parity (bytes not printed)');
const dir=await mkdtemp(join(tmpdir(),'flop337-public-fixture-'));
const envName='FLOP_337_REBUILT_FIXTURE_PASSWORD',oldEnv=process.env[envName];
process.env[envName]='public-fixture-password';
try {
 for(const pair of [ed,sr]) {
  const path=join(dir,pair.type+'.json');await writeFile(path,JSON.stringify(pair.toJson(process.env[envName])),{mode:0o600});
  const input='keystore:'+encodeURIComponent(path)+':'+envName;
  const a=await original.agentSignerConfig(input),c=await candidate.agentSignerConfig(input),client=await candidate.createClient('mock://no-network',input);
  assert.equal(c.keypair.type,pair.type);assert.deepEqual(c.keypair.publicKey,a.keypair.publicKey);assert.equal(client.route,'pair');assert.equal(client.pair.type,pair.type);assert.deepEqual(client.pair.publicKey,pair.publicKey);
  pass(pair.type+' encrypted keystore parity');
 }
} finally {await rm(dir,{recursive:true,force:true});if(oldEnv===undefined)delete process.env[envName];else process.env[envName]=oldEnv;}
assert.deepEqual(await candidate.createClient('mock://no-network'),await original.createClient('mock://no-network'));
pass('no-signer parity');assert.equal(checks,9);console.log('9 grouped checks PASS');
