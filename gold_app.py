# v2.0 - 修复 Streamlit Cloud 部署 ValueError (空Series/标量值处理)
"""
黄金核心指标监控仪表盘 (自适应多数据源版)
数据源（自动检测，优先使用可访问的源）：
  - 宏观指标：美联储 FRED（TIPS、通胀预期、美元指数、VIX、联邦基金利率）
  - 金价历史：Yahoo Finance GC=F（优先） → AkShare COMEX黄金（备用） → FRED（兜底）
  - GLD/投资需求：Yahoo Finance GLD（优先） → AkShare 上海金（备用）
  - 实时金价：Yahoo Finance（优先） → 新浪财经（备用，仅国内）
新增功能：概览卡片、GLD持仓、时间选择、预警逻辑、UI优化、错误处理增强、本地文件缓存
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import time
import os
import json

# ================== 本地文件缓存配置 ==================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR_INTENDED = os.path.join(_SCRIPT_DIR, "data_cache")  # 期望的缓存文件夹（绝对路径）
CACHE_MAX_AGE_HOURS = 6            # 缓存有效期（小时），超过则重新获取

# 尝试创建缓存目录，如果失败则降级到系统临时目录
try:
    os.makedirs(_CACHE_DIR_INTENDED, exist_ok=True)
    CACHE_DIR = _CACHE_DIR_INTENDED
except Exception:
    import tempfile
    CACHE_DIR = os.path.join(tempfile.gettempdir(), "gold_dashboard_cache")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except Exception:
        CACHE_DIR = None  # 完全禁用文件缓存

def _cache_path(name):
    """返回某个数据源的本地缓存文件路径"""
    if CACHE_DIR is None:
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{name}.csv")

def _meta_path(name):
    """返回某个数据源的缓存元信息文件路径（记录获取时间、数据来源等）"""
    if CACHE_DIR is None:
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{name}.meta.json")

def is_cache_valid(name):
    """检查本地缓存是否存在且未过期"""
    if CACHE_DIR is None:
        return False
    meta_file = _meta_path(name)
    if meta_file is None or not os.path.exists(meta_file):
        return False
    try:
        with open(meta_file, 'r') as f:
            meta = json.load(f)
        cached_time = datetime.fromisoformat(meta["cached_at"])
        return datetime.now() - cached_time < timedelta(hours=CACHE_MAX_AGE_HOURS)
    except Exception:
        return False

def save_cache(name, series, source=""):
    """将Series保存到本地缓存文件，并记录元信息（完全防崩溃版）"""
    try:
        if CACHE_DIR is None:
            return
        # 空值/None/空序列 不保存
        if series is None:
            return
        if hasattr(series, 'empty') and series.empty:
            return
        if hasattr(series, '__len__') and len(series) == 0:
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        # 统一转为 Series
        s = pd.Series(series) if not isinstance(series, pd.Series) else series.copy()
        # 确保 index 存在（这是 ValueError 的根因）
        if s.index is None or (hasattr(s.index, 'size') and s.index.size == 0):
            s = s.reset_index(drop=True)
        # 构建 DataFrame（用 reset_index 确保有 index）
        df = s.to_frame("value")
        df.index.name = "date"
        cache_path = _cache_path(name)
        if cache_path:
            df.to_csv(cache_path)
        meta = {
            "cached_at": datetime.now().isoformat(),
            "source": source,
            "count": len(s),
            "start": str(s.index[0]) if len(s) > 0 else "",
            "end": str(s.index[-1]) if len(s) > 0 else "",
        }
        meta_path = _meta_path(name)
        if meta_path:
            with open(meta_path, 'w') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 缓存保存失败不影响主流程，静默忽略
        pass

def load_cache(name):
    """从本地缓存文件加载Series"""
    if CACHE_DIR is None:
        return pd.Series(dtype=float), False
    path = _cache_path(name)
    if not os.path.exists(path):
        return pd.Series(dtype=float), False
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        series = df.iloc[:, 0].dropna()
        return series, True
    except Exception:
        return pd.Series(dtype=float), False

def clear_all_cache():
    """清除所有本地缓存文件"""
    if CACHE_DIR is None or not os.path.exists(CACHE_DIR):
        return
        for f in os.listdir(CACHE_DIR):
            os.remove(os.path.join(CACHE_DIR, f))

# 在侧边栏显示缓存状态
def show_cache_status():
    """在侧边栏显示各数据源的缓存状态"""
    if CACHE_DIR is None or not os.path.exists(CACHE_DIR):
        return
        return
    st.sidebar.subheader("💾 本地缓存状态")
    cache_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.meta.json')]
    for cf in sorted(cache_files):
        name = cf.replace('.meta.json', '')
        meta_file = os.path.join(CACHE_DIR, cf)
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
            cached_at = datetime.fromisoformat(meta["cached_at"])
            age_h = (datetime.now() - cached_at).total_seconds() / 3600
            age_str = f"{age_h:.1f}h前" if age_h < 24 else f"{age_h/24:.1f}天前"
            st.sidebar.caption(f"✅ {name}: {age_str}")
        except Exception:
            st.sidebar.caption(f"⚠️ {name}: 元数据异常")

st.set_page_config(page_title="黄金多维监控", layout="wide")
st.title("🟡 黄金核心驱动指标监控仪表盘")

# ================== 侧边栏：时间范围选择 ==================
st.sidebar.header("⚙️ 设置")

# 日期范围选择器
st.sidebar.subheader("📅 时间范围")
default_start = datetime(2021, 1, 1)
default_end = datetime.now()

start_date = st.sidebar.date_input(
    "开始日期",
    value=default_start,
    max_value=default_end - timedelta(days=1)
)

end_date = st.sidebar.date_input(
    "结束日期",
    value=default_end,
    min_value=start_date
)

# 刷新数据按钮
if st.sidebar.button("🔄 刷新数据", use_container_width=True):
    st.cache_data.clear()
    st.success("✅ 内存缓存已清除，正在重新加载数据...")
    st.rerun()

if st.sidebar.button("🗑️ 清除本地缓存", use_container_width=True):
    clear_all_cache()
    st.success("✅ 本地缓存文件已删除，正在重新获取...")
    st.rerun()

show_cache_status()

st.sidebar.divider()
st.sidebar.caption("💡 调整时间范围后，图表将自动更新")

# ================== FRED 数据获取（含本地文件缓存）====================
@st.cache_data(ttl=3600)
def fetch_fred_csv(series_id, start_date="2021-01-01", end_date=None):
    """从FRED获取经济数据CSV，带本地文件缓存"""
    cache_name = f"fred_{series_id}"

    # 优先尝试从本地缓存加载（跨重启持久化）
    if is_cache_valid(cache_name):
        cached_series, ok = load_cache(cache_name)
        if ok and not cached_series.empty:
            return cached_series, True

    # 本地缓存无效或不存在，从网络获取
    if end_date is None:
        end_date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        end_date_str = end_date.strftime("%Y-%m-%d") if hasattr(end_date, 'strftime') else str(end_date)

    start_date_str = start_date.strftime("%Y-%m-%d") if hasattr(start_date, 'strftime') else str(start_date)

    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={start_date_str}&coed={end_date_str}")
    try:
        df = pd.read_csv(url, parse_dates=["observation_date"])
        df.set_index("observation_date", inplace=True)
        series = df.iloc[:, 0].dropna()
        # 保存到本地缓存
        if not series.empty:
            try:
                save_cache(cache_name, series, f"FRED({series_id})")
            except Exception:
                pass
        return series, True
    except Exception as e:
        # 网络失败，尝试加载过期缓存作为降级
        cached_series, ok = load_cache(cache_name)
        if ok and not cached_series.empty:
            return cached_series, True
        return pd.Series(dtype=float), False

# ================== 金价获取（自适应多数据源）====================
def fetch_gold_price(start_dt, end_dt):
    """
    自适应获取黄金价格历史数据
    优先级：Yahoo Finance GC=F（国外可访问） → AkShare COMEX黄金（国内可访问） → FRED（兜底）
    返回：(series, success, source_name)
    """
    cache_name = "gold_price_adaptive"

    # 优先尝试从本地缓存加载
    if is_cache_valid(cache_name):
        cached_series, ok = load_cache(cache_name)
        if ok and not cached_series.empty:
            meta_file = _meta_path(cache_name)
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                return cached_series, True, meta.get("source", "缓存")
            except Exception:
                return cached_series, True, "本地缓存"

    # 第1级：Yahoo Finance GC=F（国外服务器可访问，国内可能被墙）
    yahoo_series, yahoo_ok = _try_yahoo_gold(start_dt, end_dt)
    if yahoo_ok and not yahoo_series.empty:
        try:
            save_cache(cache_name, yahoo_series, "Yahoo Finance (GC=F)")
        except Exception:
            pass
        return yahoo_series, True, "Yahoo Finance (GC=F 期货)"

    # 第2级：AkShare COMEX黄金期货（国内可访问，国外可能无法安装）
    akshare_series, akshare_ok, akshare_src = _try_akshare_gold()
    if akshare_ok and not akshare_series.empty:
        try:
            save_cache(cache_name, akshare_series, akshare_src)
        except Exception:
            pass
        return akshare_series, True, akshare_src

    # 第3级：FRED（金价系列已下架，仅作为兜底尝试）
    fred_series, fred_ok = _try_fred_gold(start_dt, end_dt)
    if fred_ok and not fred_series.empty:
        try:
            save_cache(cache_name, fred_series, "FRED")
        except Exception:
            pass
        return fred_series, True, "FRED (伦敦金定盘价)"

    # 所有来源均失败，尝试加载过期缓存作为降级
    cached_series, ok = load_cache(cache_name)
    if ok and not cached_series.empty:
        return cached_series, True, "本地缓存-降级"

    return pd.Series(dtype=float), False, ""


def _try_yahoo_gold(start_dt, end_dt):
    """尝试从 Yahoo Finance 获取黄金期货价格"""
    start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, 'strftime') else str(start_dt)
    end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, 'strftime') else str(end_dt)
    try:
        import yfinance as yf
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        for attempt in range(2):
            data = yf.download("GC=F", start=start_str, end=end_str,
                               session=session, progress=False, timeout=15)
            if data is not None and not data.empty:
                close = data["Close"]
                # 新版 yfinance 可能返回 DataFrame（MultiIndex列），需要展平
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]  # 取第一列作为 Series
                s = close.dropna()
                # 确保返回的是 Series
                if isinstance(s, pd.Series) and not s.empty:
                    return s, True
            time.sleep(2)
    except Exception:
        pass
    return pd.Series(dtype=float), False


def _try_akshare_gold():
    """尝试从 AkShare 获取 COMEX 黄金期货数据"""
    try:
        import akshare as ak
        df = ak.futures_foreign_hist(symbol='GC')
        if df is not None and not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            series = df['close'].dropna()
            return series, True, "AkShare (COMEX黄金期货GC)"
    except ImportError:
        pass  # AkShare 未安装
    except Exception:
        pass
    return pd.Series(dtype=float), False, ""


def _try_fred_gold(start_dt, end_dt):
    """尝试从 FRED 获取黄金价格（伦敦金定盘价，已下架，仅兜底）"""
    start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, 'strftime') else str(start_dt)
    end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, 'strftime') else str(end_dt)
    for series_id in ["GOLDPMGBD228NLBR", "GOLDAMGBD228NLBR"]:
        try:
            url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
                   f"?id={series_id}&cosd={start_str}&coed={end_str}")
            df = pd.read_csv(url, parse_dates=["observation_date"])
            df.set_index("observation_date", inplace=True)
            series = df.iloc[:, 0].dropna()
            if not series.empty:
                return series, True
        except Exception:
            pass
    return pd.Series(dtype=float), False

# ================== 实时金价获取（自适应多数据源）====================
@st.cache_data(ttl=300)  # 缓存5分钟
def fetch_gold_realtime():
    """
    自适应获取黄金实时价格
    优先级：Yahoo Finance（国外可访问） → 新浪财经（国内备用）
    """
    # 第1级：Yahoo Finance 实时报价
    try:
        import yfinance as yf
        ticker = yf.Ticker("GC=F")
        info = ticker.info
        if info and 'regularMarketPrice' in info:
            price = info['regularMarketPrice']
            return {'price': float(price), 'source': 'Yahoo Finance', 'name': 'COMEX黄金期货'}
    except Exception:
        pass

    # 第2级：新浪财经（仅国内可访问）
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/futures/'
        }
        resp = requests.get(
            'https://hq.sinajs.cn/list=hf_GC',
            headers=headers,
            timeout=10
        )
        text = resp.content.decode('gbk', errors='ignore')
        if 'hf_GC' in text:
            parts = text.split('"')[1].split(',')
            if len(parts) >= 12 and parts[3]:
                return {
                    'price': float(parts[3]),
                    'open': float(parts[0]) if parts[0] else None,
                    'high': float(parts[4]) if parts[4] else None,
                    'low': float(parts[5]) if parts[5] else None,
                    'date': parts[11],
                    'name': parts[12] if len(parts) > 12 else '黄金期货',
                    'source': '新浪财经'
                }
    except Exception:
        pass

    return None


# ================== 投资需求代理获取（自适应多数据源）====================
def fetch_investment_proxy(start_dt, end_dt):
    """
    自适应获取投资需求代理指标
    优先级：Yahoo Finance GLD ETF（国外可访问） → AkShare 上海金（国内备用）
    返回：(series, success, source_name)
    """
    cache_name = "investment_proxy_adaptive"

    # 优先尝试从本地缓存加载
    if is_cache_valid(cache_name):
        cached_series, ok = load_cache(cache_name)
        if ok and not cached_series.empty:
            meta_file = _meta_path(cache_name)
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                return cached_series, True, meta.get("source", "缓存")
            except Exception:
                return cached_series, True, "本地缓存"

    # 第1级：Yahoo Finance GLD ETF（国外可访问）
    yahoo_gld, yahoo_ok = _try_yahoo_gld(start_dt, end_dt)
    if yahoo_ok and not yahoo_gld.empty:
        try:
            save_cache(cache_name, yahoo_gld, "Yahoo Finance (GLD ETF)")
        except Exception:
            pass
        return yahoo_gld, True, "Yahoo Finance (GLD ETF)"

    # 第2级：AkShare 上海金 Au99.99（国内可访问）
    akshare_gld, akshare_ok, akshare_src = _try_akshare_sge()
    if akshare_ok and not akshare_gld.empty:
        try:
            save_cache(cache_name, akshare_gld, akshare_src)
        except Exception:
            pass
        return akshare_gld, True, akshare_src

    # 所有来源均失败，尝试加载过期缓存作为降级
    cached_series, ok = load_cache(cache_name)
    if ok and not cached_series.empty:
        return cached_series, True, "本地缓存-降级"

    return pd.Series(dtype=float), False, ""


def _try_yahoo_gld(start_dt, end_dt):
    """尝试从 Yahoo Finance 获取 GLD ETF 价格"""
    start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, 'strftime') else str(start_dt)
    end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, 'strftime') else str(end_dt)
    try:
        import yfinance as yf
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        for attempt in range(2):
            data = yf.download("GLD", start=start_str, end=end_str,
                               session=session, progress=False, timeout=15)
            if data is not None and not data.empty:
                close = data["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                s = close.dropna()
                if isinstance(s, pd.Series) and not s.empty:
                    return s, True
            time.sleep(2)
    except Exception:
        pass
    return pd.Series(dtype=float), False


def _try_akshare_sge():
    """尝试从 AkShare 获取上海金交所 Au99.99 数据"""
    try:
        import akshare as ak
        df = ak.spot_hist_sge(symbol='Au99.99')
        if df is not None and not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df['close'].dropna(), True, "上海金(Au99.99 元/克)"
    except ImportError:
        pass  # AkShare 未安装
    except Exception:
        pass
    return pd.Series(dtype=float), False, ""

# ================== 加载数据 ==================
st.info("正在从数据源获取最新数据（自动选择可访问的数据源）...")

# 转换日期格式
start_dt = pd.Timestamp(start_date)
end_dt = pd.Timestamp(end_date)

# ========== 1. 金价数据：自适应多数据源 ==========
gold_series = pd.Series(dtype=float)
gold_source = ""
gold_available = False

gold_series, gold_ok, gold_source = fetch_gold_price(start_dt, end_dt)
if gold_ok and not gold_series.empty:
    gold_available = True
else:
    gold_available = False

# ========== 2. 宏观指标（全部来自FRED）==========
tips, tips_ok   = fetch_fred_csv("DFII10", start_dt, end_dt)     # 10年 TIPS 收益率
be, be_ok       = fetch_fred_csv("T10YIE", start_dt, end_dt)     # 盈亏平衡通胀率
dxy, dxy_ok     = fetch_fred_csv("DTWEXBGS", start_dt, end_dt)   # 贸易加权美元指数
vix, vix_ok     = fetch_fred_csv("VIXCLS", start_dt, end_dt)     # VIX 收盘价
fed, fed_ok     = fetch_fred_csv("DFEDTARU", start_dt, end_dt)   # 联邦基金目标利率(上限)

# 如果 DFEDTARU 失败，尝试 DFF（有效利率）
if not fed_ok or (hasattr(fed, 'empty') and fed.empty):
    fed, fed_ok = fetch_fred_csv("DFF", start_dt, end_dt)

# ========== 3. 投资需求代理：自适应多数据源 ==========
gld_series = pd.Series(dtype=float)
gld_source = ""
gld_ok = False

gld_series, gld_ok, gld_source = fetch_investment_proxy(start_dt, end_dt)

# ========== 4. 合并主数据框 ==========
data_dict = {}
if gold_available and not (hasattr(gold_series, 'empty') and gold_series.empty):
    data_dict["金价"] = gold_series
if not (hasattr(tips, 'empty') and tips.empty):
    data_dict["10年TIPS收益率"] = tips
if not (hasattr(be, 'empty') and be.empty):
    data_dict["盈亏平衡通胀率"] = be
if not (hasattr(dxy, 'empty') and dxy.empty):
    data_dict["美元指数"] = dxy
if not (hasattr(vix, 'empty') and vix.empty):
    data_dict["VIX"] = vix
if not (hasattr(fed, 'empty') and fed.empty):
    data_dict["联邦基金利率"] = fed

df = pd.DataFrame(data_dict)

# 计算名义利率（如果TIPS和通胀数据都可用）
if not tips.empty and not be.empty:
    df["名义利率(近似)"] = tips + be

# 过滤时间范围
if not df.empty:
    try:
        df = df.loc[start_dt:end_dt]
    except (KeyError, IndexError):
        pass  # 过滤失败时保留原数据
else:
    st.error("🚨 **所有宏观数据源均无法获取数据**")
    st.error("请检查网络连接后点击侧边栏「刷新数据」按钮重试")

# ================== 概览指标卡片 ==================
st.header("📊 核心指标概览")

# 获取实时金价用于卡片
realtime_gold = fetch_gold_realtime()

if not df.empty:
    latest = df.iloc[-1]

    # 获取各指标的最新值（优先从原始Series取，避免合并DataFrame末行因日期不对齐导致NaN）
    def safe_latest(series, col_name):
        """安全获取最新值：先尝试合并df的最后有效值，回退到原始series"""
        # 从合并df中找最后一个非NaN值
        if col_name in df.columns:
            valid = df[col_name].dropna()
            if not valid.empty:
                return valid.iloc[-1]
        # 回退到原始series
        if hasattr(series, 'iloc') and not series.empty:
            return series.iloc[-1]
        return None

    latest_gold = safe_latest(gold_series, "金价")
    latest_tips = safe_latest(tips, "10年TIPS收益率")
    latest_dxy  = safe_latest(dxy, "美元指数")
    latest_vix  = safe_latest(vix, "VIX")

    card1, card2, card3, card4 = st.columns(4)

    # 卡片1: 金价
    with card1:
        if latest_gold is not None and not pd.isna(latest_gold):
            if realtime_gold and realtime_gold.get('price'):
                st.metric(label="💰 最新金价", value=f"${latest_gold:.1f}/盎司",
                         delta=f"实时: ${realtime_gold['price']:.1f}", delta_color="off")
            else:
                st.metric(label="💰 最新金价", value=f"${latest_gold:.1f}/盎司")
        elif realtime_gold and realtime_gold.get('price'):
            st.metric(label="💰 最新金价", value=f"${realtime_gold['price']:.1f}/盎司",
                     delta=f"实时数据({realtime_gold.get('source', '')})", delta_color="off")
        else:
            st.metric(label="💰 最新金价", value="暂不可用")

    # 卡片2: TIPS收益率
    with card2:
        if latest_tips is not None and not pd.isna(latest_tips):
            if latest_tips < -1.0:
                st.metric(label="📉 10年TIPS收益率", value=f"{latest_tips:.2f}%",
                         delta="实际利率极低", delta_color="inverse")
            else:
                st.metric(label="📉 10年TIPS收益率", value=f"{latest_tips:.2f}%")
        else:
            st.metric(label="📉 10年TIPS收益率", value="暂不可用")

    # 卡片3: 美元指数
    with card3:
        if latest_dxy is not None and not pd.isna(latest_dxy):
            st.metric(label="💵 美元指数（贸易加权）", value=f"{latest_dxy:.2f}")
        else:
            st.metric(label="💵 美元指数（贸易加权）", value="暂不可用")

    # 卡片4: VIX
    with card4:
        if latest_vix is not None and not pd.isna(latest_vix):
            if latest_vix > 30:
                st.metric(label="😰 VIX恐慌指数", value=f"{latest_vix:.2f}",
                         delta="市场恐慌", delta_color="inverse")
            elif latest_vix > 20:
                st.metric(label="😰 VIX恐慌指数", value=f"{latest_vix:.2f}",
                         delta="市场波动")
            else:
                st.metric(label="😰 VIX恐慌指数", value=f"{latest_vix:.2f}")
        else:
            st.metric(label="😰 VIX恐慌指数", value="暂不可用")
else:
    st.warning("⚠️ 暂无数据可显示")

# ================== 预警逻辑 ==================
st.header("⚠️ 市场预警")

# TIPS收益率预警
if tips_ok and not tips.empty:
    latest_tips = tips.iloc[-1]
    if latest_tips < -1.5:
        st.error(f"🚨 **TIPS收益率预警**：当前10年TIPS收益率为 {latest_tips:.2f}%，已低于-1.5%，实际利率极低，黄金投资吸引力增强。")
    elif latest_tips > 0:
        st.warning(f"⚠️ **TIPS收益率预警**：当前10年TIPS收益率为 {latest_tips:.2f}%，已转正，黄金持有成本上升。")

# VIX预警
if vix_ok and not vix.empty:
    latest_vix = vix.iloc[-1]
    if latest_vix > 30:
        st.error(f"🚨 **VIX恐慌预警**：当前VIX指数为 {latest_vix:.2f}，市场恐慌情绪严重，避险需求可能推高金价。")

if not tips_ok and not vix_ok:
    st.info("ℹ️ 预警功能需要TIPS收益率和VIX数据")

st.divider()

# ================== 数据加载状态提示 ==================
if gold_available:
    st.success(f"✅ 金价数据加载成功 (来源: {gold_source})")
else:
    st.error("❌ 金价数据暂不可用（AkShare和Yahoo数据源均失败），相关图表将显示'数据暂不可用'")

status_items = []
status_items.append(("✅ TIPS收益率" if tips_ok else "❌ TIPS收益率"))
status_items.append(("✅ 通胀预期" if be_ok else "❌ 通胀预期"))
status_items.append(("✅ 美元指数" if dxy_ok else "❌ 美元指数"))
status_items.append(("✅ VIX" if vix_ok else "❌ VIX"))
status_items.append(("✅ 联邦基金利率" if fed_ok else "❌ 联邦基金利率"))
status_items.append((f"✅ 投资代理({gld_source})" if gld_ok else "❌ 投资代理"))

st.caption(f"数据加载状态：{' | '.join([x[0] for x in status_items])}")
st.caption(f"📅 当前显示时间范围：{start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')}")

# ================== 可视化 ==================
# ① 实际利率 vs 金价
st.header("① 实际利率 vs 金价")

if gold_available and tips_ok and not df.empty and "金价" in df.columns and "10年TIPS收益率" in df.columns:
    c1, c2 = st.columns(2)
    with c1:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df.index, y=df["金价"], name="金价", yaxis="y1", line=dict(color="#FFD700")))
        fig1.add_trace(go.Scatter(x=df.index, y=df["10年TIPS收益率"], name="TIPS收益率", yaxis="y2", line=dict(color="#2563eb")))
        fig1.update_layout(
            title="金价与实际利率走势",
            yaxis=dict(title="美元/盎司", title_font_color="#FFD700"),
            yaxis2=dict(title="%", overlaying="y", side="right", autorange="reversed", title_font_color="#2563eb"),
            hovermode="x unified"
        )
        st.plotly_chart(fig1, use_container_width=True)

    with c2:
        fig2 = go.Figure()
        if not tips.empty:
            fig2.add_trace(go.Scatter(x=df.index, y=df["10年TIPS收益率"], name="实际利率", line=dict(color="#2563eb")))
        if not be.empty:
            fig2.add_trace(go.Scatter(x=df.index, y=df["盈亏平衡通胀率"], name="通胀预期", line=dict(color="#ef4444")))
        if "名义利率(近似)" in df.columns:
            fig2.add_trace(go.Scatter(x=df.index, y=df["名义利率(近似)"], name="名义利率(近似)", line=dict(color="#22c55e")))
        fig2.update_layout(title="利率结构分析", yaxis=dict(title="%"), hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)
else:
    st.error("❌ 金价或TIPS数据不可用，无法显示此图表")

# ② 美元与恐慌
st.header("② 美元指数与恐慌情绪")
st.caption("💡 注：此处美元指数为**贸易加权美元指数（DTWEXBGS）**，与常见的 DXY 美元指数有所不同。贸易加权美元指数反映了美元对一篮子主要贸易伙伴货币的综合强弱，覆盖范围更广。")

c3, c4 = st.columns(2)
with c3:
    if gold_available and dxy_ok and not df.empty and "金价" in df.columns and "美元指数" in df.columns:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df.index, y=df["金价"], name="金价", yaxis="y1", line=dict(color="#FFD700")))
        fig3.add_trace(go.Scatter(x=df.index, y=df["美元指数"], name="美元指数（贸易加权）", yaxis="y2", line=dict(color="#22c55e")))
        fig3.update_layout(
            title="金价与美元指数走势（负相关关系）",
            yaxis=dict(title="美元/盎司", title_font_color="#FFD700"),
            yaxis2=dict(title="指数", overlaying="y", side="right", title_font_color="#22c55e"),
            hovermode="x unified"
        )
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.error("❌ 金价或美元指数数据不可用，无法显示此图表")

with c4:
    if vix_ok and not df.empty and "VIX" in df.columns:
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=df.index, y=df["VIX"], name="VIX", fill="tozeroy", line=dict(color="#ef4444")))
        fig4.update_layout(title="VIX恐慌指数走势", yaxis=dict(title="VIX"), hovermode="x unified")
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.error("❌ VIX数据不可用，无法显示此图表")

# ③ 投资需求代理 vs 金价
st.header("③ 投资需求代理 vs 金价")

if gold_available and gld_ok and not df.empty and "金价" in df.columns:
    # 合并金价和投资需求数据
    df_invest = pd.DataFrame({"金价": gold_series, "投资需求代理": gld_series}).dropna()
    df_invest = df_invest.loc[start_dt:end_dt]
    
    if not df_invest.empty:
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=df_invest.index, y=df_invest["金价"], name="金价(COMEX USD/oz)", yaxis="y1", line=dict(color="#FFD700")))
        
        # 根据数据源设置标签
        invest_label = "上海金(Au99.99 CNY/g)" if "上海金" in gld_source else ("GLD ETF (USD)" if "GLD" in gld_source else "投资需求代理")
        fig6.add_trace(go.Scatter(x=df_invest.index, y=df_invest["投资需求代理"], name=invest_label, yaxis="y2", line=dict(color="#a855f7")))
        fig6.update_layout(
            title=f"金价与{invest_label}走势对比（投资需求代理指标）",
            yaxis=dict(title="美元/盎司", title_font_color="#FFD700"),
            yaxis2=dict(title=gld_source.split('(')[-1].rstrip(')') if '(' in gld_source else "数值", 
                       overlaying="y", side="right", title_font_color="#a855f7"),
            hovermode="x unified"
        )
        st.plotly_chart(fig6, use_container_width=True)
    else:
        st.warning("⚠️ 投资代理数据与金价的时间范围不匹配，无法显示对比图")
elif gold_available and not gld_ok:
    st.warning("⚠️ 投资需求代理数据暂不可用（AkShare上海金/Yahoo GLD均失败），仅显示金价相关图表")
else:
    st.error("❌ 金价或投资代理数据不可用，无法显示此图表")

# ④ 联邦基金利率 & 近期数据
st.header("④ 联邦基金利率 & 近期数据")

c5, c6 = st.columns(2)
with c5:
    if fed_ok and not df.empty and "联邦基金利率" in df.columns:
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(x=df.index, y=df["联邦基金利率"], name="联邦基金利率", line=dict(color="#f97316")))
        fig5.update_layout(title="联邦基金利率走势", yaxis=dict(title="%"), hovermode="x unified")
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.error("❌ 联邦基金利率数据不可用，无法显示此图表")

with c6:
    st.subheader("📋 近期数据一览")
    if not df.empty:
        recent_data = df.tail(20).sort_index(ascending=False)
        st.dataframe(recent_data, use_container_width=True)
    else:
        st.error("❌ 数据不可用，无法显示数据表")

# ================== 页脚说明 ==================
st.divider()
st.caption("""
**数据源说明（自适应多源，自动选择可访问的数据源）：**
- **美联储 FRED**：贸易加权美元指数（DTWEXBGS）、10年期TIPS收益率（DFII10）、盈亏平衡通胀率（T10YIE）、VIX（VIXCLS）、联邦基金利率（DFEDTARU/DFF）
- **黄金价格**：Yahoo Finance GC=F（优先，国外可访问） → AkShare COMEX黄金期货（备用，国内可访问） → FRED伦敦金定盘价（兜底）
- **投资需求代理**：Yahoo Finance GLD ETF（优先） → AkShare 上海金交所 Au99.99（备用）
- **实时金价**：Yahoo Finance（优先） → 新浪财经（备用，仅国内）
- **本地缓存**：所有数据获取后保存到本地 `data_cache/` 文件夹，重启应用后直接读取（6小时内有效），网络中断时自动加载过期缓存降级显示
""")
st.caption("💡 提示：点击侧边栏的「刷新数据」按钮可以清除内存缓存并重新加载最新数据")
st.caption("📦 部署说明：本应用已适配 Streamlit Community Cloud 部署，Yahoo Finance 在国外服务器可正常访问")
