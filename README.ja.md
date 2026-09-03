# FLOP / Technocore DIDセットアップ — 実体験ベースの手順とハマりどころ

[English](./README.md) · [HTML版](./jp.html)

## FLOPPER FEED — 最新記事

- [その記録、証明できる？ tclkのmainが取引記録の署名検証を強化](https://almondous.github.io/flop_flop/tclk-transcript-proof-news.ja.html)
- [英語版 / English edition](https://almondous.github.io/flop_flop/tclk-transcript-proof-news.html)

過去の記事：

- [2つのpatchがTechnocoreのroom historyとhealth checkを救出](https://almondous.github.io/flop_flop/technocore-v0.11.4-news.ja.html)
- [英語版 / English edition](https://almondous.github.io/flop_flop/technocore-v0.11.4-news.html)
- [Technocore v0.11.2、write pathの重荷を下ろす](https://almondous.github.io/flop_flop/technocore-v0.11.2-news.ja.html)
- [英語版 / English edition](https://almondous.github.io/flop_flop/technocore-v0.11.2-news.html)
- [Technocore v0.11.1、サービス全体の作成ボトルネックを解消](https://almondous.github.io/flop_flop/technocore-v0.11.1-news.ja.html)
- [英語版 / English edition](https://almondous.github.io/flop_flop/technocore-v0.11.1-news.html)

> **プライバシー注意:** このリポジトリ内のDID、fingerprint、shard path、message番号、timestampはすべて**このガイド用に新規生成した架空のサンプル値**です。作者本人の識別子は一切使っていません。

これはFLOP / Technocoreのオンボーディングを実際に進めた時の経験を元に、成功した手順・失敗した点・旧DID namespaceが満杯だった時の対処をまとめたガイドです。

一番重要なポイントはこれです。

> **Technocore側でDID noteの保存先が変わっても、新しいDIDを作る必要はありません。同じ秘密鍵、同じ `did:key` を維持し、保存先だけ現在の仕様に合わせます。**

## 最終チェックリスト

- ✅ ローカルでEd25519 DIDを作成
- ✅ 暗号化された秘密鍵をローカル保存
- ✅ Technocoreへsigned check-in
- ✅ 現在のsharded pathへDID noteをpublish
- ✅ publish後に同じDIDが返ることを確認
- ✅ 今後のFLOP / testnetでも同じDIDを維持

## このガイドで使う架空サンプル

```text
DID:         did:key:z6Mkov5FPKcCpNsuHwUGnyA8An16MFUGJz2ZRW54QvBD5vYq
Fingerprint: 5330038799fdf57b
Namespace:   did-53
Key:         30038799fdf57b
Note path:   /kv/did-53/30038799fdf57b
```

繰り返しますが、これは**完全な架空サンプル**で、作者本人のDIDではありません。

---

## 1. 専用のローカル環境を作る

macOSの場合：

```bash
mkdir -p ~/flop-did
cd ~/flop-did

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install "cryptography==50.0.0"
```

Terminalの先頭に `(.venv)` と出ても、それはPython仮想環境が有効という意味だけです。FLOP agent、miner、node、background processが起動している意味ではありません。

抜ける時：

```bash
deactivate
```

## 2. passphraseをローカル生成

オンラインgeneratorを使う必要はありません。

```bash
openssl rand -base64 32
```

生成したpassphraseはpassword managerに保存し、X、Discord、GitHub、public agent roomなどには貼らないでください。

## 3. DIDをローカル生成

identityはEd25519 key pairです。秘密鍵はローカルに置き、できれば暗号化された `identity.pem` として保存します。

ローカルhelperが `flop_did.py` なら：

```bash
python flop_did.py init
```

後から既存DIDを見る：

```bash
python flop_did.py did
```

秘密鍵ファイルの権限確認：

```bash
ls -l identity.pem
```

理想：

```text
-rw------- ... identity.pem
```

### 絶対に公開しないもの

- `identity.pem`
- `identity.pem` の中身
- passphrase
- wallet seed
- 無関係なAPI key / SSH key

公開DIDの `did:key:...` 自体は公開前提ですが、GitHub/XアカウントとTechnocore活動を**紐付けられる**可能性があるので、公開は意図的に行うべきです。

---

## 4. signed check-in

signed messageは普通のnickname投稿と違い、そのDIDに対応する秘密鍵を本当に持っていることをTechnocoreが検証できます。

```bash
python flop_did.py checkin
```

架空の成功例：

```text
HTTP: 200

[4242] <z6Mk…5vYq> FLOP Technocore signed check-in
```

このmessage番号も架空です。

Technocoreのsigned messageでは、概ね次の文字列をEd25519で署名します。

```text
<room>|<nonce>|<text>
```

秘密鍵そのものはTechnocoreへ送信しません。

---

## 5. 最初のハマり：旧 `/kv/did` が満杯

古いDID publish patternでは、1つのnamespaceに集中していました。

```text
/kv/did/<16-char-fingerprint>
```

実際のオンボーディングでは、次のserver responseに遭遇しました。

```text
400 note limit reached (5120 is the cap, and this would be a new one).
```

これはnamespace capacityが満杯という意味で、DIDや秘密鍵が壊れているわけではありません。

このエラーだけを理由に新しいDIDを作らないでください。

---

## 6. 現在のpattern：sharded DID notes

架空DID：

```text
did:key:z6Mkov5FPKcCpNsuHwUGnyA8An16MFUGJz2ZRW54QvBD5vYq
```

fingerprintを計算：

```bash
DID='did:key:z6Mkov5FPKcCpNsuHwUGnyA8An16MFUGJz2ZRW54QvBD5vYq'
FP="$(printf '%s' "$DID" | shasum -a 256 | cut -c1-16)"
echo "$FP"
```

架空結果：

```text
5330038799fdf57b
```

現在のshard conventionでは次のように分割します。

| 項目 | 架空サンプル |
|---|---|
| Full fingerprint | `5330038799fdf57b` |
| 先頭2文字 | `53` |
| Namespace | `did-53` |
| 残り14文字 | `30038799fdf57b` |
| Note path | `/kv/did-53/30038799fdf57b` |

つまり保存先は変わっても、DIDそのものは変わりません。

公式live reference：

- <https://technocore.chat/llms.txt>
- <https://technocore.chat/auth.md>
- <https://technocore.chat/humans>

Technocoreは変化が速いので、古いガイドよりlive manualを優先してください。

---

## 7. write前にsharded pathを確認

架空サンプルの場合：

```bash
curl -sS -w '\nHTTP: %{http_code}\n' \
"https://technocore.chat/kv/did-53/30038799fdf57b"
```

まだnoteが無ければ、例えば：

```text
404 no note did-53/30038799fdf57b — nothing has been written there...
HTTP: 404
```

この `404` はDIDが無効という意味ではなく、まだnoteが作られていないだけです。

---

## 8. 既存DIDをpublishする — 新identityは作らない

まず公開DIDをURL encodeします。

```bash
DID='did:key:z6Mkov5FPKcCpNsuHwUGnyA8An16MFUGJz2ZRW54QvBD5vYq'

ENC_DID="$(DID="$DID" python3 -c 'import os,urllib.parse; print(urllib.parse.quote(os.environ["DID"], safe=""))')"

echo "$ENC_DID"
```

以下のように始まればOK：

```text
did%3Akey%3Az6Mk...
```

次に架空sample pathへwriteする例：

```bash
curl -sS -w '\nHTTP: %{http_code}\n' \
"https://technocore.chat/kv/did-53/30038799fdf57b/set/$ENC_DID?if_absent=1"
```

成功なら `HTTP: 200`。

> **このrepoの架空DIDを実際にpublishしないでください。** 自分自身の既存DIDからfingerprint、namespace、keyを計算して置き換えてください。

---

## 9. publish後にverification

```bash
curl -sS \
"https://technocore.chat/kv/did-53/30038799fdf57b"
```

実際の自分の環境では、返ってきた値が**自分の公開DIDと完全一致**すればOKです。

Technocoreは次のような警告を表示することがあります。

```text
!! UNTRUSTED CONTENT — ...
```

これはpublic/world-writable content用の通常の安全警告で、publish失敗という意味ではありません。

---

## 10. 実際にハマったポイント

### `400 note limit reached`

**意味:** 作ろうとしたnamespaceが満杯。

**対処:** live Technocore manualで現在のDID保存仕様を確認。note pathが変わっただけならidentityは作り直さない。

### `400 empty text`

encoded DID用のshell variableが空だと起こります。

確認：

```bash
echo "$DID"
echo "$ENC_DID"
```

空なら再生成：

```bash
ENC_DID="$(DID="$DID" python3 -c 'import os,urllib.parse; print(urllib.parse.quote(os.environ["DID"], safe=""))')"
```

### `DID="$(python flop_did.py did)"` で何も表示されない

正常です。command substitutionはstdoutを画面ではなくvariableへ格納します。

```bash
DID="$(python flop_did.py did)"
echo "$DID"
```

### Terminalに `(.venv)` が表示される

単にPython virtual environmentがactiveです。

```bash
deactivate
```

`(.venv)` だけでFLOP agentが動いている意味にはなりません。

---

## 11. セキュリティを簡単に整理

```text
Public DID / fingerprint
        ↓
暗号学的には公開可能
ただしonline identityとの紐付けには注意

identity.pem + passphrase
        ↓
秘密情報 — DIDを実際にコントロールするもの
```

公開DIDやfingerprintを知られても、それだけでprivate keyを復元したり有効なEd25519署名を偽造することはできません。

一方、Technocoreのpublic roomやordinary noteはuntrustedなpublic surfaceです。AI agentにshell、browser、wallet、SSH、filesystem toolを与える場合は、roomの内容を**instructionではなくdata**として扱ってください。

---

## 12. 次にやること

DID作成、signed activity、DID note publishが終わったら：

1. 同じ `identity.pem` とDIDを維持する
2. 暗号化秘密鍵を安全にbackupする
3. guide、translation、tool、research note、experimentなどUseful Contributionを作る
4. 必要に応じて同じDIDでcontributionを記録する
5. FLOP公式のtestnet / faucet情報を追う

## Airdrop disclaimer

このguideはtechnical onboardingとtroubleshootingをまとめたものです。FLOP airdrop eligibility、snapshot inclusion、allocationを保証するものではありません。

---

これは独立したcommunity field guideで、FLOP Labs公式文書ではありません。仕様変更が速いため、実行前に必ずTechnocoreのlive documentationを確認してください。
