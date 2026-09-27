# codestrata

给一个 Python 仓库画两张图：

- **总图（static）** —— 全仓的包级架构。层次不是手工标的，而是由 import 出入度算出的
  「架构高度」`(out−in)/(out+in)`：+1 是入口、−1 是纯被依赖的叶子。
- **hot 图（runtime）** —— 跑一个真实 case（仓库自带的 demo / example），
  把实际发生的调用叠在**同一张图的同一套坐标**上。于是「这个 case 走了哪条路」一眼可见。

两张图共用节点与布局，差别只在数据来源：一个是 AST，一个是运行时 hook。

点任意节点可以看到该符号的源码（带真实行号），本地模式下还能一键跳进编辑器。

## 为什么不用 OpenGrok / Sourcetrail

- OpenGrok 要 Java + Tomcat + universal-ctags，为读代码架一套太重，而且它给的是**搜索与交叉引用**，
  不给「架构分层」这件事。
- Sourcetrail 2021 已归档；活着的 fork NumbatUI 明确禁用了 Python 索引。
- Hound / Zoekt 是搜索引擎，没有可供图链接的 per-symbol URL。

codestrata 只用标准库（Pygments 可选，用于高亮），`pip install` 之后一条命令出图。

## 用法

```bash
codestrata scan  <repo>                     # → .codestrata/index.json
codestrata graph <repo>                     # → .codestrata/overview.html（总图）
codestrata trace <repo> -- python demo.py   # → .codestrata/trace-<case>.json
codestrata graph <repo> --hot <case>        # → 总图 + hot 叠加
codestrata serve <repo>                     # 本地服务：图 + 源码 + 跳编辑器
```

## 状态

早期。已验证：AST 扫描（vllm-omni 1608 文件 / 3429 类 / 0 失败）、
高度分层（排序符合架构直觉）。

一个负面结论值得记下：**SCC 缩点不能用来分层**。Python 的循环 import 会让强连通分量退化——
在 vllm-omni 上 30 个包有 20 个塌进同一个环，分层信息全丢。启发式在这里胜过图论正解。

## License

MIT
