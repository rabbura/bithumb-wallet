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

st.title("🏦 업비트 금고 온체인 조회 대시보드" if st.session_state.get("ex_mode") == "업비트"
         else "🏦 빗썸 핫월렛 잔액 조회 대시보드")
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
#   '빗썸 지갑들의 현재 잔고 합(들어온 것 − 나간 것)'과 같고, 10분쯤마다 바뀐다.
#   (PONS: 금고 하나 = 공개 숫자 -0.0% / ESP: 집금 + 출금핫 합 = -1.3% / ENA -1.2%)
#   빗썸 지갑을 블록체인에서 직접 보면 총 입금량 · 입금한 지갑 수 · 시간대별 유입을
#   바로바로 볼 수 있다.
#
# 빗썸 지갑을 찾는 법 (EVM 체인 전부)
#   ① 주소록: 상장추적기·복제핫·현선봇이 모은 빗썸 지갑 목록(bithumb_wallets.json)에서
#      이 코인을 들고 있는 지갑을 전부 찾아 더한다.
#   ② 주소록에 없는 새 금고(신규 상장): 최근 여러 지갑이 코인을 보낸 일반지갑(EOA)을
#      후보로 뽑고, 아래 중 하나로 확인한다.
#        - 그 후보 잔고를 더하면 빗썸 공개 숫자와 맞는다 (모든 EVM 체인)
#        - 입금주소가 빗썸 가스지갑에게 가스를 받았다 (가스지갑을 아는 체인)
#
# ⚠️ 개인 입금주소는 화면에 절대 띄우지 않는다(다른 사람 지갑이다). 빗썸 지갑만 보여준다.
import concurrent.futures
import os

TENDERLY = "https://{}.gateway.tenderly.co"
ONCHAIN_CHAINS = {
    # 빗썸 입금망 이름(net_type) → 체인 설정
    #   logs : getLogs 용 RPC (앞에서부터 시도) / bal : 잔고를 한 번에 여러 개 묻는 용
    #   chunk: getLogs 한 번에 볼 블록 수 (거절되면 자동으로 반씩 줄인다)
    #   sweep_feeders: 입금 한 건마다 가스를 넣어주는 빗썸 가스지갑 (금고 확인에 쓴다)
    #   ※ 2026.10.09 실측: 텐더리 공개 노드가 이더·아비·옵·폴리곤·아발란체를 넓게 받아준다.
    #     베이스(1천 블록)·BSC(5천 블록)는 좁아서 기간이 길면 '실제 N시간'까지만 읽힌다.
    "ETH": {"book": "ethereum", "name": "Ethereum", "cg": ["ethereum"], "sec": 12,
            "logs": [TENDERLY.format("mainnet"), "https://gateway.tenderly.co/public/mainnet",
                     "https://rpc.mevblocker.io", "https://ethereum-rpc.publicnode.com"],
            "bal": ["https://rpc.mevblocker.io", "https://ethereum-rpc.publicnode.com"],
            "explorer": "https://etherscan.io", "chunk": 50_000},
    "BSC": {"book": "binance-smart-chain", "name": "BNB Chain", "cg": ["binance-smart-chain"],
            "sec": 0.75,
            "logs": ["https://bsc-rpc.publicnode.com", "https://bsc.rpc.blxrbdn.com"],
            "bal": ["https://bsc-rpc.publicnode.com", "https://bsc.rpc.blxrbdn.com"],
            "explorer": "https://bscscan.com", "chunk": 5_000, "slow": True},
    "BASE_ETH": {"book": "base", "name": "Base", "cg": ["base"], "sec": 2,
                 # 텐더리는 1천 블록씩이지만 옛 구간도 준다(공개노드는 최근만) → 텐더리 먼저
                 "logs": [TENDERLY.format("base"), "https://base-rpc.publicnode.com"],
                 "bal": ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
                 "explorer": "https://basescan.org", "chunk": 1_000, "slow": True},
    "ARB_ETH": {"book": "arbitrum-one", "name": "Arbitrum", "cg": ["arbitrum-one"], "sec": 0.25,
                "logs": ["https://arb1.arbitrum.io/rpc", TENDERLY.format("arbitrum")],
                "bal": ["https://arbitrum-one.public.blastapi.io", "https://arb1.arbitrum.io/rpc"],
                "explorer": "https://arbiscan.io", "chunk": 100_000},
    "OP_ETH": {"book": "optimistic-ethereum", "name": "Optimism", "cg": ["optimistic-ethereum"],
               "sec": 2,
               "logs": [TENDERLY.format("optimism"), "https://mainnet.optimism.io"],
               "bal": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"],
               "explorer": "https://optimistic.etherscan.io", "chunk": 50_000},
    "POLYGON": {"book": "polygon-pos", "name": "Polygon", "cg": ["polygon-pos"], "sec": 2,
                "logs": [TENDERLY.format("polygon"), "https://polygon-bor-rpc.publicnode.com"],
                "bal": ["https://polygon-bor-rpc.publicnode.com", TENDERLY.format("polygon")],
                "explorer": "https://polygonscan.com", "chunk": 50_000},
    "AVAX": {"book": "avalanche", "name": "Avalanche C", "cg": ["avalanche"], "sec": 1,
             "logs": [TENDERLY.format("avalanche"),
                      "https://avalanche-c-chain-rpc.publicnode.com"],
             "bal": ["https://avalanche-c-chain-rpc.publicnode.com"],
             "explorer": "https://snowtrace.io", "chunk": 50_000},
    "KAIA": {"book": "kaia", "name": "Kaia", "cg": ["kaia", "klay-token"], "sec": 1,
             "logs": ["https://public-en.node.kaia.io"],
             "bal": ["https://public-en.node.kaia.io"],
             "explorer": "https://kaiascan.io", "chunk": 10_000},
    "ROBINHOOD": {"book": "robinhood", "name": "Robinhood Chain", "cg": ["robinhood"], "sec": 0.1,
                  "logs": ["https://rpc.mainnet.chain.robinhood.com", "https://rpc.ordofi.network"],
                  "bal": ["https://rpc.mainnet.chain.robinhood.com", "https://rpc.ordofi.network"],
                  "explorer": "https://robin.etherscan.io", "chunk": 1_500_000,
                  "sweep_feeders": ["0xf4fe70cdf6a46b3684676902cc84f9e74c425e3e"]},
}
# 빗썸이 같은 망을 다른 이름으로 부를 때
NET_ALIASES = {"ERC20": "ETH", "BEP20": "BSC", "BNB": "BSC", "BASE": "BASE_ETH",
               "ARB": "ARB_ETH", "ARBITRUM": "ARB_ETH", "OP": "OP_ETH", "OPTIMISM": "OP_ETH",
               "POL": "POLYGON", "MATIC": "POLYGON", "AVAX_C": "AVAX", "AVAXC": "AVAX",
               "KLAY": "KAIA"}
# 이미 찾아둔 금고·컨트랙트 (주소록에 아직 없을 때 여기 한 줄 넣으면 바로 뜬다)
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
MATCH_PCT = 5.0          # 공개 숫자와 이만큼(%) 안이면 '맞다'
MAX_FLOW_WALLETS = 20    # 입출금 기록을 볼 빗썸 지갑 수 상한 (잔고 큰 순)


def _rpc_post(rpcs, payload):
    """RPC 목록을 순서대로 시도. 정상 응답(JSON)을 그대로 돌려준다.
    배치(목록)를 보냈는데 오류 하나로 돌려주는 곳(배치 미지원)은 건너뛴다."""
    last = None
    for url in rpcs:
        try:
            r = requests.post(url, json=payload, timeout=25,
                              headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                continue
            res = r.json()
            if isinstance(payload, list) and not isinstance(res, list):
                last = str((res or {}).get("error", "배치 거부"))[:80]
                continue
            return res
        except Exception as e:
            last = str(e)[:80]
    raise RuntimeError(f"RPC 연결 실패: {last}")


def _rpc_call(rpcs, method, params):
    """오류가 오면 다음 RPC로 넘어간다 (노드마다 허용 범위가 다르다)."""
    last = None
    for url in rpcs:
        try:
            res = _rpc_post([url], {"jsonrpc": "2.0", "id": 1, "method": method,
                                    "params": params})
        except RuntimeError as e:
            last = str(e)
            continue
        if isinstance(res, dict) and res.get("error"):
            last = str(res["error"].get("message", "RPC 오류"))[:100]
            continue
        return res.get("result") if isinstance(res, dict) else None
    raise RuntimeError(last or "RPC 오류")


def _hexint(v):
    try:
        return int(v, 16) if v not in (None, "", "0x") else 0
    except Exception:
        return 0


def _topic_addr(a):
    return "0x" + "0" * 24 + a.lower()[2:]


def _get_logs(rpcs, address, topics, lo, hi, chunk, deadline):
    """최신 블록부터 거꾸로 나눠 읽는다 → (로그, 실제로 읽은 첫 블록).
    '너무 넓다'고 거절당하면 구간을 반으로 줄이고, 시간이 다 되거나 노드가 옛 구간을
    안 주면(아카이브 제한) 거기까지만 돌려준다 — 화면에 '실제 N시간'으로 정직하게 표시."""
    out, end, step = [], hi, chunk
    while end >= lo:
        if time.time() > deadline:
            return out, end + 1
        start = max(lo, end - step + 1)
        flt = {"address": address, "topics": topics,
               "fromBlock": hex(start), "toBlock": hex(end)}
        try:
            out.extend(_rpc_call(rpcs, "eth_getLogs", [flt]) or [])
        except RuntimeError:
            if step > 200:
                step = max(200, step // 2)
                continue
            return out, end + 1
        end = start - 1
    return out, lo


@st.cache_data(ttl=300)
def bithumb_networks(ticker):
    """빗썸 입금망 목록 (예: ['ETH'])"""
    try:
        r = requests.get(
            f"https://api.bithumb.com/public/assetsstatus/multichain/{ticker.upper()}",
            timeout=8)
        if r.status_code == 200 and r.json().get('status') == '0000':
            return [d.get('net_type', '').upper() for d in r.json().get('data', [])]
    except Exception:
        pass
    return []


def _chains_of(nets):
    """빗썸 입금망 중 지원하는 EVM 체인들 (WLD 처럼 이더+옵티미즘 등 여러 망으로 받는 코인이 있다)"""
    out = []
    for n in nets:
        k = NET_ALIASES.get(n, n)
        if k in ONCHAIN_CHAINS and k not in out:
            out.append(k)
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _load_book_raw():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bithumb_wallets.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


EXCHANGES = {"bithumb": {"name": "빗썸", "key": "chains"},
             "upbit": {"name": "업비트", "key": "upbit"}}


def load_book(ex="bithumb"):
    """거래소 지갑 주소록 (app.py 옆 bithumb_wallets.json) → (체인별 [주소, 라벨, 콜드], 기준시각).
    빗썸 = "chains", 업비트 = "upbit". 파일이 없으면 빈 목록 — 그래도 빗썸 새 금고 찾기는 돈다."""
    d = _load_book_raw()
    return d.get(EXCHANGES[ex]["key"], {}), d.get("_at", "")


@st.cache_data(ttl=3600, show_spinner=False)
def other_exchange_wallets(book_chain):
    """주소록의 다른 거래소 지갑 (새 금고 후보에서 뺀다 — 업비트 집금지갑을 빗썸으로 잡는 오탐 방지)"""
    s = (_load_book_raw().get("others") or {}).get(book_chain, "")
    return frozenset("0x" + s[i:i + 40] for i in range(0, len(s), 40))


@st.cache_data(ttl=600)
def chain_clock(chain_key):
    """블록당 초 (최근 블록들로 잰다. 못 재면 설정값)"""
    cfg = ONCHAIN_CHAINS[chain_key]
    try:
        tip = _hexint(_rpc_call(cfg["bal"], "eth_blockNumber", []))
        span = min(50_000, tip - 1)
        b1 = _rpc_call(cfg["bal"], "eth_getBlockByNumber", [hex(tip), False])
        b0 = _rpc_call(cfg["bal"], "eth_getBlockByNumber", [hex(tip - span), False])
        return max((_hexint(b1["timestamp"]) - _hexint(b0["timestamp"])) / span, 0.01)
    except Exception:
        return cfg["sec"]


def _tip_now(chain_key):
    """(최신 블록, 지금 시각, 블록당 초)"""
    sec = chain_clock(chain_key)
    tip = _hexint(_rpc_call(ONCHAIN_CHAINS[chain_key]["bal"], "eth_blockNumber", []))
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
def token_decimals(chain_key, contract):
    rpcs = ONCHAIN_CHAINS[chain_key]["bal"]
    return _hexint(_rpc_call(rpcs, "eth_call", [{"to": contract, "data": "0x313ce567"},
                                                "latest"])) or 18


@st.cache_data(ttl=3600, show_spinner=False)
def cg_platforms(ticker):
    """코인게코에서 심볼이 같은 코인들의 체인별 주소 목록.
    실패(429 등)는 예외로 올려서 캐시에 안 남긴다 — 실패를 1시간 기억하면 그동안 못 쓴다."""
    r = requests.get("https://api.coingecko.com/api/v3/search", params={"query": ticker},
                     timeout=8)
    if r.status_code != 200:
        raise RuntimeError(f"코인게코 응답 {r.status_code} (잠시 뒤 다시)")
    out = []
    for c in (r.json().get("coins") or [])[:5]:
        if (c.get("symbol") or "").upper() != ticker:
            continue
        d = requests.get(f"https://api.coingecko.com/api/v3/coins/{c['id']}",
                         params={"localization": "false", "tickers": "false",
                                 "market_data": "false", "community_data": "false",
                                 "developer_data": "false"}, timeout=8)
        if d.status_code != 200:
            raise RuntimeError(f"코인게코 응답 {d.status_code} (잠시 뒤 다시)")
        out.append(d.json().get("platforms") or {})
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def token_contract(chain_key, ticker):
    """그 체인의 토큰 컨트랙트. 코인게코 주소를 온체인 심볼로 한 번 더 확인한다
    (티커가 같은 가짜 토큰이 검색 1위로 나오는 경우가 있다). 못 찾으면 None."""
    t = ticker.upper()
    if (chain_key, t) in KNOWN_CONTRACTS:
        return KNOWN_CONTRACTS[(chain_key, t)]
    cfg = ONCHAIN_CHAINS[chain_key]
    for plats in cg_platforms(t):
        for pid in cfg["cg"]:
            addr = (plats.get(pid) or "").lower()
            if addr.startswith("0x") and _token_symbol(cfg["bal"], addr).upper() == t:
                return addr
    return None


def _balances(rpcs, contract, addrs, batch=100):
    """balanceOf 를 한 번에 여러 개. 빠진 것은 RPC 순서를 바꿔 한 번 더 묻는다."""
    out, todo = {}, list(addrs)
    for order in (rpcs, list(reversed(rpcs))):
        miss = []
        for i in range(0, len(todo), batch):
            part = todo[i:i + batch]
            try:
                res = _rpc_post(order, [{"jsonrpc": "2.0", "id": j, "method": "eth_call",
                                         "params": [{"to": contract, "data": "0x70a08231"
                                                     + _topic_addr(a)[2:]}, "latest"]}
                                        for j, a in enumerate(part)])
            except RuntimeError:
                res = []
            got = set()
            for x in res:
                j = x.get("id") if isinstance(x, dict) else None
                if isinstance(j, int) and 0 <= j < len(part) and "result" in x:
                    out[part[j]] = _hexint(x["result"])
                    got.add(j)
            miss += [a for j, a in enumerate(part) if j not in got]
        todo = miss
        if not todo:
            break
    return out, len(todo)


@st.cache_data(ttl=60, show_spinner=False)
def book_holders(chain_key, contract, extra=(), ex="bithumb"):
    """주소록의 거래소 지갑 중 이 코인을 가진 곳 → ([(주소, 라벨, 콜드, 수량)], 조회 수, 못 읽은 수)"""
    cfg = ONCHAIN_CHAINS[chain_key]
    book, _ = load_book(ex)
    rows = {a: (lab, cold) for a, lab, cold in book.get(cfg["book"], [])}
    for a in extra:
        rows.setdefault(a.lower(), ("등록/직접 입력 금고", False))
    if not rows:
        return [], 0, 0
    scale = 10 ** token_decimals(chain_key, contract)
    bals, miss = _balances(cfg["bal"], contract, list(rows))
    out = [(a, rows[a][0], rows[a][1], v / scale) for a, v in bals.items() if v > 0]
    out.sort(key=lambda r: -r[3])
    return out, len(rows), miss


def _is_eoa(rpcs, addrs):
    """빗썸 지갑은 사람이 서명하는 일반 지갑(EOA)이다. DEX 풀·라우터(컨트랙트)를 걸러낸다."""
    if not addrs:
        return {}
    res = _rpc_post(rpcs, [{"jsonrpc": "2.0", "id": i, "method": "eth_getCode",
                            "params": [a, "latest"]} for i, a in enumerate(addrs)])
    code = {x.get("id"): x.get("result") for x in (res if isinstance(res, list) else [])}
    return {a: code.get(i) in ("0x", "0x0") for i, a in enumerate(addrs)}


def _gas_funded(rpcs, feeders, addr, sweep_block, back=500):
    """addr 이 sweep_block 직전에 가스지갑에게 가스를 받았나 (로빈후드: 보통 300블록 전)."""
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
def fanin_candidates(chain_key, contract, hours, skip=()):
    """최근 hours 동안 여러 지갑이 코인을 보낸 일반지갑(EOA) 후보.
    → ([{addr, senders, bal, gas}], 실제로 본 시간)
       gas: True=빗썸 가스지갑 확인 / None=가스지갑 모르는 체인(잔고로 확인)"""
    cfg = ONCHAIN_CHAINS[chain_key]
    feeders = set(cfg.get("sweep_feeders") or [])
    others = other_exchange_wallets(cfg["book"])
    tip, _, sec = _tip_now(chain_key)
    lo = max(0, tip - int(hours * 3600 / sec))
    logs, got_lo = _get_logs(cfg["logs"], contract, [TRANSFER_TOPIC], lo, tip, cfg["chunk"],
                             deadline=time.time() + 40)
    seen_h = (tip - got_lo) * sec / 3600
    senders, first = {}, {}
    for lg in logs:
        try:
            frm = "0x" + lg["topics"][1][-40:]
            to = "0x" + lg["topics"][2][-40:]
        except Exception:
            continue
        if frm == ZERO_ADDR or to == ZERO_ADDR or to in skip or to in others:
            continue
        senders.setdefault(to, set()).add(frm)
        k = (frm, to)
        bn = _hexint(lg.get("blockNumber"))
        if k not in first or bn < first[k]:
            first[k] = bn
    # ⚠️ 거래가 많은 코인은 위쪽을 DEX 풀·라우터(컨트랙트)가 다 차지한다
    #    (PONS 12시간: 이동 9.7만 건, 상위 12곳 중 10곳이 컨트랙트). 넉넉히 40곳을 본다.
    rank = sorted(senders.items(), key=lambda x: -len(x[1]))[:40]
    eoa = _is_eoa(cfg["bal"], [a for a, _ in rank])
    cands = [(a, s) for a, s in rank if eoa.get(a) and len(s) >= 3][:6]
    if not cands:
        return [], seen_h
    scale = 10 ** token_decimals(chain_key, contract)
    bals, _ = _balances(cfg["bal"], contract, [a for a, _ in cands])
    out = [{"addr": a, "senders": len(s), "bal": bals.get(a, 0) / scale,
            "gas": None if not feeders else False} for a, s in cands]
    if feeders:
        # 후보를 하나씩: 입금지갑 4곳을 고르게 뽑아(처음·중간·끝) 동시에 가스지갑 확인.
        # 하나라도 맞으면 거기서 멈춘다(빗썸 가스지갑은 빗썸 입금주소에만 가스를 준다).
        for c, (cand, ss) in zip(out, cands):
            order = sorted(ss, key=lambda s: first.get((s, cand), 0))
            pick = sorted({order[int(i * (len(order) - 1) / 3)] for i in range(4)})
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                ok = list(ex.map(lambda s: _gas_funded(cfg["bal"], feeders, s,
                                                       first[(s, cand)]), pick))
            if any(ok):
                c["gas"] = True
                break
    return out, seen_h


def vault_flows(chain_key, contract, wallets, hours, ex="bithumb"):
    """느린 체인(BSC·베이스: 한 번 읽는 데 30초~2분)은 5분, 나머지는 1분마다 새로 읽는다.
    (자동 새로고침을 켜도 느린 체인이 계속 '읽는 중'에 머물지 않게)"""
    if ONCHAIN_CHAINS[chain_key].get("slow"):
        return _vault_flows_slow(chain_key, contract, wallets, hours, ex)
    return _vault_flows_fast(chain_key, contract, wallets, hours, ex)


@st.cache_data(ttl=60, show_spinner=False)
def _vault_flows_fast(chain_key, contract, wallets, hours, ex):
    return _vault_flows(chain_key, contract, wallets, hours, ex)


@st.cache_data(ttl=300, show_spinner=False)
def _vault_flows_slow(chain_key, contract, wallets, hours, ex):
    return _vault_flows(chain_key, contract, wallets, hours, ex)


def _vault_flows(chain_key, contract, wallets, hours, ex):
    """거래소 지갑들로 들어온/나간 기록 (그 거래소 지갑끼리 옮긴 것은 뺀다)
    → 총입금·지갑 수·시간대별 유입·나감, 실제로 본 시간"""
    cfg = ONCHAIN_CHAINS[chain_key]
    tip, now_ts, sec = _tip_now(chain_key)
    lo = max(0, tip - int(hours * 3600 / sec))
    scale = 10 ** token_decimals(chain_key, contract)
    # 내부 이동 = 주소록의 그 거래소 지갑 전부(콜드 포함). 조회하는 상위 20곳끼리만 빼면
    #   콜드→핫 보충이 '총 입금'으로 잡혀 오래된 코인의 입금이 부풀었다 (10/9 리뷰)
    W = set(wallets) | {r[0] for r in load_book(ex)[0].get(cfg["book"], [])}
    tw = [_topic_addr(a) for a in wallets]
    deadline = time.time() + 40
    ins, lo_in = _get_logs(cfg["logs"], contract, [TRANSFER_TOPIC, None, tw], lo, tip,
                           cfg["chunk"], deadline)
    outs, lo_out = _get_logs(cfg["logs"], contract, [TRANSFER_TOPIC, tw], lo, tip,
                             cfg["chunk"], max(deadline, time.time() + 20))
    got_lo = max(lo_in, lo_out)

    def ts_of(bn):
        return now_ts - (tip - bn) * sec

    rows, senders = [], set()
    for lg in ins:
        frm = "0x" + lg["topics"][1][-40:]
        bn = _hexint(lg["blockNumber"])
        if frm == ZERO_ADDR or frm in W or bn < got_lo:
            continue
        senders.add(frm)
        rows.append((ts_of(bn), _hexint(lg["data"]) / scale))
    out_sum, out_n = 0.0, 0
    for lg in outs:
        to = "0x" + lg["topics"][2][-40:]
        if to in W or _hexint(lg["blockNumber"]) < got_lo:
            continue
        out_sum += _hexint(lg["data"]) / scale
        out_n += 1
    df = pd.DataFrame(rows, columns=["ts", "qty"])
    return {
        "in_sum": float(df["qty"].sum()) if len(df) else 0.0,
        "in_n": len(df), "wallets": len(senders),
        "out_sum": out_sum, "out_n": out_n,
        "first_ts": float(df["ts"].min()) if len(df) else None,
        "last_ts": float(df["ts"].max()) if len(df) else None,
        "rows": rows, "asof": now_ts, "block": tip,
        "seen_h": (tip - got_lo) * sec / 3600,
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


def _short(a):
    return f"{a[:8]}…{a[-6:]}"


def render_onchain(ticker, official_amount, ex="bithumb"):
    """ex: "bithumb" = 빗썸 (공개 숫자 비교 + 새 금고 찾기) / "upbit" = 업비트 (주소록만)"""
    X = EXCHANGES[ex]["name"]
    st.markdown("---")
    st.subheader(f"⛓ {X} 온체인 금고 (블록체인 직접 조회)")
    if ex == "bithumb":
        nets = bithumb_networks(ticker)
        chains = _chains_of(nets)
        if not chains:
            st.caption(f"이 코인의 빗썸 입금망({', '.join(nets) or '확인 안 됨'})은 EVM 체인이 아니라 "
                       f"아직 온체인 조회를 지원하지 않습니다. 지원: "
                       + ", ".join(c["name"] for c in ONCHAIN_CHAINS.values()))
            return
    else:
        # 업비트는 입금망 공개 API가 없다 → 주소록에 업비트 지갑이 있는 EVM 체인을 전부 본다
        ubook = load_book(ex)[0]
        chains = [k for k, c in ONCHAIN_CHAINS.items() if ubook.get(c["book"])]
        if not chains:
            st.warning("⚠️ 주소록에 업비트 지갑이 없습니다. export_bithumb_wallets.py 로 "
                       "bithumb_wallets.json 을 새로 만들어 GitHub에 올려 주세요.")
            return
    t = ticker.upper()
    first = ONCHAIN_CHAINS[chains[0]]

    o1, o2 = st.columns([1, 2])
    with o1:
        hours = st.selectbox("조회 기간", [6, 12, 24, 48, 72], index=2,
                             format_func=lambda h: f"최근 {h}시간", key="oc_hours")
    with o2:
        with st.expander("🔧 직접 입력 (자동으로 못 찾을 때)"):
            st.caption(f"{first['name']} 기준으로 넣어 주세요.")
            m_contract = st.text_input("토큰 컨트랙트", key="oc_contract").strip().lower()
            m_vault = st.text_input("금고 주소", key="oc_vault").strip().lower()
    m_contract = m_contract if m_contract.startswith("0x") and len(m_contract) == 42 else ""
    m_vault = m_vault if m_vault.startswith("0x") and len(m_vault) == 42 else ""
    off = official_amount or 0

    try:
        # ① 주소록: EVM 망마다, 그 거래소 지갑 중 이 코인을 가진 곳을 전부 찾는다
        per, errs = [], []
        with st.spinner(f"📒 {X} 지갑 주소록에서 이 코인 보유량 확인 중..."):
            for ck in chains:
                try:
                    c = m_contract if (ck == chains[0] and m_contract) else token_contract(ck, t)
                    if not c:
                        continue
                    extra = [m_vault] if (ck == chains[0] and m_vault) else []
                    if ex == "bithumb" and (ck, t) in KNOWN_VAULTS:
                        extra.append(KNOWN_VAULTS[(ck, t)])
                    holders, n_book, n_miss = book_holders(ck, c, tuple(extra), ex)
                    per.append({"ck": ck, "contract": c, "holders": holders,
                                "n_book": n_book, "n_miss": n_miss,
                                "hot": sum(h[3] for h in holders if not h[2])})
                except Exception as e:
                    errs.append(f"{ONCHAIN_CHAINS[ck]['name']}: {str(e) or type(e).__name__}")
        if not per:
            st.warning(f"⚠️ {t} 토큰 컨트랙트를 못 찾았습니다 (체인 기본 코인이거나 코인게코에 "
                       f"주소가 없음). 위 '직접 입력'에 넣어 주세요."
                       + (f" — {'; '.join(errs)}" if errs else ""))
            return
        hot_sum = sum(p["hot"] for p in per)
        main = max(per, key=lambda p: p["hot"])
        ck, contract = main["ck"], main["contract"]
        cfg = ONCHAIN_CHAINS[ck]

        # ② 주소록으로 공개 숫자가 설명 안 되면 → 그 체인에서 새 금고 찾기
        found, found_how = None, ""
        gap_pct = (hot_sum / off - 1) * 100 if off else 0
        # 업비트는 공개 숫자도 가스지갑도 없어 확인할 방법이 없다 → 찾지 않는다 (오탐 방지)
        need_find = ex == "bithumb" and (
            (off > 0 and gap_pct < -MATCH_PCT) or (hot_sum == 0 and cfg.get("sweep_feeders")))
        if need_find:
            skip = tuple(h[0] for h in main["holders"])
            with st.spinner("🔎 주소록에 없는 빗썸 금고 찾는 중... (처음 한 번 30초~1분, 5분간 기억)"):
                h1 = min(hours, 6)
                pool, seen1 = fanin_candidates(ck, contract, h1, skip)
                pool = list(pool)
                # 6시간을 다 읽었는데도 못 찾았을 때만 조회 기간 전체로 한 번 더
                #   (6시간도 다 못 읽는 체인이면 길게 봐도 소용없고 느리기만 하다)
                if hours > h1 and seen1 >= h1 * 0.97 and not any(c["gas"] for c in pool):
                    more, _ = fanin_candidates(ck, contract, hours, skip)
                    pool += [c for c in more if c["addr"] not in {p["addr"] for p in pool}]
            for c in pool:
                if c["gas"]:
                    found, found_how = c, "빗썸 가스지갑 확인"
                    break
            if not found and off > 0:
                # 잔고로 확인: 더하면 공개 숫자와 맞고(±5%), 원래 차이가 절반 이하로 줄어야 한다.
                #   (ONDO 실측: 주소록 -5.8% 에 업비트 집금지갑을 더하니 -4.5% — 겨우 5% 안에
                #    들어온 오탐. '크게 메워야' 진짜 빗썸 금고다)
                for c in pool:
                    after = abs((hot_sum + c["bal"]) / off - 1) * 100
                    if c["bal"] > 0 and after <= MATCH_PCT and after <= abs(gap_pct) / 2:
                        found, found_how = c, "더하면 빗썸 공개 숫자와 맞음"
                        break

        bal_of = {h[0]: h[3] for h in main["holders"] if not h[2]}
        if found:
            bal_of[found["addr"]] = found["bal"]
            hot_sum += found["bal"]
        if not bal_of:
            book_at = load_book(ex)[1]
            st.info(f"🔎 {t}를 가진 {X} 지갑을 아직 못 찾았습니다 "
                    f"({', '.join(ONCHAIN_CHAINS[p['ck']]['name'] for p in per)} · 주소록 "
                    f"{sum(p['n_book'] for p in per)}곳 조회"
                    f"{f' · {book_at} 기준' if book_at else ''}). "
                    + ("아직 입금 전이거나, 새 금고라면 잠시 뒤 다시 보세요." if ex == "bithumb" else
                       "업비트 신규 상장 금고는 상장추적봇이 찾아 주소록에 넣은 뒤, "
                       "bithumb_wallets.json 을 새로 올려야 보입니다."))
            return
        wallets = sorted(bal_of, key=lambda a: -bal_of[a])[:MAX_FLOW_WALLETS]

        with st.spinner(f"{X} 지갑 입출금 기록 읽는 중..."):
            s = vault_flows(ck, contract, tuple(wallets), hours, ex)
    except Exception as e:
        st.error(f"온체인 조회 실패: {e}")
        return

    price, p_src = _usd_price(t)
    usdt_krw, _ = get_usdt_krw_price()

    def krw(q):
        return format_krw_short(q * price * usdt_krw) if price else "시세 없음"

    multi = len(per) > 1
    seen = s["seen_h"]
    span_txt = f"{hours}h" if seen >= hours * 0.97 else f"실제 {seen:.1f}h"
    n_hold = sum(1 for p in per for h in p["holders"] if not h[2]) + (1 if found else 0)
    cold_sum = sum(h[3] for p in per for h in p["holders"] if h[2])
    st.markdown(f"🏦 **{X} 지갑 {n_hold}곳** · "
                + " + ".join(ONCHAIN_CHAINS[p["ck"]]["name"] for p in per if p["hot"] > 0
                             or p is main)
                + (f" · 🆕 새 금고 [`{_short(found['addr'])}`]"
                   f"({cfg['explorer']}/address/{found['addr']}) ({found_how})" if found else ""))
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(f"총 입금 ({span_txt})", _fmt_qty(s["in_sum"]))
        st.caption(f"{krw(s['in_sum'])} · {s['in_n']}건")
    with m2:
        st.metric("입금한 지갑 수", f"{s['wallets']:,}곳")
        st.caption(f"첫 입금 {_kst(s['first_ts'])} · 마지막 {_kst(s['last_ts'])}")
    with m3:
        st.metric(f"{X} 지갑 보유 합계", _fmt_qty(hot_sum))
        st.caption(krw(hot_sum) + (" · " + " / ".join(
            f"{ONCHAIN_CHAINS[p['ck']]['name']} {_fmt_qty(p['hot'] + (found['bal'] if found and p is main else 0))}"
            for p in per) if multi else "")
            + (f" · 🧊 콜드 {_fmt_qty(cold_sum)} 별도" if cold_sum else ""))
    with m4:
        st.metric(f"{X} 밖으로 나감 ({span_txt})", _fmt_qty(s["out_sum"]))
        st.caption(f"{krw(s['out_sum'])} · {s['out_n']}건")

    # 빗썸 공개 숫자와 비교 — 공개 숫자 = 빗썸 지갑 잔고 합(입금 − 출금) 인지 확인
    if off and hot_sum > 0:
        diff = (off / hot_sum - 1) * 100
        if abs(diff) <= MATCH_PCT:
            st.success(f"✅ 빗썸 공개 숫자 {_fmt_qty(off)} ≈ 빗썸 지갑 보유 합계 "
                       f"{_fmt_qty(hot_sum)} ({diff:+.1f}%) → 공개 숫자는 "
                       f"'들어온 것 − 나간 것'입니다. 실제 들어온 양은 위 '총 입금'을 보세요.")
        elif hot_sum < off * 0.5:
            st.info(f"ℹ️ 주소록에서 찾은 빗썸 지갑은 공개 숫자 {_fmt_qty(off)}의 "
                    f"{hot_sum / off * 100:.0f}%({_fmt_qty(hot_sum)})만 들고 있습니다. 나머지는 아직 "
                    f"주소록에 없는 빗썸 지갑에 있어서, 위 입출금 숫자도 찾은 지갑 기준입니다.")
        else:
            st.info(f"ℹ️ 빗썸 공개 숫자 {_fmt_qty(off)} vs 빗썸 지갑 보유 합계 "
                    f"{_fmt_qty(hot_sum)} ({diff:+.1f}%) — 공개 숫자는 10분쯤마다 갱신돼 늦을 수 "
                    f"있고, 주소록에 없는 빗썸 지갑이 더 있을 수도 있습니다.")
    if ex == "upbit":
        st.caption("ℹ️ 업비트는 빗썸의 '입금 누적' 같은 공개 숫자가 없어서, 상장추적봇이 확인해 "
                   "주소록에 넣은 업비트 지갑만 셉니다 (콜드 제외). 신규 상장 금고는 상장추적봇이 "
                   "찾은 뒤 주소록을 새로 올려야 보입니다.")
    if seen < hours * 0.97:
        st.caption(f"⚠️ 무료 RPC가 옛 기록을 다 안 줘서 입출금은 최근 {seen:.1f}시간만 셌습니다 "
                   f"(보유 합계는 지금 잔고라 정확).")
    if multi:
        st.caption(f"ℹ️ 보유 합계는 {X} 지갑이 있는 망 {len(per)}개를 다 더한 값이고, "
                   f"입출금은 가장 많이 들고 있는 {cfg['name']} 기준입니다.")

    if s["rows"]:
        df = pd.DataFrame(s["rows"], columns=["ts", "qty"])
        df["시각"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(KST) \
                     .dt.floor("10min").dt.tz_localize(None)
        per10 = df.groupby("시각")["qty"].sum()
        ch1, ch2 = st.columns(2)
        with ch1:
            st.caption("10분마다 들어온 양")
            st.bar_chart(per10.rename("입금량"))
        with ch2:
            st.caption("누적 입금")
            st.line_chart(per10.cumsum().rename("누적"))

    n_list = sum(len(p["holders"]) for p in per) + (1 if found else 0)
    with st.expander(f"📒 {X} 지갑 목록 ({n_list}곳)"):
        lines = []
        if found:
            lines.append(f"- 🆕 [`{_short(found['addr'])}`]({cfg['explorer']}/address/"
                         f"{found['addr']}) 새 금고 ({found_how}, 입금지갑 {found['senders']}곳)"
                         f" — **{_fmt_qty(found['bal'])}** ({krw(found['bal'])})")
        for p in per:
            pc = ONCHAIN_CHAINS[p["ck"]]
            for a, lab, cold, q in p["holders"][:30]:
                lines.append(f"- {'🧊 ' if cold else ''}{pc['name'] + ' · ' if multi else ''}"
                             f"[`{_short(a)}`]({pc['explorer']}/address/{a})"
                             f" {lab or X} — **{_fmt_qty(q)}** ({krw(q)})"
                             + (" · 콜드라 합계 제외" if cold else ""))
        st.markdown("\n".join(lines) or "(없음)")
        book_at = load_book(ex)[1]
        n_miss = sum(p["n_miss"] for p in per)
        st.caption(f"주소록 {sum(p['n_book'] for p in per)}곳 조회"
                   + (f" · {book_at} 기준" if book_at else "")
                   + (f" · {n_miss}곳은 RPC가 답을 안 줌" if n_miss else "")
                   + (f" · 조회 실패: {'; '.join(errs)}" if errs else ""))

    st.caption(f"⏱ 블록 {s['block']:,} 기준 · {_kst(s['asof'])} KST · "
               f"{'5분' if ONCHAIN_CHAINS[ck].get('slow') else '1분'}마다 새로 읽음"
               + (f" · 시세 {p_src} ${price:,.6f}" if price else ""))
    st.caption(f"ℹ️ 개인 입금주소는 표시하지 않습니다. {X} 거래소 지갑만 보여줍니다.")


@st.cache_data(ttl=300)
def upbit_symbols():
    """업비트 상장 코인 (KRW·BTC·USDT 마켓 전부). 실패하면 None → 아무 티커나 받는다."""
    try:
        r = requests.get("https://api.upbit.com/v1/market/all", timeout=8)
        if r.status_code == 200:
            return frozenset(m["market"].split("-", 1)[1] for m in r.json())
    except Exception:
        pass
    return None


def render_upbit_page():
    """🟦 업비트 모드 (2026.10.09 추가) — 업비트는 공개 '입금 누적'이 없어서 ⛓ 온체인 칸만 보여준다.
    빗썸 화면 코드는 건드리지 않고, 여기서 다 그린 뒤 st.stop() 한다."""
    with st.sidebar:
        st.header("🔍 코인 검색")
        syms = upbit_symbols()
        t = st.text_input("코인 티커 입력 (예: ONDO, ENA)", placeholder="ONDO",
                          key="up_ticker").strip().upper()
        if t and syms is not None and t not in syms:
            st.error(f"❌ 업비트에 {t} 코인이 없습니다.")
            similar = sorted(x for x in syms if t in x)
            if similar:
                st.info(f"💡 혹시 이 코인? {', '.join(similar[:5])}")
            t = ""
        elif t:
            st.success(f"✅ {t}")
        st.markdown("---")
        auto = st.checkbox("자동 새로고침 (1분마다 새 숫자)", key="up_auto")
    if t:
        render_onchain(t, 0, ex="upbit")
    else:
        st.info("👈 왼쪽에 업비트 코인 티커를 넣으세요.")
        st.markdown("업비트 거래소 지갑(상장추적봇·복제핫·현선봇 주소록)이 블록체인에서 들고 있는 양과 "
                    "최근 입출금을 보여줍니다. 업비트는 빗썸처럼 '입금 누적' 공개 숫자가 없어서 "
                    "온체인 숫자만 나옵니다.")
    st.markdown("---")
    st.caption("⛓ 업비트 금고: 주소록의 업비트 지갑 입출금을 블록체인에서 직접 조회 — EVM 체인")
    st.caption("⚠️ 정보는 참고용이며, 정확한 정보는 각 거래소 공식 사이트 확인.")
    if t and auto:
        time.sleep(15)      # 숫자는 1분(느린 체인 5분)마다 새로 읽힌다 — 15초마다 화면만 다시 그림
        st.rerun()


# 거래소 고르기 (2026.10.09) — 빗썸이 기본. 업비트를 고르면 업비트 화면만 그리고 끝낸다.
with st.sidebar:
    ex_mode = st.radio("거래소", ["빗썸", "업비트"], horizontal=True, key="ex_mode")
if ex_mode == "업비트":
    render_upbit_page()
    st.stop()


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
st.caption("⛓ 온체인 금고: 빗썸 지갑(주소록 + 새 금고 자동 찾기)의 입출금을 블록체인에서 직접 조회 — EVM 체인 전부")
st.caption("⚠️ 정보는 참고용이며, 정확한 정보는 각 거래소 공식 사이트 확인.")

if _tick_after_render:
    time.sleep(1)
    st.rerun()
