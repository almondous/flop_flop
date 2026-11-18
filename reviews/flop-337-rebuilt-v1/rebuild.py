#!/usr/bin/env python3
"""Reconstructed v1, NOT recovery of the lost original artifact. Public npm only."""
import base64, hashlib, io, pathlib, subprocess, tarfile, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
SOURCE_SHA='c94d7d6bdfee094c401aa5accd04faf19e6d48fd925ffd934f962c2ceca1de40'
SRI='zFLbjNdWHgc6IGO0kqwtU57dNsX29XYDWaxhbe0DtRw4QPekRpvz0yb2m/1q6dtzfTFyGz+1RBK4ll4iDnpW3w=='
data=urllib.request.urlopen('https://registry.npmjs.org/@flop-labs/cli/-/cli-0.5.0.tgz', timeout=30).read()
assert base64.b64encode(hashlib.sha512(data).digest()).decode()==SRI,'tarball integrity mismatch'
with tarfile.open(fileobj=io.BytesIO(data)) as t: source=t.extractfile('package/dist/cli.js').read()
assert hashlib.sha256(source).hexdigest()==SOURCE_SHA,'bundle hash mismatch'
work=ROOT/'generated';work.mkdir(exist_ok=True)
(work/'cli.js').write_bytes(source)
subprocess.run(['patch','--batch','-p1','-i',str(ROOT/'candidate.patch')],cwd=work,check=True)
subprocess.run(['node','--check',str(work/'cli.js')],check=True)
for name,text in [('original',source.decode()),('candidate',(work/'cli.js').read_text())]:
 start=text.index('async function loadKeystore(') if name=='original' else text.index('function typedSigner(')
 end=text.index('// src/opts.ts',start)
 factory=text[start:end]
 assert factory.count('import("@flop-labs/sdk")')==2
 # Only the SDK boundary is replaced; real keyring/crypto/fs imports remain.
 factory=factory.replace('import("@flop-labs/sdk")','import("../sdk-stub.mjs")')
 (work/(name+'.mjs')).write_text(factory+'\nexport {loadKeystore, sr25519KeyHex, agentSignerConfig, createClient};\n')
print('Verified CLI 0.5.0; patch applied; full bundle syntax valid; helpers extracted.')
