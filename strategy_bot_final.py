import requests
import pandas as pd
import time
import threading
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands
from telegram.ext import Updater, CommandHandler

# ========== 사용자 설정 ==========
TELEGRAM_TOKEN = '7665786478:AAFuBpntS7fM-P8mkmFsHit7wx713iF4pQc'
CHAT_ID = '7801524005'

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'SHIBUSDT', 'XRPUSDT']
TIMEFRAMES = ['1m', '5m', '15m', '1h', '1d']
CHECK_INTERVAL = 60

# ⚙️ 실시간 설정값
condition_threshold = 4
tp_ratio = 1.03
sl_ratio = 0.985

status_dict = {}
market_status_dict = {}
# ================================

def is_kst_in_active_hours():
    return True

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {'chat_id': CHAT_ID, 'text': message}
    try:
        requests.post(url, data=payload)
    except:
        print("❌ 텔레그램 전송 실패")

def fetch_ohlcv(symbol, interval='5m', limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        data = requests.get(url).json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            '_', '_', '_', '_', '_', '_'
        ])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"[{symbol}-{interval}] OHLCV 불러오기 실패: {e}")
        return None

def analyze(df, symbol, interval):
    global condition_threshold, tp_ratio, sl_ratio
    try:
        # ✅ 데이터 길이 체크
        if df is None or len(df) < 50:
            print(f"[{symbol}-{interval}] 데이터 부족으로 분석 생략")
            return
        df['rsi'] = RSIIndicator(df['close']).rsi()
        macd = MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        df['ema9'] = EMAIndicator(df['close'], 9).ema_indicator()
        df['ema21'] = EMAIndicator(df['close'], 21).ema_indicator()
        df['ema200'] = EMAIndicator(df['close'], 200).ema_indicator()
        bb = BollingerBands(df['close'])
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_upper'] = bb.bollinger_hband()

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        long_conditions = [
            latest['rsi'] < 30,
            latest['macd'] > latest['macd_signal'],
            latest['macd_hist'] > 0 and prev['macd_hist'] < 0,
            latest['ema9'] > latest['ema21'],
            latest['close'] > latest['ema200'],
            latest['close'] < latest['bb_lower'],
            latest['close'] > latest['open'],
            latest['volume'] > prev['volume']
        ]

        short_conditions = [
            latest['rsi'] > 70,
            latest['macd'] < latest['macd_signal'],
            latest['macd_hist'] < 0 and prev['macd_hist'] > 0,
            latest['ema9'] < latest['ema21'],
            latest['close'] < latest['ema200'],
            latest['close'] > latest['bb_upper'],
            latest['close'] < latest['open'],
            latest['volume'] > prev['volume']
        ]

        status_dict[f"{symbol}_{interval}"] = {
            'long': sum(long_conditions),
            'short': sum(short_conditions)
        }

        market_status_dict[f"{symbol}_{interval}"] = {
            'close': latest['close'],
            'rsi': latest['rsi'],
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'volume': latest['volume']
        }

        entry = latest['close']
        tp_long = entry * tp_ratio
        sl_long = entry * sl_ratio
        tp_short = entry * (2 - tp_ratio)
        sl_short = entry * (2 - sl_ratio)

        if sum(long_conditions) >= condition_threshold:
            msg = (
                f"📍 [{symbol} | {interval}] ✅ 롱 진입 조건 충족!\n"
                f"진입가: ${entry:.6f}\nTP: ${tp_long:.6f}\nSL: ${sl_long:.6f}\n"
                f"조건 일치: {sum(long_conditions)}/8"
            )
            send_telegram(msg)

        elif sum(short_conditions) >= condition_threshold:
            msg = (
                f"📍 [{symbol} | {interval}] ❌ 숏 진입 조건 충족!\n"
                f"진입가: ${entry:.6f}\nTP: ${tp_short:.6f}\nSL: ${sl_short:.6f}\n"
                f"조건 일치: {sum(short_conditions)}/8"
            )
            send_telegram(msg)

    except Exception as e:
        print(f"[{symbol}-{interval}] 분석 에러: {e}")

def run_bot():
    while True:
        if is_kst_in_active_hours():
            for symbol in SYMBOLS:
                for interval in TIMEFRAMES:
                    df = fetch_ohlcv(symbol, interval)
                    if df is not None:
                        analyze(df, symbol, interval)
        else:
            print("⏰ 현재는 비활성 시간 (한국 기준). 전략 분석 생략 중.")
        time.sleep(CHECK_INTERVAL)

# ✅ 텔레그램 명령어 함수들

def status_command(update, context):
    text = "📊 현재 전략 상태 요약:\n"
    for key, value in status_dict.items():
        symbol, interval = key.split("_")
        text += f"▪ {symbol} ({interval}) - 롱: {value['long']}/8, 숏: {value['short']}/8\n"
    update.message.reply_text(text)

def market_command(update, context):
    text = "📈 실시간 시장 지표:\n"
    for key, value in market_status_dict.items():
        symbol, interval = key.split("_")
        text += (
            f"▪ {symbol} ({interval})\n"
            f"  - 현재가: ${value['close']:.4f}\n"
            f"  - RSI: {value['rsi']:.2f}\n"
            f"  - MACD: {value['macd']:.4f}, Signal: {value['macd_signal']:.4f}\n"
            f"  - 거래량: {value['volume']:.2f}\n\n"
        )
    update.message.reply_text(text)

def entry_command(update, context):
    text = "🚨 진입 가능 조건 충족 코인:\n"
    has_entry = False
    for key, value in status_dict.items():
        symbol, interval = key.split("_")
        if value['long'] >= condition_threshold:
            text += f"✅ 롱 진입: {symbol} ({interval}) 조건 {value['long']}/8\n"
            has_entry = True
        elif value['short'] >= condition_threshold:
            text += f"❌ 숏 진입: {symbol} ({interval}) 조건 {value['short']}/8\n"
            has_entry = True
    if not has_entry:
        text += "현재 진입 조건을 충족한 코인이 없습니다."
    update.message.reply_text(text)

def set_condition(update, context):
    global condition_threshold
    try:
        new_val = int(context.args[0])
        if 1 <= new_val <= 8:
            condition_threshold = new_val
            update.message.reply_text(f"✅ 전략 조건 기준이 {new_val}개 이상으로 변경되었습니다.")
        else:
            update.message.reply_text("⚠️ 1~8 사이의 값을 입력해주세요.")
    except:
        update.message.reply_text("❌ 사용법: /set_condition 5")

def set_tp(update, context):
    global tp_ratio
    try:
        new_val = float(context.args[0])
        if 1.00 < new_val < 1.2:
            tp_ratio = new_val
            update.message.reply_text(f"✅ TP 비율이 {tp_ratio:.3f}으로 변경되었습니다.")
        else:
            update.message.reply_text("⚠️ 예: 1.03 (3% 익절)")
    except:
        update.message.reply_text("❌ 사용법: /set_tp 1.03")

def set_sl(update, context):
    global sl_ratio
    try:
        new_val = float(context.args[0])
        if 0.90 < new_val < 1.0:
            sl_ratio = new_val
            update.message.reply_text(f"✅ SL 비율이 {sl_ratio:.3f}으로 변경되었습니다.")
        else:
            update.message.reply_text("⚠️ 예: 0.985 (1.5% 손절)")
    except:
        update.message.reply_text("❌ 사용법: /set_sl 0.985")

def config_command(update, context):
    text = (
        f"⚙️ 현재 설정값\n"
        f"- 조건 기준: {condition_threshold}/8\n"
        f"- TP 비율: {tp_ratio:.3f}\n"
        f"- SL 비율: {sl_ratio:.3f}"
    )
    update.message.reply_text(text)

def start_telegram_listener():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("market", market_command))
    dp.add_handler(CommandHandler("entry", entry_command))
    dp.add_handler(CommandHandler("set_condition", set_condition))
    dp.add_handler(CommandHandler("set_tp", set_tp))
    dp.add_handler(CommandHandler("set_sl", set_sl))
    dp.add_handler(CommandHandler("config", config_command))
    updater.start_polling()
    print("✅ 텔레그램 명령 리스너 실행 중")

if __name__ == '__main__':
    send_telegram("✅ 전략 봇 시작됨! (조건/TP/SL 실시간 설정 가능)")
    threading.Thread(target=run_bot).start()
    start_telegram_listener()
