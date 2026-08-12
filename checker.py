from web3 import Web3
import requests
from datetime import datetime, timezone

# ---------- 配置区域（你需要修改的部分）----------
# 使用免费公共RPC节点[reference:1]
RPC_URL = "https://eth.llamarpc.com"
# 需要检查的钱包地址
WALLET_ADDRESS = "0x18da907cb9d981bc798acb87ac27b03a2dc3cbb7"
# 你的Etherscan API Key（免费申请：https://etherscan.io/register）
ETHERSCAN_API_KEY = "YOUR_API_KEY"
# 空投规则示例：最少交易笔数，最少交易量(ETH)[reference:2]
MIN_TX_COUNT = 10
MIN_VOLUME_ETH = 0.5
# ---------- 配置结束 ----------

def check_eligibility(address):
    # 1. 获取交易历史[reference:3]
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&apikey={ETHERSCAN_API_KEY}"
    try:
        data = requests.get(url, timeout=10).json()
        if data["status"] != "1":
            return f"API查询失败: {data.get('message', '未知错误')}"
        txs = data["result"]
    except Exception as e:
        return f"请求失败: {str(e)}"

    # 2. 分析数据
    if len(txs) < MIN_TX_COUNT:
        return f"❌ 交易笔数不足 ({len(txs)}/{MIN_TX_COUNT})"

    total_eth = sum(int(tx["value"]) for tx in txs) / 1e18
    if total_eth < MIN_VOLUME_ETH:
        return f"❌ 交易量不足 ({total_eth:.4f} ETH/{MIN_VOLUME_ETH} ETH)"

    return f"✅ 符合条件！交易 {len(txs)} 笔，总量 {total_eth:.4f} ETH"
    
# ----- 执行检查并打印结果（GitHub Actions会捕获这个输出）-----
if __name__ == "__main__":
    result = check_eligibility(WALLET_ADDRESS)
    print(result)