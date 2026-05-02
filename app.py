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
            time.sleep(1)
            st.rerun()


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
st.caption("⚠️ 정보는 참고용이며, 정확한 정보는 각 거래소 공식 사이트 확인.")

