import os

# ========== 你的私有配置（部署时通过Render环境变量设置） ==========

# Telegram Bot配置
TELEGRAM_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# 扫描间隔（分钟）
SCAN_INTERVAL_MIN = int(os.environ.get("SCAN_INTERVAL", "30"))

# 评分阈值：高于此分数才推送通知
MIN_SCORE_ALERT = int(os.environ.get("MIN_SCORE", "30"))

# TVL异常检测阈值（50%涨幅触发告警）
TVL_ANOMALY_THRESHOLD = float(os.environ.get("TVL_THRESHOLD", "0.5"))

# 重点关注的链
FOCUS_CHAINS = [
    "Ethereum", "Arbitrum", "Optimism", "Base",
    "zkSync", "Solana", "Sui", "Aptos"
]

# 顶级VC名单（融到这些钱的项目空投价值更高）
TOP_VCS = {
    "a16z", "Paradigm", "Polychain", "Coinbase Ventures",
    "Binance Labs", "Sequoia", "Pantera", "Multicoin",
    "Jump Crypto", "Dragonfly", "Hashkey", "OKX Ventures",
    "Animoca Brands", "Framework", "Electric Capital"
}