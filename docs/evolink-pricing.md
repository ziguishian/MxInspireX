# EvoLink 公开价格

用量与计费的分类报价收录 `https://evolink.ai/zh/pricing` 2026-10-22 的 135 条公开记录。`evolink_price_data.json` 保存官网页面内嵌价格数据，`evolink_prices.py` 只读解析。公开目录不改变工作区模型可用性，不访问凭据、不触发模型发现。

人民币展示复用 `credits.usdToCny` 记账汇率（默认 7.2），同时展示美元原价、单位、来源与核对日期；不是实时外汇报价。手动报价、服务返回目录报价优先于网站快照。只对 EvoLink 服务的精确 API ID 应用对应公开价，不通过去除命名空间猜测模型。

网页文本价格底层为美元/千 Token，展示时乘以 1000；SKU 积分价格按官网数据使用的 68 积分/美元转换。缓存读写、长上下文倍率、图片 Token、按张、视频输入/输出秒和音频两首一组的单位保留。视频表头的最低价可能对应不同于产品默认 API ID 的变体，因此抓取最终渲染表中的 API ID、说明与单位，不能将参考视频价绑定到文生视频。公开报价全部为参考，不补算 EvoLink 实际扣费，不修改历史账单。

更新时下载官方公开页面，再执行：

```sh
python scripts/import-evolink-prices.py downloaded-pricing.html YYYY-MM-DD
```

导入只解析页面 JSON 与 HTML，不执行网页脚本。若官网结构变化，应让导入报错并检查，而不是补造报价。桌面打包通过 `build-sidecar.mjs` 显式携带 JSON 数据。

验证：`test_evolink_prices.py`、`test_model_prices.py`、前端 `modelEconomy.test.ts`。
