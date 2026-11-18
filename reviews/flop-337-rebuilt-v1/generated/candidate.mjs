function typedSigner(signer) {
  return typeof signer === "string" && /^(ed25519|sr25519):/.test(signer);
}
async function loadSigner(signer) {
  if (signer.startsWith("keystore:")) {
    const [, encodedPath, encodedEnv] = signer.split(":");
    return loadKeystore(decodeURIComponent(encodedPath), decodeURIComponent(encodedEnv));
  }
  const match = /^(ed25519|sr25519):(.*)$/s.exec(signer);
  const type = match?.[1] ?? "sr25519";
  const uri = match ? match[2] : signer;
  if (!uri) throw new Error("typed signer URI must not be empty");
  const [{ Keyring }, { cryptoWaitReady }] = await Promise.all([
    import("@polkadot/keyring"), import("@polkadot/util-crypto")
  ]);
  await cryptoWaitReady();
  return new Keyring({ type, ss58Format: 42 }).addFromUri(uri);
}
async function loadKeystore(path5, envName) {
  const password = process.env[envName];
  if (!password) throw new Error(`keystore password environment variable is unset: ${envName}`);
  const [{ readFile: readFile13 }, { Keyring: Keyring6 }, { cryptoWaitReady: cryptoWaitReady5 }] = await Promise.all([
    import("node:fs/promises"),
    import("@polkadot/keyring"),
    import("@polkadot/util-crypto")
  ]);
  await cryptoWaitReady5();
  const json = JSON.parse(await readFile13(path5, "utf8"));
  const keyring = new Keyring6({ type: json.encoding?.content?.[1] ?? "sr25519", ss58Format: 42 });
  const pair = keyring.addFromJson(json);
  pair.decodePkcs8(password);
  return pair;
}
async function sr25519KeyHex(signer, required = true) {
  const [{ Keyring: Keyring6 }, { decodePair }, { cryptoWaitReady: cryptoWaitReady5 }] = await Promise.all([
    import("@polkadot/keyring"),
    import("@polkadot/keyring/pair/decode"),
    import("@polkadot/util-crypto")
  ]);
  await cryptoWaitReady5();
  const [, encodedPath, encodedEnv] = signer.split(":");
  const pair = await loadSigner(signer);
  if (pair.type !== "sr25519") {
    if (!required) return void 0;
    throw new Error(`DA shard uploads are signed with sr25519; this signer is ${pair.type}`);
  }
  const { secretKey, publicKey } = decodePair(void 0, pair.encodePkcs8(), "none");
  return `0x${Buffer.from(secretKey).toString("hex")}${Buffer.from(publicKey).toString("hex")}`;
}
async function agentSignerConfig(signer) {
  const [, encodedPath, encodedEnv] = signer.split(":");
  return signer.startsWith("keystore:") || typedSigner(signer) ? { keypair: await loadSigner(signer) } : { signerUri: signer };
}
async function createClient(rpcUrl, signer) {
  const { FlopClient: FlopClient7 } = await import("../sdk-stub.mjs");
  if (signer?.startsWith("keystore:") || typedSigner(signer)) {
    const [, encodedPath, encodedEnv] = signer.split(":");
    return FlopClient7.createWithKeypair(
      rpcUrl,
      await loadSigner(signer)
    );
  }
  const opts = { endpoint: rpcUrl };
  if (signer) opts.signer = signer;
  return FlopClient7.create(opts);
}
async function createReadOnlyClient(rpcUrl) {
  const { connectFlopApi, FlopClient: FlopClient7 } = await import("../sdk-stub.mjs");
  const api = await connectFlopApi(rpcUrl);
  try {
    return FlopClient7.fromApiReadOnly(api);
  } catch (error) {
    await api.disconnect();
    throw error;
  }
}


export {loadKeystore, sr25519KeyHex, agentSignerConfig, createClient};
