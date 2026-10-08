import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime, timezone, timedelta
import time

KST = timezone(timedelta(hours=9))

st.set_page_config(
    page_title="빗썸 핫월렛 잔액 조회",
    page_icon="💰",
    layout="wide"
)

st.title("🏦 빗썸 핫월렛 잔액 조회 대시보드")
st.markdown("---")

if 'coin_data' not in st.session_state:
    st.session_state.coin_data = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None
if 'last_refresh_time' not in st.session_state:
    st.session_state.last_refresh_time = time.time()


@st.cache_data(ttl=300)
def get_coin_list():
    try:
        ts = int(time.time() * 1000)
        url = f"https://gw.bithumb.com/exchange/v1/comn/intro?_={ts}&retry=0"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.bithumb.com/'
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('data') and data['data'].get('coinList'):
                d = {}
                for c in data['data']['coinList']:
                    if c.get('coinSymbol') and c.get('coinType'):
                        d[c['coinSymbol'].upper()] = c['coinType']
                return d
        return None
    except Exception as e:
        st.error(f"오류: {e}")
        return None


def get_deposit_info(coin_code):
    try:
        ts = int(time.time() * 1000)
        url = f"https://gw.bithumb.com/exchange/v1/trade/accumulation/deposit/{coin_code}-C0100?_={ts}&retry=0"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.bithumb.com/'
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('data'):
                return data['data']
        return None
    except Exception as e:
        st.error(f"입금 정보 조회 오류: {e}")
        return None


@st.cache_data(ttl=30)
def get_overseas_usdt_price(ticker):
    """해외 거래소 USDT 가격 (Binance → Bybit → OKX → Gate → MEXC)"""
    t = ticker.upper()

    # 1. Binance
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={t}USDT",
            timeout=5
        )
        if r.status_code == 200:
            p = float(r.json().get('price', 0))
            if p > 0:
                return p, "Binance"
    except Exception:
        pass

    # 2. Bybit
    try:
        r = requests.get(
            f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={t}USDT",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('retCode') == 0:
                lst = data.get('result', {}).get('list', [])
                if lst:
                    p = float(lst[0].get('lastPrice', 0))
                    if p > 0:
                        return p, "Bybit"
    except Exception:
        pass

    # 3. OKX
    try:
        r = requests.get(
            f"https://www.okx.com/api/v5/market/ticker?instId={t}-USDT",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('code') == '0':
                d = data.get('data', [])
                if d:
                    p = float(d[0].get('last', 0))
                    if p > 0:
                        return p, "OKX"
    except Exception:
        pass

    # 4. Gate.io
    try:
        r = requests.get(
            f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={t}_USDT",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                p = float(data[0].get('last', 0))
                if p > 0:
                    return p, "Gate.io"
    except Exception:
        pass

    # 5. MEXC
    try:
        r = requests.get(
            f"https://api.mexc.com/api/v3/ticker/price?symbol={t}USDT",
            timeout=5
        )
        if r.status_code == 200:
            p = float(r.json().get('price', 0))
            if p > 0:
                return p, "MEXC"
    except Exception:
        pass

    return None, None


@st.cache_data(ttl=60)
def get_dex_price(ticker):
    """DexScreener 검색 - 심볼 정확 매칭 + 유동성 1순위"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={ticker}"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        pairs = r.json().get('pairs', []) or []
        # 심볼이 정확히 일치하는 것만 필터
        t = ticker.upper()
        matches = [
            p for p in pairs
            if p.get('baseToken', {}).get('symbol', '').upper() == t
        ]
        # 최소 유동성 $10K 이상만 (스팸 풀 거름)
        matches = [
            p for p in matches
            if float((p.get('liquidity') or {}).get('usd') or 0) > 10000
        ]
        if not matches:
            return None
        # 유동성 큰 순 정렬
        matches.sort(
            key=lambda p: float((p.get('liquidity') or {}).get('usd') or 0),
            reverse=True
        )
        top = matches[0]
        price = float(top.get('priceUsd', 0))
        if price <= 0:
            return None
        return {
            'price': price,
            'chain': top.get('chainId', '?'),
            'dex': top.get('dexId', '?'),
            'pair': f"{top['baseToken']['symbol']}/{top['quoteToken']['symbol']}",
            'liquidity_usd': float((top.get('liquidity') or {}).get('usd') or 0),
        }
    except Exception:
        return None


def format_krw_short(amount):
    """원화 단위 축약: 조 / 억 / 만"""
    if amount >= 1e12:
        return f"₩{amount/1e12:,.2f}조"
    if amount >= 1e8:
        return f"₩{amount/1e8:,.2f}억"
    if amount >= 1e4:
        return f"₩{amount/1e4:,.0f}만"
    return f"₩{amount:,.0f}"


@st.cache_data(ttl=30)
def get_usdt_krw_price():
    """USDT/KRW 환율 (업비트 → 빗썸)"""
    try:
        r = requests.get(
            "https://api.upbit.com/v1/ticker?markets=KRW-USDT",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                return float(data[0]['trade_price']), "업비트"
    except Exception:
        pass

    try:
        r = requests.get(
            "https://api.bithumb.com/public/ticker/USDT_KRW",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('status') == '0000':
                return float(data['data']['closing_price']), "빗썸"
    except Exception:
        pass

    return 1380.0, "폴백"

# =====================================================================
# ⛓ 온체인 금고 조회 (2026.10 추가) — 빗썸 공개 숫자를 '보완'한다
# =====================================================================
# 왜 필요한가
#   위의 빗썸 공개 '입금 누적'(accumulationDepositAmt)은 실측해 보면
#   '금고 현재 잔고(들어온 것 − 나간 것)'와 같고, 10분쯤마다 바뀐다.
#   금고(입금이 모이는 지갑)를 블록체인에서 직접 보면
#   총 입금량 · 입금한 지갑 수 · 시간대별 유입을 바로바로 볼 수 있다.
#
# 금고를 찾는 법 (가스지갑 확인)
#   빗썸 입금주소는 코인을 금고로 보내려면 가스비가 필요하다. 그 가스비를
#   늘 같은 지갑(아래 gas_feeders)이 넣어준다. 그래서
#     "가스지갑에게 가스를 받은 주소들이 코인을 보낸 곳" = 빗썸 금고 다.
#
# ⚠️ 개인 입금주소는 화면에 절대 띄우지 않는다(다른 사람 지갑이다). 금고 주소만 보여준다.
import concurrent.futures

ONCHAIN_CHAINS = {
    # 빗썸 입금망 이름(net_type) → 체인 설정
    "ROBINHOOD": {
        "name": "Robinhood Chain",
        "cg": "robinhood",                       # 코인게코 플랫폼 id
        "rpcs": ["https://rpc.mainnet.chain.robinhood.com",
                 "https://rpc.ordofi.network"],
        "explorer": "https://robin.etherscan.io",
        "gas_feeders": ["0xf4fe70cdf6a46b3684676902cc84f9e74c425e3e"],
        # getLogs 한 번에 볼 블록 수 (노드 상한: topic 값 여러 개 10만 / 하나 200만, 결과 1만 건)
        "chunk": 1_500_000,
    },
}
# 이미 찾아둔 금고·컨트랙트 (찾는 시간을 아낀다. 없으면 자동으로 찾는다)
KNOWN_VAULTS = {
    ("ROBINHOOD", "PONS"): "0xcaad7987d6cbb1519a4629fa48d02262506e9850",
    ("ROBINHOOD", "CASHCAT"): "0x7a41ea709a89b2a5e7c6b1f52ab305349140af60",
}
KNOWN_CONTRACTS = {
    ("ROBINHOOD", "PONS"): "0x39dbed3a2bd333467115de45665cc57f813c4571",
    ("ROBINHOOD", "CASHCAT"): "0x020bfc650a365f8bb26819deaabf3e21291018b4",
}
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDR = "0x" + "0" * 40


def _rpc_post(rpcs, payload):
    """RPC 목록을 순서대로 시도. 응답(JSON)을 그대로 돌려준다."""
    last = None
    for url in rpcs:
        try:
            r = requests.post(url, json=payload, timeout=25,
                              headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)
    raise RuntimeError(f"RPC 연결 실패: {last}")


def _rpc_call(rpcs, method, params):
    res = _rpc_post(rpcs, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if isinstance(res, dict) and res.get("error"):
        raise RuntimeError(res["error"].get("message", "RPC 오류"))
    return res.get("result") if isinstance(res, dict) else None


def _hexint(v):
    try:
        return int(v, 16) if v not in (None, "", "0x") else 0
    except Exception:
        return 0


def _topic_addr(a):
    return "0x" + "0" * 24 + a.lower()[2:]


def _get_logs(rpcs, address, topics, lo, hi, chunk, deadline):
    """구간을 나눠 getLogs. '너무 많다' 고 거절당하면 구간을 반으로 줄여 다시 읽는다."""
    out, start, step = [], lo, chunk
    while start <= hi:
        if time.time() > deadline:
            raise RuntimeError("조회 시간 초과 (구간을 줄여 보세요)")
        end = min(hi, start + step - 1)
        flt = {"address": address, "topics": topics,
               "fromBlock": hex(start), "toBlock": hex(end)}
        try:
            out.extend(_rpc_call(rpcs, "eth_getLogs", [flt]) or [])
        except RuntimeError:
            if step > 500:
                step //= 2
                continue
            raise
        start = end + 1
        if step < chunk:
            step = min(chunk, step * 2)
    return out


@st.cache_data(ttl=300)
def bithumb_networks(ticker):
    """빗썸 입금망 목록 (예: ['ROBINHOOD'])"""
    try:
        r = requests.get(
            f"https://api.bithumb.com/public/assetsstatus/multichain/{ticker.upper()}",
            timeout=8)
        if r.status_code == 200 and r.json().get('status') == '0000':
            return [d.get('net_type', '').upper() for d in r.json().get('data', [])]
    except Exception:
        pass
    return []


@st.cache_data(ttl=600)
def chain_clock(chain_key):
    """(최신 블록, 그 시각, 블록당 초)"""
    rpcs = ONCHAIN_CHAINS[chain_key]["rpcs"]
    tip = _hexint(_rpc_call(rpcs, "eth_blockNumber", []))
    span = 50_000
    b1 = _rpc_call(rpcs, "eth_getBlockByNumber", [hex(tip), False])
    b0 = _rpc_call(rpcs, "eth_getBlockByNumber", [hex(tip - span), False])
    t1, t0 = _hexint(b1["timestamp"]), _hexint(b0["timestamp"])
    return tip, t1, max((t1 - t0) / span, 0.01)


def _tip_now(chain_key):
    """블록 간격은 캐시를 쓰고, 최신 블록만 새로 묻는다."""
    _, _, sec = chain_clock(chain_key)
    rpcs = ONCHAIN_CHAINS[chain_key]["rpcs"]
    tip = _hexint(_rpc_call(rpcs, "eth_blockNumber", []))
    return tip, time.time(), sec


def _token_symbol(rpcs, contract):
    try:
        raw = _rpc_call(rpcs, "eth_call", [{"to": contract, "data": "0x95d89b41"}, "latest"])
        b = bytes.fromhex(raw[2:])
        if len(b) >= 64:
            n = int.from_bytes(b[32:64], "big")
            return b[64:64 + n].decode(errors="ignore").strip()
        return b.rstrip(b"\x00").decode(errors="ignore").strip()
    except Exception:
        return ""


@st.cache_data(ttl=3600)
def token_contract(chain_key, ticker):
    """코인게코에서 그 체인의 컨트랙트를 찾고, 온체인 심볼로 한 번 더 확인한다.
    (티커가 같은 가짜 토큰이 검색 1위로 나오는 경우가 있다)"""
    t = ticker.upper()
    if (chain_key, t) in KNOWN_CONTRACTS:
        return KNOWN_CONTRACTS[(chain_key, t)], "등록값"
    cfg = ONCHAIN_CHAINS[chain_key]
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search",
                         params={"query": t}, timeout=8)
        for c in (r.json().get("coins") or [])[:5]:
            if (c.get("symbol") or "").upper() != t:
                continue
            d = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{c['id']}",
                params={"localization": "false", "tickers": "false",
                        "market_data": "false", "community_data": "false",
                        "developer_data": "false"}, timeout=8).json()
            addr = ((d.get("platforms") or {}).get(cfg["cg"]) or "").lower()
            if addr.startswith("0x") and _token_symbol(cfg["rpcs"], addr).upper() == t:
                return addr, "코인게코+온체인 심볼 확인"
    except Exception:
        pass
    return None, "못 찾음"


def _is_eoa(rpcs, addrs):
    """금고는 사람이 서명하는 일반 지갑(EOA)이다. DEX 풀·라우터(컨트랙트)를 걸러낸다."""
    if not addrs:
        return {}
    res = _rpc_post(rpcs, [{"jsonrpc": "2.0", "id": i, "method": "eth_getCode",
                            "params": [a, "latest"]} for i, a in enumerate(addrs)])
    code = {x.get("id"): x.get("result") for x in (res if isinstance(res, list) else [])}
    return {a: code.get(i) in ("0x", "0x0") for i, a in enumerate(addrs)}


def _gas_funded(rpcs, feeders, addr, sweep_block, back=500):
    """addr 이 sweep_block 직전에 가스지갑에게 가스를 받았나 (보통 300블록 전)."""
    top, lo = sweep_block, max(0, sweep_block - back)
    while top >= lo:
        bot = max(lo, top - 99)
        res = _rpc_post(rpcs, [{"jsonrpc": "2.0", "id": n, "method": "eth_getBlockByNumber",
                                "params": [hex(n), True]} for n in range(bot, top + 1)])
        for x in (res if isinstance(res, list) else []):
            for tx in ((x or {}).get("result") or {}).get("transactions") or []:
                if (str(tx.get("from", "")).lower() in feeders
                        and str(tx.get("to", "")).lower() == addr):
                    return True
        top = bot - 1
    return False


@st.cache_data(ttl=300, show_spinner=False)
def find_vault(chain_key, contract, hours):
    """빗썸 금고 찾기 → (금고주소 또는 None, 설명)"""
    cfg = ONCHAIN_CHAINS[chain_key]
    rpcs, feeders = cfg["rpcs"], set(cfg["gas_feeders"])
    tip, _, sec = _tip_now(chain_key)
    lo = max(0, tip - int(hours * 3600 / sec))
    logs = _get_logs(rpcs, contract, [TRANSFER_TOPIC], lo, tip, cfg["chunk"],
                     deadline=time.time() + 120)
    senders, first = {}, {}
    for lg in logs:
        try:
            frm = "0x" + lg["topics"][1][-40:]
            to = "0x" + lg["topics"][2][-40:]
        except Exception:
            continue
        if frm == ZERO_ADDR or to == ZERO_ADDR:
            continue
        senders.setdefault(to, set()).add(frm)
        k = (frm, to)
        bn = _hexint(lg.get("blockNumber"))
        if k not in first or bn < first[k]:
            first[k] = bn
    # ⚠️ 거래가 많은 코인은 위쪽을 DEX 풀·라우터(컨트랙트)가 다 차지한다
    #    (PONS 12시간: 이동 9.7만 건, 상위 12곳 중 10곳이 컨트랙트). 넉넉히 40곳을 본다.
    rank = sorted(senders.items(), key=lambda x: -len(x[1]))[:40]
    eoa = _is_eoa(rpcs, [a for a, _ in rank])
    cands = [(a, s) for a, s in rank if eoa.get(a) and len(s) >= 3][:4]
    if not cands:
        return None, f"최근 {hours}시간 동안 여러 지갑이 모이는 곳이 없다 (아직 입금 전일 수 있음)"
    # 후보를 하나씩: 입금지갑 4곳을 고르게 뽑아(처음·중간·끝) 동시에 가스지갑 확인.
    # 하나라도 맞으면 거기서 멈춘다(빗썸 가스지갑은 빗썸 입금주소에만 가스를 준다).
    for cand, ss in cands:
        order = sorted(ss, key=lambda s: first.get((s, cand), 0))
        pick = sorted({order[int(i * (len(order) - 1) / 3)] for i in range(4)})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            ok = list(ex.map(lambda s: _gas_funded(rpcs, feeders, s, first[(s, cand)]), pick))
        if any(ok):
            return cand, (f"가스지갑 확인 {sum(ok)}/{len(pick)} · "
                          f"입금지갑 {len(ss)}곳이 이 금고로 보냄")
    return None, (f"후보 {len(cands)}곳 모두 빗썸 가스지갑 확인 실패 "
                  f"(다른 거래소 금고일 수 있음)")


@st.cache_data(ttl=60, show_spinner=False)
def vault_stats(chain_key, contract, vault, hours):
    """금고로 들어온/나간 기록 → 총입금·지갑 수·시간대별 유입·잔고"""
    cfg = ONCHAIN_CHAINS[chain_key]
    rpcs = cfg["rpcs"]
    tip, now_ts, sec = _tip_now(chain_key)
    lo = max(0, tip - int(hours * 3600 / sec))
    dec = _hexint(_rpc_call(rpcs, "eth_call", [{"to": contract, "data": "0x313ce567"},
                                               "latest"])) or 18
    scale = 10 ** dec
    v = _topic_addr(vault)
    deadline = time.time() + 60
    ins = _get_logs(rpcs, contract, [TRANSFER_TOPIC, None, v], lo, tip, cfg["chunk"], deadline)
    outs = _get_logs(rpcs, contract, [TRANSFER_TOPIC, v], lo, tip, cfg["chunk"], deadline)
    bal = _hexint(_rpc_call(rpcs, "eth_call", [
        {"to": contract, "data": "0x70a08231" + v[2:]}, "latest"])) / scale

    def ts_of(bn):
        return now_ts - (tip - bn) * sec

    rows, wallets = [], set()
    for lg in ins:
        frm = "0x" + lg["topics"][1][-40:]
        if frm == ZERO_ADDR:
            continue
        wallets.add(frm)
        rows.append((ts_of(_hexint(lg["blockNumber"])), _hexint(lg["data"]) / scale))
    out_sum = sum(_hexint(lg["data"]) / scale for lg in outs
                  if "0x" + lg["topics"][2][-40:] != vault)
    out_n = sum(1 for lg in outs if "0x" + lg["topics"][2][-40:] != vault)
    df = pd.DataFrame(rows, columns=["ts", "qty"])
    return {
        "in_sum": float(df["qty"].sum()) if len(df) else 0.0,
        "in_n": len(df), "wallets": len(wallets),
        "out_sum": out_sum, "out_n": out_n, "balance": bal,
        "first_ts": float(df["ts"].min()) if len(df) else None,
        "last_ts": float(df["ts"].max()) if len(df) else None,
        "rows": rows, "asof": now_ts, "block": tip,
    }


def _usd_price(ticker):
    p, src = get_overseas_usdt_price(ticker)
    if p:
        return p, src
    dex = get_dex_price(ticker)
    if dex:
        return dex["price"], f"DEX {dex['dex']}"
    return None, None


def _fmt_qty(x):
    return f"{x:,.2f}".rstrip('0').rstrip('.') if x < 1000 else f"{x:,.0f}"


def _kst(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%m-%d %H:%M") if ts else "-"


def render_onchain(ticker, official_amount):
    st.markdown("---")
    st.subheader("⛓ 온체인 금고 (블록체인 직접 조회)")
    nets = bithumb_networks(ticker)
    chain_key = next((n for n in nets if n in ONCHAIN_CHAINS), None)
    if not chain_key:
        st.caption(f"이 코인의 빗썸 입금망({', '.join(nets) or '확인 안 됨'})은 아직 온체인 금고 조회를 "
                   f"지원하지 않습니다. 지원: "
                   + ", ".join(c["name"] for c in ONCHAIN_CHAINS.values()))
        return
    cfg = ONCHAIN_CHAINS[chain_key]

    o1, o2 = st.columns([1, 2])
    with o1:
        hours = st.selectbox("조회 기간", [6, 12, 24, 48, 72], index=2,
                             format_func=lambda h: f"최근 {h}시간", key="oc_hours")
    with o2:
        with st.expander("🔧 직접 입력 (자동으로 못 찾을 때)"):
            m_contract = st.text_input("토큰 컨트랙트", key="oc_contract").strip().lower()
            m_vault = st.text_input("금고 주소", key="oc_vault").strip().lower()

    try:
        if m_contract.startswith("0x") and len(m_contract) == 42:
            contract, c_src = m_contract, "직접 입력"
        else:
            contract, c_src = token_contract(chain_key, ticker)
        if not contract:
            st.warning(f"⚠️ {cfg['name']}에서 {ticker} 컨트랙트를 못 찾았습니다. 위 '직접 입력'에 넣어 주세요.")
            return

        if m_vault.startswith("0x") and len(m_vault) == 42:
            vault, v_src = m_vault, "직접 입력"
        elif (chain_key, ticker.upper()) in KNOWN_VAULTS:
            vault, v_src = KNOWN_VAULTS[(chain_key, ticker.upper())], "등록된 금고"
        else:
            # 금고 찾기는 최근 6시간만 본다(거래 많은 코인은 토큰 이동이 시간당 수천 건이라
            # 길게 보면 느려진다). 못 찾으면 조회 기간 전체로 한 번 더.
            with st.spinner("⛽ 빗썸 가스지갑으로 금고 찾는 중... (처음 한 번 30초~1분, 10분간 기억)"):
                vault, v_src = find_vault(chain_key, contract, min(hours, 6))
                if not vault and hours > 6:
                    vault, v_src = find_vault(chain_key, contract, hours)
        if not vault:
            st.info(f"🔎 금고를 아직 못 찾았습니다 — {v_src}")
            return

        with st.spinner("금고 입출금 기록 읽는 중..."):
            s = vault_stats(chain_key, contract, vault, hours)
    except Exception as e:
        st.error(f"온체인 조회 실패: {e}")
        return

    price, p_src = _usd_price(ticker)
    usdt_krw, _ = get_usdt_krw_price()

    def krw(q):
        return format_krw_short(q * price * usdt_krw) if price else "시세 없음"

    st.markdown(f"🏦 **빗썸 금고** [`{vault[:8]}…{vault[-6:]}`]({cfg['explorer']}/address/{vault}) "
                f"· {cfg['name']} · {v_src}")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(f"총 입금 ({hours}h)", _fmt_qty(s["in_sum"]))
        st.caption(f"{krw(s['in_sum'])} · {s['in_n']}건")
    with m2:
        st.metric("입금한 지갑 수", f"{s['wallets']:,}곳")
        st.caption(f"첫 입금 {_kst(s['first_ts'])} · 마지막 {_kst(s['last_ts'])}")
    with m3:
        st.metric("금고 현재 잔고", _fmt_qty(s["balance"]))
        st.caption(krw(s["balance"]))
    with m4:
        st.metric(f"금고에서 나감 ({hours}h)", _fmt_qty(s["out_sum"]))
        st.caption(f"{krw(s['out_sum'])} · {s['out_n']}건")

    # 빗썸 공개 숫자와 비교 — 공개 숫자 = 금고 잔고(입금 − 출금) 인지 확인
    if official_amount and s["balance"] > 0:
        diff = (official_amount / s["balance"] - 1) * 100
        if abs(diff) <= 3:
            st.success(f"✅ 빗썸 공개 숫자 {_fmt_qty(official_amount)} ≈ 금고 잔고 "
                       f"{_fmt_qty(s['balance'])} ({diff:+.1f}%) → 공개 숫자는 "
                       f"'들어온 것 − 나간 것'입니다. 실제 들어온 양은 위 '총 입금'을 보세요.")
        else:
            st.info(f"ℹ️ 빗썸 공개 숫자 {_fmt_qty(official_amount)} vs 금고 잔고 "
                    f"{_fmt_qty(s['balance'])} ({diff:+.1f}%) — 공개 숫자는 10분쯤마다 갱신돼 "
                    f"늦을 수 있고, 금고가 여러 개일 수도 있습니다.")

    if s["rows"]:
        df = pd.DataFrame(s["rows"], columns=["ts", "qty"])
        df["시각"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(KST) \
                     .dt.floor("10min").dt.tz_localize(None)
        per = df.groupby("시각")["qty"].sum()
        ch1, ch2 = st.columns(2)
        with ch1:
            st.caption("10분마다 들어온 양")
            st.bar_chart(per.rename("입금량"))
        with ch2:
            st.caption("누적 입금")
            st.line_chart(per.cumsum().rename("누적"))

    st.caption(f"⏱ 블록 {s['block']:,} 기준 · {_kst(s['asof'])} KST · 1분마다 새로 읽음"
               + (f" · 시세 {p_src} ${price:,.6f}" if price else ""))
    st.caption("ℹ️ 개인 입금주소는 표시하지 않습니다. 금고 주소만 보여줍니다.")


# 자동 새로고침 '1초 틱'은 화면을 다 그린 뒤 맨 아래에서 한다 (2026.10 수정)
#   전에는 사이드바 안에서 바로 st.rerun() 을 불러서, 아래 본문이 끝까지 그려지기 전에
#   매번 처음으로 돌아갔다 → 새로 받은 숫자가 화면에 안 바뀌는 문제가 있었다.
_tick_after_render = False

with st.sidebar:
    st.header("🔍 코인 검색")
    coin_dict = get_coin_list()

    if coin_dict:
        search_method = st.radio(
            "검색 방식 선택",
            ["티커로 검색", "목록에서 선택"]
        )
        selected_ticker = None

        if search_method == "티커로 검색":
            ticker_input = st.text_input(
                "코인 티커 입력 (예: BTC, ETH, XRP)",
                placeholder="BTC"
            ).upper()
            if ticker_input:
                if ticker_input in coin_dict:
                    selected_ticker = ticker_input
                    st.success(f"✅ {ticker_input} 코인을 찾았습니다!")
                else:
                    st.error(f"❌ {ticker_input} 코인을 찾을 수 없습니다.")
                    similar = [t for t in coin_dict.keys() if ticker_input in t]
                    if similar:
                        st.info(f"💡 혹시 이 코인? {', '.join(similar[:5])}")
        else:
            selected_ticker = st.selectbox(
                "코인 선택",
                options=sorted(coin_dict.keys()),
                index=None,
                placeholder="코인을 선택하세요"
            )

        if selected_ticker:
            coin_code = coin_dict[selected_ticker]
            st.info(f"📌 코인 코드: {coin_code}")
            if st.button("🔄 잔액 조회", type="primary", use_container_width=True):
                with st.spinner("조회 중..."):
                    deposit_data = get_deposit_info(coin_code)
                    if deposit_data:
                        st.session_state.coin_data = {
                            'ticker': selected_ticker,
                            'code': coin_code,
                            'data': deposit_data
                        }
                        st.session_state.last_update = datetime.now(KST)
                        st.session_state.last_refresh_time = time.time()
                        st.success("✅ 조회 완료!")
                    else:
                        st.error("❌ 데이터를 가져올 수 없습니다.")

    st.markdown("---")
    st.markdown("### ⚙️ 자동 새로고침 설정")
    auto_refresh = st.checkbox("자동 새로고침 활성화")

    if auto_refresh:
        refresh_interval = st.selectbox(
            "새로고침 주기",
            options=[30, 60, 120, 300, 600],
            format_func=lambda x: f"{x//60}분" if x >= 60 else f"{x}초",
            index=3
        )
        if st.session_state.coin_data:
            elapsed = time.time() - st.session_state.last_refresh_time
            remaining = refresh_interval - elapsed
            if remaining > 0:
                st.info(f"🔄 다음 새로고침: {int(remaining)}초 후")
                st.progress(elapsed / refresh_interval)
            else:
                st.info("🔄 새로고침 중...")
                st.session_state.last_refresh_time = time.time()
                coin_code = st.session_state.coin_data['code']
                deposit_data = get_deposit_info(coin_code)
                if deposit_data:
                    st.session_state.coin_data['data'] = deposit_data
                    st.session_state.last_update = datetime.now(KST)
                st.rerun()
            _tick_after_render = True


if st.session_state.coin_data:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(label="코인", value=st.session_state.coin_data['ticker'])
    with c2:
        st.metric(label="코인 코드", value=st.session_state.coin_data['code'])
    with c3:
        if st.session_state.last_update:
            st.metric(
                label="마지막 업데이트",
                value=st.session_state.last_update.strftime("%Y-%m-%d %H:%M:%S")
            )

    st.markdown("---")
    deposit_data = st.session_state.coin_data['data']
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("💰 입금 누적 금액")
        if 'accumulationDepositAmt' in deposit_data:
            amount = float(deposit_data['accumulationDepositAmt'])
            ticker = st.session_state.coin_data['ticker']

            st.metric(
                label=f"{ticker} 잔액",
                value=f"{amount:,.8f}".rstrip('0').rstrip('.')
            )

            usdt_price, usdt_source = get_overseas_usdt_price(ticker)
            usdt_krw, usdt_krw_source = get_usdt_krw_price()

            price_usd = None
            price_label = None
            extra_caption = None

            if usdt_price:
                price_usd = usdt_price
                price_label = f"{usdt_source} {ticker}/USDT"
            else:
                # 폴백: DexScreener
                dex = get_dex_price(ticker)
                if dex:
                    price_usd = dex['price']
                    price_label = f"DEX {dex['dex']} ({dex['chain']}) {dex['pair']}"
                    extra_caption = f"💧 풀 유동성: ${dex['liquidity_usd']:,.0f}"

            if price_usd:
                total_usd = amount * price_usd
                total_krw = total_usd * usdt_krw

                sub1, sub2 = st.columns(2)
                with sub1:
                    st.metric(label="원화 환산", value=format_krw_short(total_krw))
                    st.caption(f"💵 정확: ₩{total_krw:,.0f}")
                    st.caption(f"💱 {price_label}: ${price_usd:,.6f}")
                    st.caption(f"💱 {usdt_krw_source} USDT/KRW: ₩{usdt_krw:,.2f}")
                    if extra_caption:
                        st.caption(extra_caption)
                with sub2:
                    st.metric(label="달러 환산", value=f"${total_usd:,.2f}")
                    st.caption(f"💱 {price_label}: ${price_usd:,.6f}")
                    if extra_caption:
                        st.caption(extra_caption)
            else:
                st.warning(
                    f"⚠️ {ticker} 시세 없음 "
                    f"(CEX 5곳 + DexScreener 모두 매칭 실패)"
                )
        else:
            st.info("입금 정보가 없습니다.")

    with col2:
        st.subheader("📊 추가 정보")
        info_dict = {}
        for k, v in deposit_data.items():
            if k != 'accumulationDepositAmt' and v is not None:
                info_dict[k] = v
        if info_dict:
            for k, v in info_dict.items():
                st.text(f"{k}: {v}")
        else:
            st.info("추가 정보가 없습니다.")

    with st.expander("📋 Raw 데이터 보기"):
        st.json(deposit_data)

    # ⛓ 온체인 금고 (2026.10 추가) — 위 공개 숫자는 그대로 두고 아래에 덧붙인다
    render_onchain(
        st.session_state.coin_data['ticker'],
        float(deposit_data.get('accumulationDepositAmt') or 0)
    )

else:
    st.info("👈 왼쪽 사이드바에서 코인을 검색하여 핫월렛 잔액을 조회하세요.")

    with st.expander("📖 사용 방법"):
        st.markdown("""
        1. **코인 검색**: 왼쪽 사이드바에서 티커 입력 또는 목록 선택
        2. **잔액 조회**: '잔액 조회' 버튼 클릭
        3. **자동 새로고침**: 필요시 자동 새로고침 옵션 활성화
        """)

    st.subheader("🚀 인기 코인 빠른 조회")
    if coin_dict:
        popular = ['BTC', 'ETH', 'XRP', 'ADA', 'SOL', 'DOGE', 'MATIC', 'LINK']
        available = [c for c in popular if c in coin_dict]
        cols = st.columns(4)
        for idx, coin in enumerate(available[:8]):
            with cols[idx % 4]:
                if st.button(coin, use_container_width=True):
                    coin_code = coin_dict[coin]
                    with st.spinner(f"{coin} 조회 중..."):
                        deposit_data = get_deposit_info(coin_code)
                        if deposit_data:
                            st.session_state.coin_data = {
                                'ticker': coin,
                                'code': coin_code,
                                'data': deposit_data
                            }
                            st.session_state.last_update = datetime.now(KST)
                            st.session_state.last_refresh_time = time.time()
                            st.rerun()

st.markdown("---")
st.caption("💡 빗썸 입금 누적 데이터 + CEX(Binance/Bybit/OKX/Gate/MEXC) USDT 시세 + DexScreener DEX 폴백")
st.caption("⛓ 온체인 금고: 빗썸 가스지갑으로 찾은 금고의 입출금을 블록체인에서 직접 조회 (현재 Robinhood Chain)")
st.caption("⚠️ 정보는 참고용이며, 정확한 정보는 각 거래소 공식 사이트 확인.")

if _tick_after_render:
    time.sleep(1)
    st.rerun()

