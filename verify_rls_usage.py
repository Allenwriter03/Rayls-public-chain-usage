"""
How much of Rayls Public Chain activity is real users?
Rebuilds every number in the article from Rayls explorer (Blockscout) exports.

Files expected in the same folder:
  stats.json, chart-txs.json, top-senders.json, top-senders-p2.json,
  bot-counters.json, bot-r1.json ... bot-r7.json,
  sender-b8ff.json, sender-e936.json, sender-e37f.json, sender-0002.json,
  sender-39f8.json, sender-31c1.json, my-tx.json, my-block.json
Run:  python verify_rls_usage.py      (standard library only)
"""
import json, glob, collections, datetime as dt

LO, HI = dt.date(2026, 10, 10), dt.date(2026, 11, 9)   # 31-day window (UTC)
ORACLE = "0x339d413ccefd986b1b3647a9cfa9cbbe70a30749"
PRICEFEED = "0x3c2269811836af69497e5f486a85d7316753cf62"
SENDERS = {  # file -> (address prefix, label)
    "sender-b8ff.json": ("0xb8ff", "LayerZero DVN (verifier)"),
    "sender-e936.json": ("0xe936", "LayerZero executor"),
    "sender-e37f.json": ("0xe37f", "calls CreditMessaging"),
    "sender-0002.json": ("0x0002", "approvals + one contract"),
    "sender-39f8.json": ("0x39f8", "two contracts"),
    "sender-31c1.json": ("0x31c1", "token transfers"),
}
# 4-byte selectors, matched by hashing the signatures (keccak256)
SEL = {
    "0x3161b7f6": "setPrice((uint32,(uint128,uint64,uint32))[])   [LayerZero PriceFeed]",
    "0xb143044b": "execute((uint32,address,bytes,uint256,bytes)[]) [LayerZero DVN]",
    "0x0894edf1": "commitVerification(bytes,bytes32)               [LayerZero executor]",
    "0xcfc32570": "execute302(...)                                 [LayerZero executor]",
    "0x7cd44734": "compose302(...)                                 [LayerZero executor]",
    "0x475b6d9e": "nativeDrop(...)                                 [LayerZero executor]",
}

load = lambda f: json.load(open(f))
day = lambda x: dt.datetime.fromtimestamp(int(x["timeStamp"]), dt.UTC).date()
inwin = lambda x: LO <= day(x) <= HI

# 1. Chain totals
stats = load("stats.json")
chart = {c["date"]: c["transactions_count"] for c in load("chart-txs.json")["chart_data"]}
win_total = sum(v for k, v in chart.items() if LO.isoformat() <= k <= HI.isoformat())
print("1. Chain totals (explorer)")
print(f"   all-time transactions: {int(stats['total_transactions']):,}   addresses: {int(stats['total_addresses']):,}")
print(f"   {LO} to {HI}: {win_total:,} transactions ({win_total/31:,.0f} a day)")

# 2. Biggest sender since launch
top = load("top-senders.json")["items"] + load("top-senders-p2.json")["items"]
o = int(top[0]["transactions_count"])
print("\n2. Biggest sender since launch")
print(f"   {top[0]['hash']}: {o:,} of {int(stats['total_transactions']):,} = {o/int(stats['total_transactions'])*100:.1f}%")
print(f"   next biggest: {top[1]['hash']} with {int(top[1]['transactions_count']):,}")
print(f"   oracle counters now: {int(load('bot-counters.json')['transactions_count']):,} transactions")

# 3. The oracle in the window
rows = []
for f in sorted(glob.glob("bot-r*.json")):
    r = load(f)["result"]
    assert len(r) < 10000, f + " hit the 10,000 cap"
    rows += r
own = [x for x in rows if x["from"].lower() == ORACLE and inwin(x)]
per_day = collections.Counter(day(x).isoformat() for x in own)
fees = [int(x["gasUsed"]) * int(x["gasPrice"]) / 1e18 for x in own]
shares = [per_day[d] / chart[d] * 100 for d in per_day]
print("\n3. The price oracle, last 31 days")
print(f"   transactions: {len(own):,} = {len(own)/win_total*100:.1f}% of all   failed: {sum(x['isError']!='0' for x in own)}")
print(f"   every call goes to PriceFeed: {all(x['to'].lower()==PRICEFEED for x in own)}")
for m, n in collections.Counter(x["methodId"] for x in own).most_common():
    print(f"   {m} x{n:,}  {SEL.get(m, '(setPriceForArbitrum, name from explorer)')}")
print(f"   daily share: lowest {min(shares):.1f}%  highest {max(shares):.1f}%")
print(f"   gas paid: {sum(fees):,.2f} USDr   average fee: {sum(fees)/len(fees):.6f} USDr")
for x in rows:
    if x["to"].lower() == ORACLE:
        print(f"   gas top-up: {int(x['value'])/1e18:.2f} USDr from {x['from']} on {day(x)}")
bn = [int(x["blockNumber"]) for x in own]

# 4. The next biggest senders
print("\n4. The next biggest senders, last 31 days")
others = 0
for f, (pre, label) in SENDERS.items():
    r = [x for x in load(f)["result"] if x["from"].lower().startswith(pre) and inwin(x)]
    others += len(r)
    m = collections.Counter(x["methodId"] for x in r).most_common(2)
    print(f"   {pre}  {len(r):>5,}  {label:<26} " + ", ".join(f"{k} x{v}" for k, v in m))
    if pre == "0xe936":
        pairs = min(sum(x["methodId"] == "0xcfc32570" for x in r), sum(x["methodId"] == "0x0894edf1" for x in r))
        print(f"          bridge messages delivered (commit + execute pairs): {pairs}")

# 4b. What the executor actually delivered (decode execute302 calldata)
word = lambda b, o: int.from_bytes(b[o:o + 32], "big")
RECEIVERS = {
    "0x674843c06ff83502ddb4d37c2e09c01cda38cbc8": "CreditMessaging (Stargate credit sync, protocol)",
    "0x3147be1cd913fe9ea5df7505ffe704a8313b20b0": "RLS OFT bridge (FeeAggregator.oftBridge)",
    "0x015fd589f4f1a33ce4487e12714e1b15129c9329": "Stargate-format token messages",
    "0xe56ddf65e311cddb71f69c0ac4d27e58b239d69a": "BRL1.p bridge (holds BRL1.p MINTER_ROLE)",
}
EID = {30101: "Ethereum", 30102: "BNB Chain", 30109: "Polygon", 30110: "Arbitrum", 30111: "Optimism",
       30184: "Base", 30106: "Avalanche"}   # LayerZero endpoint IDs; others shown as numbers
ex = [x for x in load("sender-e936.json")["result"]
      if x["from"].lower().startswith("0xe936") and inwin(x) and x["methodId"] == "0xcfc32570"]
by = collections.defaultdict(list)
for x in ex:
    b = bytes.fromhex(x["input"][10:]); t = word(b, 0)
    recv = "0x" + b[t + 12:t + 32].hex(); eid = word(b, t + 32)
    mo = t + word(b, t + 160); msg = b[mo + 32:mo + 32 + word(b, mo)]
    by[recv].append((eid, msg))
print("\n4b. Executor deliveries by destination, last 31 days")
for recv, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
    src = collections.Counter(EID.get(e, e) for e, _ in v).most_common(3)
    line = f"   {recv[:6]}…{recv[-4:]}  {len(v):>3}  {RECEIVERS.get(recv, '?'):<48} from {src}"
    if all(len(m) == 40 for _, m in v):   # OFT message: bytes32 to + uint64 amountSD (6 decimals)
        line += f"\n          {len({m[12:32] for _, m in v})} receiving wallets, {sum(int.from_bytes(m[32:40], 'big') for _, m in v)/1e6:,.2f} tokens"
    print(line)
KNOWN = {"0e301beef8daad28f8e38d9fce09112b78fe3161": "root admin, funds the staking reserve",
         "bbd0b35294fff3981a7aeb2adb14f23f93bf9662": "validator allowlisted on 15 Oct"}
rls = collections.Counter(); rls_n = collections.Counter()
for _, m in by["0x3147be1cd913fe9ea5df7505ffe704a8313b20b0"]:
    rls[m[12:32].hex()] += int.from_bytes(m[32:40], "big") / 1e6; rls_n[m[12:32].hex()] += 1
tot_rls = sum(rls.values())
print(f"   RLS bridge: top 5 receivers took {sum(v for _, v in rls.most_common(5)):,.0f} of {tot_rls:,.0f} RLS")
for w, tag in KNOWN.items():
    print(f"   0x{w[:4]}…{w[-4:]} ({tag}): {rls_n[w]} deliveries, {rls[w]:,.2f} RLS")
user_side = sum(len(v) for k, v in by.items() if not k.startswith("0x674843"))
print(f"   token transfers arriving: {user_side}   protocol credit messages: {len(by['0x674843c06ff83502ddb4d37c2e09c01cda38cbc8'])}")

# 4c. Why the verifier sends ~3 calls per message (decode DVN execute calldata)
dv = [x for x in load("sender-b8ff.json")["result"] if x["from"].lower().startswith("0xb8ff") and inwin(x)]
packets, per_dvn, other = collections.Counter(), collections.Counter(), collections.Counter()
for x in dv:
    if x["methodId"] != "0xb143044b":
        other[x["methodId"]] += 1; continue
    b = bytes.fromhex(x["input"][10:]); a = word(b, 0); base = a + 32
    for i in range(word(b, a)):
        t = base + word(b, base + 32 * i)
        co = t + word(b, t + 64); cd = b[co + 32:co + 32 + word(b, co)]
        if cd[:4].hex() != "0223536e":           # verify(bytes,bytes32,uint64) on ReceiveUln302
            other["non-verify param"] += 1; continue
        po = 4 + word(cd, 4); ph = cd[po + 32:po + 32 + word(cd, po)]
        packets[(ph[9:13], ph[13:45], ph[1:9])] += 1   # srcEid, sender, nonce
        per_dvn[x["to"]] += 1
print("\n4c. Verifier calls vs executor deliveries, last 31 days")
print(f"   verifier transactions: {len(dv)}   verifications decoded: {sum(per_dvn.values())}   unique messages: {len(packets)}")
print(f"   DVN contracts it submits to: {len(per_dvn)} -> " + ", ".join(f"{k[:6]}…{k[-4:]} x{v}" for k, v in per_dvn.items()))
print(f"   verifications per message: {set(packets.values())}   other calls: {dict(other)}")
lz = len(own) + others
rest = win_total - len(own) - others
print(f"   top 7 wallets: {len(own)+others:,} = {(len(own)+others)/win_total*100:.1f}%")
print(f"   everyone else: {rest:,} in 31 days = {rest/31:.0f} a day")
print(f"   window in blocks (first and last oracle call): {min(bn):,} to {max(bn):,}")
print(f"   blocks in window: about {max(bn)-min(bn):,}; blocks holding a transaction: at most {win_total/(max(bn)-min(bn))*100:.1f}%")
before = int(stats["total_transactions"]) - win_total
print(f"   30-day growth: {win_total:,} new on {before:,} = {win_total/before*100:.1f}%; without the oracle: {(win_total-len(own))/before*100:.1f}%")

# 5. My own transaction
t = load("my-tx.json")
b = load("my-block.json")["items"]
print("\n5. One real transaction (mine)")
print(f"   {t['hash']}")
print(f"   block {t['block_number']}  {t['timestamp']}  {t['result']}  confirmed in {t['confirmation_duration'][1]/1000:.3f}s")
print(f"   fee {int(t['fee']['value'])/1e18:.6f} USDr for {int(t['gas_used']):,} gas   transactions in its block: {len(b)}")
print(f"   vs the oracle's average fee: {sum(fees)/len(fees):.6f} USDr")

# 6. File fingerprints, so readers can confirm they have the same data
import hashlib
print("\n6. SHA-256 of every input file")
for f in sorted(glob.glob("*.json")):
    print(f"   {hashlib.sha256(open(f, 'rb').read()).hexdigest()}  {f}")
