# codestrata：一份静态分析 + 多次 runtime 的设计（修订版）

> 设计稿，2026-09-27。三个方向（存储 / 录制流程 / 界面）各出一份方案，合成后再经一轮审阅修订。
> - 依据：`codestrata/{trace,payload,serve,scan,notes,__main__}.py`、`web/app.js`、`web/ds.js`（commit 6c177e4），以及 vllm-omni 上的实测数据（`src/vllm-omni/.codestrata/trace-minicpmo-duplex.json`、`parts-minicpmo-duplex/`）。
> - 用户的补充（同一天）：图上要能在「静态图 ↔ runtime 图 1 ↔ runtime 图 2 …」之间切换（M4 的 run 选择器）；计划完成后直接按计划执行，只有 GPU 录制前先问。
> - 已定下的（原「需要拍板」第 1 条）：vllm-omni 的 runs 实际放在 `/mnt/data/duplex-agents/codestrata-runs/vllm-omni/`（数据一律放 /mnt/data），`duplex-agents/vllm-omni/runs` 是指过去的软链，`src/vllm-omni/.codestrata/runs → ../../../runs`。已有的 trace 和 parts 备份在 `/mnt/data/duplex-agents/codestrata-runs/backup-20260927/`。

---

## 1 目标与原则

**用户的原话**：「static analysis 只需要存一个，runtime 应该有多个，比如今天我跑 minicpm、明天我跑 qwen，但是我想将所有的 runtime 都能够存下来，只需要跑一次就能复用」。另外，模块图和时序图要能来回切换。

**原则**

1. **静态分析只存一份。** `.codestrata/{index,symbols,xref}.json` 是当前工作区的快照，只在显式 `scan` 时整份替换，不按 commit 存历史。
2. **runtime 可以有很多份。** 每次 `trace` 都生成一个新 run，不覆盖任何旧 run。
3. **录一次，永久复用。** run 是唯一不能重建的数据。run 目录里的东西分两类：
   - **原始数据**：`parts.tar.gz`、`events/raw.tar.gz`、`files/`、`legacy/`，以及 run.json 和 detail.json 里录制时写下的字段。finalize 之后就不再变；除了 `runs rm`，没有任何代码会删它或改它。
   - **派生数据**：`counts.json.gz`、`events/spans/`。都可以用 `runs merge` 从原始数据重建。
   - 读取端永远兼容所有 schema，不做就地升级。
4. **代码变了，run 仍然能用。** run 只存原始键（`rel:firstlineno`）和录制时实际执行的文件的哈希，加载时现映射到当前 index 上。每个文件单独标状态，不会让整个 run 作废。
5. **录制端先行。** 只有录制时才拿得到的东西都在任何 UI 工作之前做完：qualname、进程起止、退出原因、解释器和包版本、GPU、git、事件原始日志。读取端可以以后再写。
6. **实现尽量小。** 只用 stdlib，存文件、不用数据库；不引入新的配置文件格式；单文件导出继续可用；`to_package_graph`、`cut.py`、`layout.py` 都不改。

**现状的问题**（标「实测」的是在 vllm-omni 上验证过的：57 个进程，其中 5 个跑到了仓库代码）

- **同名 case 重跑会覆盖旧数据。** `trace.run()` 先清空 `parts-<case>/`，`cmd_trace` 再覆写 `trace-<case>.json`。
- **有冗余（实测）。** `funcs` 和 `func_edges` 逐键等于各阶段之和；只存阶段数据，gzip 后是 58 KB，原文件是 1.75 MB。
- **过期判断比错了对象。** `trace.stale_files()` 拿 run 去比工作区，但叠加用的行号来自 index。
- **serve 只能在启动时选一个 case。** `Handler.hot` 是类属性，换 run 要重启。
- **中断时会丢数据，还会留下孤儿进程。**
  - 超时或 Ctrl+C 时，`subprocess.call` 对 bash 发 SIGKILL，`trace_case.sh` 的 `trap stop_group EXIT` 来不及执行。
  - setsid 出去的 API server 和 engine core 变成孤儿，一直占着显存。
  - merge 又立刻执行，这些进程最后 ≤10 秒的数据丢了。
- **孤儿进程还会继续往 parts 目录写。** `_dump` 用 `os.makedirs(_out)` 建目录，每 10 秒落一次盘。
- **exec 会冲掉数据。** exec 之后 pid 不变，新程序写的 `part-<pid>.json` 会覆盖 exec 之前的数据。
- **`.codestrata/` 没被 git 忽略（实测）。** vllm-omni 的 `git status` 一直显示 `?? .codestrata/`。
- **老 trace 的 argv 被截断（实测）。** 只存了前 6 项，也没有 ppid；`payload._procs` 靠「有没有 ppid」来提示这件事。

### 1.1 决策

| 问题 | 决定 | 原因 |
|---|---|---|
| run 目录怎么组织 | 扁平的 `runs/<id>/`，id = `YYYYMMDD-HHMMSS-<case>` | glob 只需一层；按 id 排序就是按时间排序 |
| 存哪些数据 | 原始：`parts.tar.gz`（实测 5.1 MB 压到 365 KB）；派生：`counts.json.gz`（58 KB） | merge 逻辑还会改，原始数据在就能重算 |
| 事件日志 | 原始日志打包成 `events/raw.tar.gz`，永久保留；span 分块是派生数据 | 配对和折叠是最不成熟的逻辑 |
| 清单文件 | `run.json`（≤4 KB，列表只读它）+ `detail.json`（procs、file_shas、mapped、环境） | 列 100 个 run 时，不用读十几 MB |
| case 定义文件 | 不要。变体就是不同的 `--case` 名，外加 `--env`、`--tag`；`runs show` 打印重录命令 | 目标是录一次、复用，不是方便重录；也省掉 TOML 和对 3.11 的依赖 |
| 过期判断和谁比 | 和 index 比（scan 新写 `file_sha`）；老 index 没有这个字段时退回比工作区 | 叠加用的行号来自 index |
| 不在 index 里的文件 | 标 `outside`，不叠加，也不算过期 | 实测：examples 下的 demo，以及只在安装包里的 `_version.py` |
| qualname 回退 | 在 `to_package_graph` 之前改写键，用 `(f, qualname) → 符号键` 查 | 改动面小；`__init__.py` 里的函数也能对上 |
| REF 语法 | `完整 id \| case`，外加可选的 `@阶段` | 够用；id 前缀和日期冲突 |
| `runs` 子命令的形式 | `codestrata runs <repo> <动词>`，两者都必填 | 避免可省略的 repo 把动词当成自己 |
| 迁移 | 自动做；用 rename 认领；老文件压成 gz 留在 `legacy/` | 幂等，可以并发，不丢数据 |
| run 放在哪 | `.codestrata/runs/`，可以是软链；vllm-omni 在迁移之前先建软链，指向 `duplex-agents/vllm-omni/runs/` | `rm -rf` 只删链接本身；src/ 是上游的 clone |
| 跨进程关系 | 只画确定的 ppid 派生 | 宁可不画，也不画错；和 xref「宁可不跳，也不跳错」一致 |
| 多 run 导出 | 主 run 全量嵌入，其余 run 只嵌计数；放在最后一个里程碑 | 省下的额度留给全文 |
| serve 运行中热加载 index | 不做，scan 之后重启 serve | 和多 run 无关 |
| 事件什么时候开始录 | M3，排在所有 UI 之前；开销实测通过后默认打开 | 录制端先行 |
| 引用时不写 `@阶段` | CLI 里表示「全部阶段」，兼容现在的 `--hot case`；网页上有 serving 就预选 serving | 兼容老用法，网页上又是最常用的默认值 |
| 环境变量 | 只记录 `--env` 设的变量，不抓整份环境 | 防止把 token 存进去 |

---

## 2 名词

| 词 | 含义 | 存在哪 | 能否重建 |
|---|---|---|---|
| **static**（静态索引） | 单元、import 边、符号、切面、交叉引用 | `.codestrata/index.json`、`symbols.json`、`xref.json` | 随时 `scan` |
| **case** | 一种跑法的名字。MiniCPM 和 Qwen 就是两个 case 名；每个 run 里都存着当时的命令和 `--env` | run.json | — |
| **run** | 某个 case 的一次录制，只增不删 | `.codestrata/runs/<id>/` | **不能** |
| **原始 / 派生** | 见原则 3 | run 目录 | 原始的不能；派生的用 `runs merge` 重建 |
| **phase** | run 里的一段时间，由 case 脚本写 `$CODESTRATA_OUT/PHASE` 划分；从没写过的 run 只有 `start` 一个阶段 | counts.json.gz | — |
| **REF** | CLI 和 API 里引用 run 的写法，见 4.5 | — | — |
| **tag / note** | 人给 run 加的标签和备注 | run.json | — |
| **file_state** | run 里每个文件相对当前 index 的状态：same / changed / mismatch / outside / gone / unknown | 加载时现算 | — |
| **events** | 跨文件调用的原始事件，分 C / R / Y / S 四种（见 7.1） | `events/raw.tar.gz` | 不能 |
| **span** | 由事件配对得到的一次跨文件调用 | `events/spans/` | 能 |
| **cut**（切面） | 已有概念：当前展开着的目录集合，两张图共用 | URL | — |

---

## 3 存储布局与格式

### 3.1 目录树

```
<repo>/.codestrata/
  .gitignore            内容是 "*"；_outdir() 建目录时写入
  README.txt            一行：「除 runs/ 外都能删；runs/ 是录制数据，不能重建」
  index.json symbols.json xref.json     静态索引：只有一份，scan 时覆盖
  overview*.html tasks/ …               其他缓存
  runs/                 可以是软链；scan 不碰它
    .tmp-<id>/          只在迁移过程中存在
    20260927-153412-minicpmo-duplex/
      run.json          小；列表页只读这个
      detail.json       原始：procs、leftovers、file_shas、mapped*、pythons、gpu、git.dirty、script、files 索引
      parts.tar.gz      原始：各进程写出的分片
      files/            原始：case 脚本、argv 里出现的小文本文件、--attach 指定的文件
      legacy/           原始：只有迁移来的 run 才有，里面是 trace-<case>.json.gz
      counts.json.gz    派生
      events/raw.tar.gz 原始：只有录了事件的 run 才有
      events/spans/     派生：keys.json、index.json、p<pid>-NNN.jsonl.gz
      parts/            只在录制期间存在
```

- **新录制的 run id**：建目录时用 `mkdir(exist_ok=False)`，同一秒撞名就加 `-2`。迁移来的 run 的 id 是确定的，见 3.7。
- **所有写操作都是原子的**：先写 tmp，再 `os.replace`。
- **runs/ 不会被扫进 index**：`scan.iter_py_files` 跳过以点开头的目录，所以 runs/ 里存的 `.py` 快照不会进 index。

### 3.2 run.json（列表页只读这个文件）

| 字段 | 例子 / 说明 |
|---|---|
| `schema` | `2`；老的 `trace-*.json` 算作 1 |
| `id` / `case` | `"20260927-153412-minicpmo-duplex"` / `"minicpmo-duplex"`；case 名只允许 `[A-Za-z0-9._-]` |
| `status` | `recording` / `ok` / `partial` / `failed`，定义见 4.2 |
| `problems` | `["超时", "2 个进程被强杀"]` |
| `stop` | `exit` / `timeout` / `interrupt` / `driver-lost` |
| `driver` | `{"pid": 81234, "start": <取自 /proc/<pid>/stat 的 starttime>}`；判断 driver 是否还活着时，用它防止 pid 被复用 |
| `created` / `duration_s` / `returncode` / `host` | |
| `cmd` / `cwd` | 和现在一样 |
| `env` | 只含 `--env` 设的变量 |
| `git` | `{"commit": "a8576cc…", "branch": null, "n_dirty": 0}`；dirty 列表在 detail.json；不是 git 仓库时为 null |
| `clock` | `{"mono0_ns", "wall0"}`；driver 起跑的时刻，所有 `*_us` 都相对 `mono0` |
| `phases` | `[{"name": "serving", "t_us": …, "n_funcs": 1657, "n_calls": 934915}, …]`；`t_us` 由 driver 每 100 ms 轮询 PHASE 得到；迁移来的 run 为 null |
| `summary` | `{n_funcs, n_func_edges, n_files, n_procs, n_procs_active, n_mapped, n_leftovers, n_unclean}` |
| `events` | `null` 或 `{n_lines, n_spans, n_calls, n_procs, truncated: [pid…], bytes}`（bytes 是 events/raw.tar.gz 的大小）；整理 span 失败时是 `{error, bytes}` |
| `tags` / `note` | run 完成后，只有这两个字段还会被 CLI 改写 |
| `migrated_from` | 只有迁移来的 run 有 |
| `sizes` | 各文件的字节数，`runs ls` 汇总大小用 |

### 3.3 detail.json（加载某个 run 时才读）

```json
{"sha_of": "executed",
 "file_shas": {"vllm_omni/entrypoints/openai/api_server.py": "9a1b…"},
 "mapped_from": "/…/venv/lib/python3.12/site-packages/vllm_omni",
 "mapped": {"<rel>": "<实际执行的路径>"},
 "mapped_mismatch": [], "mapped_only_installed": ["vllm_omni/_version.py"],
 "procs": [{"pid": 1, "ppid": 0, "argv": ["…"], "argv_cut": false, "n_funcs": 2962,
            "t0_us": 0, "t1_us": 412000000, "why": "atexit", "py": "/…/python3.12"}],
 "leftovers": [{"pid": 1, "argv": ["…"], "signal": "SIGTERM"}],
 "pythons": {"/…/venv/bin/python3.12": {"version": "3.12.3",
             "dists": {"vllm": "…", "vllm-omni": "0.30.0", "torch": "…"}}},
 "gpu": [{"index": 0, "name": "…", "driver": "…", "mem_mib": 32607}],
 "git": {"dirty": []},
 "script": {"path": "../../trace_case.sh", "stored": "files/trace_case.sh"},
 "files": [{"path": "/…/deploy/minicpmo_4_5_rtx5090.yaml", "sha": "…",
            "stored": "files/minicpmo_4_5_rtx5090.yaml", "why": "argv"}]}
```

- **`sha_of`**：新 run 是 `"executed"`，哈希的是实际执行的文件（映射过的就是安装包里那份）；迁移来的 run 是 `"repo"`。
- **`dists`**：driver 列出 hook 报告的 `site` 目录下的 `*.dist-info` 目录名，得到每个包的版本。
- **`gpu`**：`nvidia-smi --query-gpu=index,name,driver_version,memory.total`，超时 5 秒，失败记 null。
- **`files` 从三处自动收集**：
  - case 脚本，沿用 `trace.case_script`；
  - 任何进程的 argv 里出现的、实际存在、不超过 200 KB 的 `.sh/.py/.yaml/.yml/.json/.toml` 文件。vllm-omni 上就是 `--deploy-config` 指向的 yaml；
  - `--attach` 指定的文件。`common.sh` 这类被 source 的文件不会出现在 argv 里，要靠它。
- **不做模型指纹**：server 的 argv 里本来就有模型路径。

### 3.4 counts.json.gz（派生）

```json
{"phases": {"start":   {"funcs": {"<rel>:<firstlineno>": 1}, "func_edges": {"<a>|<b>": 1}},
            "serving": {"funcs": {}, "func_edges": {}}},
 "names":  {"<rel>:<firstlineno>": "Cls.method"}}
```

- **只有一个阶段时也要存。** 老的 merge 在这种情况下会丢掉阶段名。
- **`runs.load_counts(run, None)`** 把各阶段加起来，就是现在 `tr["funcs"]` 的含义。
- **`file_edges` 不存。** 它只在内存里算，用来打印摘要。

### 3.5 run 和当前 index 怎么对上

1. **scan 写 `file_sha`。**
   - 写到 symbols.json 里，形如 `{rel: sha16}`。
   - 在 `scan()` 解析源码时，用已经读进来的字节顺手算，不再多读一遍；哈希函数和 `trace.file_shas` 相同。
   - `write_index` 多写一个键就行。
2. **`runs.file_state(detail, idx, repo)` 给每个文件定状态。**
   - `mismatch`：rel 在 `mapped_mismatch` 里，也就是录制时安装包就和仓库不一致。优先判这个。
   - `outside`：rel 不在 `idx["files"]` 里，但在工作区里存在，或者在 `mapped_only_installed` 里。这类文件不叠加，也不算过期。
   - `gone`：rel 不在 index 里，工作区里也没有。
   - `changed`：`file_shas[rel]` 和 index 的 `file_sha[rel]` 不同。
   - `unknown`：run 没存哈希。如果是老 index 没有 `file_sha`，就退回 `trace.stale_files` 去比工作区。
   - `hotMeta.file_state` 只列不是 same 的文件。同时保留 `hotMeta.stale_files`（= changed + mismatch），前端现有的显示不用改。
3. **qualname 回退（M6）：`runs.remap(counts, names, file_state, idx)`。**
   - 只处理 changed 和 mismatch 的文件。
   - 用 symbols 建 `(s["f"], s["n"]) → 符号键` 的映射（实测没有重复键）。命中的，把键改写成 `rel:<有 dl 就用 dl，否则用 l>`。
   - 带 `<locals>` 的、`<lambda>`、查不到的，都保留原行号，并计入 `hotMeta.unmatched`。
   - 改写后撞到同一个键的，计数相加。
4. **`to_package_graph` 不改**，调用方式也不变。

### 3.6 并发与原子性

- **录制一开始就写 `run.json`**：`status: recording`，并写下 `driver`。每个 run 有自己的 `parts/`，同时录两个 run 也不会互相踩。
- **hook 不建目录**：`_out` 不存在时，`_dump` 和 `_snapshot` 什么都不写。
- **finalize 的顺序**：
  1. 停掉残留进程（M2 起）；
  2. 合并；
  3. 写派生数据；
  4. 把 parts 打包到 tmp，重新打开核对成员数；
  5. `os.replace`；
  6. 删掉 `parts/`；
  7. 写最终状态。

  任何一步失败都保留 `parts/`，状态停在 recording，并打印 `runs merge` 的用法。
- **finalize 之后**：原始数据不再变；tags 和 note 由 CLI 用 tmp + `os.replace` 改写；派生数据只由 `runs merge` 重写。
- **serve 对 runs 只读。** 不加锁。两个 run 抢 GPU 的问题，交给 case 脚本自己的 `check_gpu_free`。

### 3.7 迁移现有的 trace-*.json

**触发时机**：`runs.catalog(repo)` 第一次被调用时。serve、graph、tasks/pack `--hot`、runs、trace 都会调用它。

**步骤**（幂等，可以并发）：

1. **收拾上次的残留。** 发现 `runs/.tmp-*/legacy/trace-*.json` 时，说明上次迁移中断了：把老文件挪回 `.codestrata/`，删掉 tmp，从头来。
2. **定 id，判断是否已迁过。** id 用老文件的 mtime 加 case 名，每次算出来都一样。`runs/<id>` 已经存在、而且 `migrated_from` 相同，就跳过。
3. **建好并核对。** 在 `runs/.tmp-<id>/` 里写好 run.json、detail.json、counts.json.gz。对「全部」和每个阶段，都要求 `load_counts` 的结果和老数据**逐键相等**；不相等就删掉 tmp、保留老文件、打印原因。
4. **认领。** 执行 `os.rename(trace-<case>.json → .tmp-<id>/legacy/trace-<case>.json)`。遇到 FileNotFoundError，说明另一个进程正在迁移：删掉自己的 tmp，退出。
5. **打包。** 把 legacy 压成 gz；把 `parts-<case>/` 打包成 parts.tar.gz，核对通过后删掉目录。
6. **落位。** 执行 `os.rename(.tmp-<id> → <id>)`，打印一行说明。

**字段去向**：

| 老字段 | 去向 |
|---|---|
| `case`、`cmd`、`cwd`、`returncode` | run.json |
| `pids` | detail.procs。没有 ppid 的，写 `argv_cut: true`，`payload._procs` 改成读这个字段；`t0_us`、`t1_us`、`why` 为 null |
| `phases`（为空时用 `funcs` / `func_edges`） | counts.json.gz。为空时只有一个阶段，名字叫 `start` |
| `file_shas`、`mapped*`、`script` | detail.json，`sha_of: "repo"`；脚本文本存进 `files/` |
| `parts-<case>/` | parts.tar.gz |
| 整个老文件 | `legacy/trace-<case>.json.gz` |

- **状态**：returncode 为 0 的记 `ok`，否则记 `partial`。`git` 为 null。
- **要迁的两份**：vllm-omni 的 `minicpmo-duplex`，codestrata 自己的 `scan-export`。

---

## 4 录制流程与命令

### 4.1 变体：用不同的 case 名，加上 `--env`

不设 case 定义文件。MiniCPM 和 Qwen 就是两个 `--case` 名，差别用 `--env` 传给脚本，用 `--tag` 标出来：

```bash
cd ~/projects/duplex-agents/vllm-omni
codestrata trace src/vllm-omni --case minicpmo-duplex --timeout 1500 \
    --tag model=MiniCPM-o-4_5 --attach ../../common.sh -- bash ../../trace_case.sh
codestrata trace src/vllm-omni --case qwen25omni-chat --timeout 1500 \
    --env MODEL_NAME=Qwen2.5-Omni-7B --env DEPLOY_NAME=qwen2_5_omni_rtx5090.yaml \
    --env SERVED_NAME=Qwen/Qwen2.5-Omni-7B --env DEMO=chat \
    --tag model=Qwen2.5-Omni-7B --attach ../../common.sh -- bash ../../trace_case.sh
```

- `runs show` 会打印一条可以直接复制的重录命令，由 `cmd`、`env`、`tags`、`note` 拼出来。
- **Qwen 要先在 duplex-agents 那边做的事**（不在 codestrata 里，由用户那边做）：
  - `common.sh`：
    ```bash
    MODEL="$ROOT/models/${MODEL_NAME:-MiniCPM-o-4_5}"
    DEPLOY="$ROOT/deploy/${DEPLOY_NAME:-minicpmo_4_5_rtx5090.yaml}"
    SERVED_NAME=${SERVED_NAME:-openbmb/MiniCPM-o-4_5}
    ```
  - `trace_case.sh`：用 `case "${DEMO:-duplex}"` 选择跑哪个 demo。
  - 新写 `deploy/qwen2_5_omni_rtx5090.yaml`：上游那份 `vllm_omni/deploy/qwen2_5_omni.yaml` 是在 2×H100 上验证的。
  - 把权重下载到 `/mnt/data`，再在 `models/` 下建软链。现在 `models/` 下只有 `MiniCPM-o-4_5`。

### 4.2 trace 流程

1. **准备 run。**
   - 校验 case 名；
   - `runs.new_run()` 建目录，写 run.json（`status: recording`，带上 cmd、env、git、clock、driver）；
   - `CODESTRATA_OUT` 指向 `<run>/parts`。PHASE 约定不变，`trace_case.sh` 一行都不用改。
2. **启动命令。** 改用 `Popen(cmd, cwd=repo, env=…, start_new_session=True)`。driver 每 100 ms 做两件事：`wait(timeout=0.1)`，以及读一次 `parts/PHASE`，阶段一变就记下 `t_us`。
3. **停的时候分三级。** 碰到超时、driver 收到 SIGINT 或 SIGTERM 时：
   - 先对整个进程组发 SIGINT，让 case 自己的 `trap stop_group EXIT` 收尾；
   - 等 `--stop-grace` 秒（默认 90），再发 SIGTERM；
   - 再等 15 秒，最后发 SIGKILL。

   第二次按 Ctrl+C 时直接升级一级。
4. **清理残留进程（M2）。**
   - 命令退出后，扫 `/proc/*/environ`，找出 `CODESTRATA_OUT` 等于本 run parts 的进程（setsid 出去的进程也继承了这个变量）；
   - 按同样的三级顺序停掉，记进 `detail.leftovers`；
   - 等 2 秒，让它们最后落一次盘。

   只有 Linux 能这样做，其他系统上只停进程组。
5. **finalize。** 按 3.6 的顺序执行。录了事件的，再做 7.3 的整理。
6. **定状态。**
   - `ok`：returncode 为 0、`stop=exit`、没有 unclean 的进程、没有残留进程。
   - `partial`：有数据，但不满足 ok 的某一条；原因写进 `problems`。
   - `failed`：合并后一个函数都没有。
7. **打印结果。** 解析出的 run id、摘要（沿用现在 `cmd_trace` 的输出）、警告、重录命令。

### 4.3 hook（`trace._SITECUSTOMIZE`）的改动

除事件外，这些改动都在 M1 做：

- **`_names`**：键第一次出现时记下 `code.co_qualname`，用 `getattr` 取；Python 3.10 取不到就跳过。
- **进程起止时刻**：`_t0 = time.monotonic_ns()` 在 import 时记一次，fork 之后在子进程里重记。每次 `_dump` 都写进 `t0` 和 `t`。
- **`_dump(why)`**：`why` 取 `atexit` / `_exit` / `exec` / `periodic` / `phase` 之一。最后一次落盘是 `periodic` 的进程是被强杀的，算作 unclean。
- **`py`**：记下 `{version, executable, site: site.getsitepackages()}`。
- **exec 前先落盘**：包一层 `os.execv` 和 `os.execve`（`os.exec*` 系列最终都走这两个），调用前先 `_dump("exec")`。
- **part 改名**：
  - 新名字是 `part-<pid>-<t0ns>.json` 和 `part-<pid>-<t0ns>@<n>-<phase>.json`，exec 之后的新程序不会再覆盖旧数据；
  - `trace.merge` 两种命名都认，老 run 执行 `runs merge` 也能用。
- **不建目录**：`_dump` 和 `_snapshot` 里去掉 `os.makedirs`。
- **事件（M3）**：由 `CODESTRATA_EVENTS=1` 打开，格式见 7.1。

**实现时（M1 评审之后）补上的几条**：

- **落盘串行**：落盘线程（`periodic` / `phase` / `stop`）和主线程（`atexit` / `_exit` / `exec`）共用一把 RLock，临时文件名带线程号；主线程的最后一次落盘一开始，落盘线程就不再写（否则更早拷贝的计数可能最后 rename、盖掉最终那份）。fork 后重建锁。实测不加锁时，进程退出撞上定时落盘会把分片写坏，merge 悄悄丢掉整个进程。
- **不装信号处理器**：曾试过给没人接管的 SIGTERM 装一个「先落盘再退出」的处理器，评审证明它改变被 trace 的程序的行为（Python 层处理器要等主线程回到解释器，卡在 C 里的进程收到 SIGTERM 不再立刻死，multiprocessing 退出会挂住；链式调用旧处理器的程序被直接杀掉）。改为：driver 升级到 SIGTERM 之前写 `$CODESTRATA_OUT/STOP`，落盘线程 1 秒内看到就落一次（`why=stop`），driver 等 1.5 秒再发信号。
- **最后一次落盘不能被打断**：被 trace 的程序自己的信号处理器可能在落盘中途抛 KeyboardInterrupt / SystemExit，吞掉重试；`os._exit` 的包装无论如何都会真的退出（否则 fork 出的子进程会逃进父进程的代码）。
- **哈希在执行时取**：每个进程第一次跑到一个文件时记下它的内容哈希（`shas`），detail 的 `file_shas` 用它；和收尾时磁盘上的对不上的记进 `changed_during`，run 标 partial。
- **argv 在 import 时读一次**并记 `argv_cut`；之后 `/proc/self/cmdline` 若被 setproctitle 改了，另记 `title`。
- **残留进程的第二种认法**：分片里记 `st`（`/proc/self/stat` 的启动时刻）。vLLM 的 engine core 用 setproctitle，它默认会清空 `/proc/<pid>/environ`；driver 设 `SPT_NOENV=1`，并且把「分片文件名里的 pid 还活着、启动时刻一致」的进程也算作本 run 的。
- **driver 的信号**：SIGINT / SIGTERM / SIGHUP / SIGQUIT 都接管（已被忽略的，比如 nohup 下的 SIGHUP，保持忽略）；SIGQUIT（Ctrl+\\）跳过 SIGINT 那一级。处理器一直装到 finalize 做完，收尾中途按 Ctrl+C 不会把打包打断。
- **finalize 拆成两步**：`capture`（detail.json、files/，只写一次）和 `derive`（计数、状态）。`runs merge` 只重做 derive，原始分片取 parts.tar.gz 和散着的 parts/ 的并集，不会拿少的盖多的；包已替换好、只是 parts/ 没删干净，不算失败。
- **残留进程停完再找一遍**（最多三轮）：残留的 bash 在 EXIT trap 里还会起新的子进程，它们同样带着本 run 的环境。
- **`runs rm` 只认完整的 run id**（case 名解析到「最新一次录完的」，用它删东西会删错），还在录的不删。

### 4.4 命令全表

```
codestrata trace <repo> --case NAME [--tag T]… [--note TXT] [--env K=V]… [--attach F]…
                        [--events] [--timeout S] [--stop-grace S] -- CMD…

codestrata runs <repo> ls [--case C]           按 case 分组，最新的在前。第一行打印 runs/ 的 realpath；
                                               每行：id、状态、时长、活跃进程数、git 短哈希、
                                               改过的文件数、tags、大小。runs/ 超过 1 GB 时警告
codestrata runs <repo> show REF                run.json、detail 摘要、相对当前 index 的 file_state、重录命令
codestrata runs <repo> tag REF TAG… | untag REF TAG… | note REF TEXT
codestrata runs <repo> rm REF… [--events-only] [--yes]      要确认：run 不能重建
codestrata runs <repo> merge REF               从原始数据重建派生数据；driver 死了时从 parts/ 合并。
                                               还有进程带着这个 run 的 CODESTRATA_OUT 时拒绝执行

codestrata serve <repo> [--hot REF]            --hot 只决定打开页面时先选哪个 run（M4 起）
codestrata graph <repo> [--hot REF] [--out F]  M7 起 --hot 可以给多个，并支持 --compare
codestrata tasks|pack <repo> … [--hot REF]
```

`runs` 的 repo 和动词都必填，写法和现有的 `pack <repo> <target>` 一样。

### 4.5 REF 语法（全部在 `runs.resolve(repo, ref)` 里解析）

```
REF := (<完整 run id> | <case>) ["@" PHASE]
```

- **先当完整 id，再当 case 名。**
- **只写 `<case>`**：取这个 case 最新一次 `ok` 的 run；一次 ok 都没有时，取最新的 `partial` 并打印警告。
- **不写 `@PHASE`**：各阶段相加，和现在 `--hot case` 的含义相同。现在的 `minicpmo-duplex@serving` 写法照旧能用。
- **每条命令都打印解析到的完整 id。**
- **导出的默认文件名**：`overview-<case>@<phase>.html`，只保留 `[A-Za-z0-9@._-]` 这些字符。

---

## 5 serve / API

**`serve.Handler` 的改动（M4）**

- **去掉类属性 `hot` / `hot_meta`**，换成 `self._hot(run_id, phase)`。
  - 它内部调用 `runs.load(...)`，结果放进 LRU（8 项，带锁）。
  - 缓存键是 `(run_id, phase, counts.json.gz 的 mtime)`。
  - 一次加载：读 58 KB 的 gz，调 `to_package_graph`，约 20 ms。
- **`_graphs` 的缓存键加上 run**；M7 再加 cmp。
- **index 不热加载**，scan 之后照旧重启 serve。启动时用 xref 的 `fp` 数一下 scan 之后改过的文件，落后就打印出来。
- **`serve.main(hot=)`** 只用来决定打开页面时先选哪个 run，通过 `/api/runs` 的 `default` 字段交给前端。
- **不做文件监视。** `/api/runs` 每次请求都现 glob 一遍，解析结果按 mtime 缓存。

**路由**（标注从哪个里程碑开始有）

```
GET /api/runs                                      M4  run 列表
GET /api/graph?open=&w=&run=REF[&cmp=REF]          M4 加 run；M7 加 cmp
GET /api/edge?a=&b=&run=REF[&cmp=REF]              M4 / M7
GET /api/refs?t=&run=REF                           M4
GET /api/pack/<t>?run=REF                          M4
GET /api/seq/overview?run=REF                      M5  每个进程 400 格的调用密度
GET /api/seq?run=REF&open=&t0=&t1=&max=300         M5  折叠后的时序
GET /api/seq/find?run=REF&a=&b=&after=             M5  一条边下一次出现的时刻
```

**返回的数据形状**

- `/api/runs`：
  ```
  {default, runs: [{id, case, status, problems, created, duration_s, git: {commit}, tags, note,
                    phases: [{name, n_funcs}], n_procs_active, events: bool, stale: null | {…}}]}
  ```
  `stale` 在下拉框第一次展开时再算：要读 detail.json，结果按 run_id 缓存。
- **`hotMeta`**：保留现有的全部键（`case`、`phase`、`phases`、`n_procs`、`procs`、`stale_files`、`mapped_*`、`script`、`unmapped`），另外加 `run_id`、`status`、`problems`、`git`、`tags`、`note`、`file_state`、`unmatched`、`events`。
- **对比（M7）**：
  - 把 `payload.graph_payload` 里按切面汇总 hot 的两个循环（`hp` / `he`）抽成 `_hot_on_cut(hot, node_of)`，A、B 各调一次；
  - 返回多一个块：`cmp: {ref_b, nodes: {id: [nA, nB]}, edges: {"x|y": [nA, nB]}}`；
  - `runtimeOnlyEdges` 和「只看跑到的」都取 A∪B。

---

## 6 界面

### 6.1 run 选择器（M4）

- **工具栏 `.bar` 加一段**：`运行 [▼]  阶段 [全部|start|serving|shutdown]`。M5 再加 `模块图 | 时序图`，M7 再加 `对比 [无 ▼]`。
- **下拉列表**：
  - 按 case 分组；
  - 每一行显示 tags、日期、git 短哈希、活跃进程数、各阶段的函数数、`⚠ 改过 12 个文件`，录了事件的再加一个「时序」标记；
  - `partial` 的行灰一点，并显示 `problems`。
- **什么时候刷新列表**：打开下拉时、页面重新获得焦点时。有新 run 只在按钮上加个小点，不自动切过去。
- **状态写进 URL hash**：`#run=<id>@<phase>`，M5 加 `&view=seq`，M7 加 `&cmp=`。hash 里存的是解析好的完整 id，刷新页面后看到的还是同一个 run。
- **打开页面时的初始选择**：先看 hash，再看 `serve --hot`，都没有就只显示静态图。选中一个 run 时，有 serving 阶段就预选它。
- **`app.js` 的改动**：
  - 把 `setCut(open, focus)` 推广成 `load({open, run, view}, focus)`，沿用 `_cutSeq` 丢弃过期的响应，也沿用保留选中的逻辑；
  - `header()` 和 `runHtml(m)` 按当前选中的 run 重画。
- **`ds.js` 的改动**：`graph(open, w, run)`，加 `runs()`。
- **file_state 怎么显示**：
  - 横幅上写「⚠ 这个 run 录制后改过 12 个文件」；
  - `mismatch` 单独一句「录制时安装包和仓库不一致」；
  - `outside` 不提示；
  - 文件树里过期的文件加 `--stale` 色标。

> M1 就要先改的两处文案：
> - 横幅上「重跑 trace 即可」改成「这些文件上的叠加可能偏」；
> - argv 截断的提示改为读 `argv_cut`。

### 6.2 模块图和时序图的切换（M5）

- **切换按钮**：工具栏上的 `模块图 | 时序图`。当前 run 没录事件时按钮置灰，提示用 `trace --events` 录。
- **两张图共享的东西**：选中状态 `CS.graph.state.sel` / `selEdge`，以及切面 `open`。
  - 点生命线头 = 选中节点，面板照旧走 `showPkg`；
  - 点一条消息 = 选中边 `a|b`，走 `showEdge`，再附上这条消息的时刻、时长、pid/tid、两端的函数；
  - 生命线头上的 ＋ 走 `app.expand`；切面一变，两张图都重新取数据；
  - 边详情里加「在时序图里看」，用 `/api/seq/find` 定位到这条边出现的时刻。
- **时间刷**：视图顶上一条带，画 `/api/seq/overview` 返回的每个进程的调用密度，框选就是选时间窗。默认窗口从当前阶段的起点开始，自动收窄到折叠后不超过 300 行。
- **前端实现**：新文件 `web/seq.js`，用 SVG 画进 `.gbox`，复用 graph.js 的配色 token；加进 `render.SCRIPTS`。

### 6.3 对比（M7）

| 情况 | 画法 |
|---|---|
| 只有 A 跑到 | 橙色，沿用 `--hot` |
| 只有 B 跑到 | 紫色，新 token `--hotb`，明暗两套 |
| 两边都跑到 | 前景色 `--fg` 实线，粗细 ∝ log(max)；tooltip 写 `A 1.2k / B 30` |
| 两边都没跑到 | 退到背景 |

- 对比时不重新排版。
- 边详情：`_pair_detail` 和 `edge_detail` 加参数 `hot_b`，每个 item 多一个 `calls_b`。
- 两个 run 一个录了事件、一个没录时，横幅上提示「调用次数受录制开销影响」。

---

## 7 时序图的数据

### 7.1 录制（M3，`CODESTRATA_EVENTS=1`）

**记哪些事件**

- **只记跨文件的调用**，口径和 `func_edges` 相同：调用方是栈顶的仓库帧、rel 和被调方不同。调用方为空（从仓库外进来）的不记。
- **帧标识**：`fr = id(sys._getframe(1))`。setprofile 回退路径下直接用 frame。
- **hook 状态**：`_xf = {fr: 1}`，记下「这一帧是跨文件进来的」。各事件的处理：
  - PY_START 且跨文件：写 C，并登记 `_xf[fr]`；
  - PY_RETURN / PY_UNWIND：`fr in _xf` 时写 R，并删掉 `_xf[fr]`；
  - PY_YIELD：`fr in _xf` 时写 Y；
  - PY_RESUME：`fr in _xf` 时写 S。

  配对靠帧标识，不靠栈的顺序，所以同一线程里 asyncio 协程交错也不会错配。

**行格式**（文本）

```
N 3 MainThread                           线程登记：进程内的小整数 tid → 线程名
K 17 vllm_omni/engine/async_omni.py:241  键登记：进程内的 id → rel:firstlineno
C <t_ns> <tid> <fr> <调用方 id> <被调方 id>
R <t_ns> <tid> <fr>                      返回，或异常展开
Y <t_ns> <tid> <fr>                      挂起
S <t_ns> <tid> <fr>                      恢复
T                                        达到上限，之后不再记（计数不受影响）
```

**缓冲与落盘**

- 事件先在进程内缓冲。现有的落盘线程 `_flusher` 每秒把缓冲换出来，追加到 `parts/ev-<pid>-<t0ns>.log`；`_dump` 时也刷一次。
- fork 之后，子进程清空缓冲、键表、线程表和 `_xf`。

**上限**：每个进程最多 `CODESTRATA_EV_MAX` 行，默认 300 万。实测 serving 阶段所有进程合计 443,474 次跨文件调用。

**真值测试**（CPU 上跑，放在 `tests/trace_cases/`），每一项都要配对正确：

- 同步嵌套；
- 返回后再调用；
- 生成器；
- 异常展开；
- 两个 asyncio 任务在同一线程里交替调用另一个文件；
- 多线程；
- fork；
- exec。

同时验证 `sys._getframe(1)` 在 sys.monitoring 回调里确实是被监控的帧；如果不是，只能退回用栈配对，并在 run.json 里标出 `pairing: "stack"`。

**实现时的调整（M3）**：

- 日志里不写帧地址，写**进程内的 span 号**：C 时分配（`itertools.count`，多线程也不重号），`_xf` 记 `id(帧) → span 号`，R / Y / S 写 span 号。配对因此是精确的，帧地址被复用也不会串。
- 时间写**相对这个进程映像 t0 的微秒**，文件开头一行 `H <pid> <t0_ns> <ppid>`；整理成 span 时换算成相对 run 的 `mono0`。
- 真值测试证实：sys.monitoring 回调里 `sys._getframe(1)` 就是被监控的那一帧，同一帧的 START / YIELD / RESUME / RETURN 拿到的 id 相同，同一个协程函数的两个并发实例 id 不同。
- 线程的入口（`Thread.run`）在仓库外：线程里第一个仓库函数没有「调用方」，和 func_edges 一样不记；它再调别的文件才有事件。
- 原始日志不进 parts.tar.gz，单独打成 `events/raw.tar.gz`；`runs merge` 取它和散着的 `parts/ev-*.log` 的并集重建 span。
- M3 评审后补上的：
  - **PY_THROW 也要订阅**（`throw()` / `close()` / asyncio 取消经它恢复帧，否则清理代码里的调用挂错父亲），而且它和 PY_UNWIND 一样**不能 DISABLE**——返回 DISABLE 会在被 trace 的程序里抛 ValueError（测试里 asyncio 取消就这样崩过）。
  - `_xf` 存 `(span 号, code)`：半路被丢掉的生成器在 3.12 上关闭时不发事件，帧地址会被别的帧复用；code 对不上就作废旧账。这种 span 显示为没返回（-1）。
  - 线程号缓存在线程局部变量里，不按 `get_ident()`（glibc 会把退出线程的 ident 分给新线程）。
  - 行数上限只管调用（C）；返回 / 挂起 / 恢复照写，否则上限之前开始的调用会显示成没返回。上限到了只在 events 摘要里标 truncated，**不改 status**（计数是完整的，case 名不该因此跳到更早的一次）。
  - 事件缓冲写成功才删；日志按 UTF-8 + backslashreplace 写，名字里的换行替换掉；解析时丢掉没有换行结尾的最后一行。
  - 第一级折叠按 **(父 span, 段)** 认兄弟（不按深度）：同一线程上交错的两个协程，子调用深度相同但不是兄弟；「段」是这个线程上两次挂起 / 恢复之间，合出来的一行因此不会盖住别的协程的调用。
  - 同一 pid 的多个映像（exec 前后）线程号接着编；原始日志先落包再整理 span，整理失败只记在 events 摘要里（`error`），不耽误计数。
- 测试：`tests/test_runs.py` 的 `test_events_*`，场景在 `tests/trace_cases/fake_repo/fakesvc/truth.py`（多了一个第一级折叠的场景：连续 50 次叶子调用合成一条 rep=50，有跨文件子调用的不合）。fake_service 上各阶段 span 的 Σrep 和跨文件 func_edges 逐阶段相等。

### 7.2 时钟

- 用 `time.monotonic_ns()`。它在 Linux 上是 CLOCK_MONOTONIC，全机共享，不同进程的时间可以直接比；换了机器、重启过都不可比。
- `clock.mono0_ns` 和 `wall0` 由 driver 在同一时刻记下；落盘时所有时间都换算成相对 `mono0` 的微秒。
- 阶段边界用 driver 记的 `t_us`。各进程最多晚 1 秒才看到阶段切换，所以计数的阶段归属和时间窗之间可能差不到 1 秒，文档里写明。

### 7.3 整理成 span（派生数据；finalize 和 `runs merge` 都会做）

1. **打包原始日志**：原始 `ev-*.log` 打成 `events/raw.tar.gz`，永久保留。
2. **配对**：按 (pid, span 号) 把 C 和 R 配成 span，每条是 `[t0_us, dur_us, tid, depth, a, b, rep, n_susp]`。
   - 有 Y/S 的 span 标 async，`dur` 是墙钟时间，其中包含挂起的时间；
   - 进程结束时还没返回的，`dur_us = -1`；
   - depth 取 C 那一刻，这个线程上正在执行（没返回、也没挂起）的 span 数。
3. **第一级折叠**：同一个**父 span** 下、中间这个线程上没有挂起 / 恢复、同一对 a→b、并且自己没有跨文件子调用的连续同步兄弟 span，合成一条，`rep = n`。按父 span 而不按深度：同一线程上交错的两个协程，子调用深度相同但不是兄弟。
4. **写出**：
   - 键表写到 `events/spans/keys.json`：`{keys, threads}`（qualname 在 counts.json.gz 的 names 里）；键丢了的指到 `"?"`；
   - span 按时间排序后分块写进 `p<pid>-NNN.jsonl.gz`，每块最多 10 万行；
   - `index.json` 记 `{pairing, chunks: [{pid, chunk, t0_us, t1_us, n}], procs, truncated, n_lines, n_spans, n_calls}`。

大小估算：原始日志约 20–30 MB 文本，gzip 后约 4–6 MB；spans 约 2–3 MB。在 M3 实测确认。

### 7.4 第二级折叠和出图（M5，`codestrata/seq.py`，每次请求现算，依赖切面）

- **消息**：a、b 经 rel → 单元 → `node_of` 映射到切面上的节点，两端落在不同节点的才画。
- **生命线** = (进程, 切面节点)，只画时间窗里有消息的。
  - 按进程分组，组内按架构高度排，和模块图从上到下的方向一致。
  - argv 相同的进程按 pid 分列，标签用 argv 摘要加 `#1…#n`（按 t0 排序）。
- **循环折叠**：
  - 按 (pid, tid) 把消息转成记号 `(调用方节点, 被调方节点, 被调符号)`；
  - 从左到右贪心地找周期 p ≤ 8、至少重复 3 次的片段，折成一行 `loop ×4312 · 1.8s`；
  - 点开这一行，再请求那一小段时间窗。
- **超出上限不静默截断**：折完仍超过 `max`（默认 300，最大 2000）时，返回 `too_dense` 和一个建议的时间窗。
- **行序和空闲**：行按时间先后排，不按比例画。相邻两行间隔超过 50 ms 时，插一行「⋯ 空闲 340ms」。
- **跨进程只画确定的关系**：子进程在它的 `t0_us` 时刻，从父进程（ppid）画一条派生箭头。IPC 交接不画。
- **async span**：第一版只画箭头，不画激活条；`dur` 和挂起次数只在消息详情里显示。
- **缓存**：overview 按 (run, phase) 缓存；解压过的块放进 LRU（16 块）。

---

## 8 导出

- **M1 起：`graph --hot REF`**，和现在一样只嵌一个 run：`hot`、`hotMeta`、`graphHot`，以及所有边的 `edge_detail`。
- **M7：可以给多个 `--hot`。**
  - 第一个是主 run，全量嵌入；
  - 其余 run 放在 `EMB.hotBy["<id>@<phase>"]`，只嵌它们在导出切面上的节点次数、边次数和精简过的 meta；
  - `--compare` 为前两个 run 嵌入 `cmp` 块，边详情带上 `calls_b`；
  - 大小预算沿用 `export_payload` 的 `remaining`，命令最后打印各部分的大小；
  - `ds.js` 的 embedded 分支加上 `runs()`，`graph(open, w, run)` 在主 run 和 `hotBy` 之间切换。
- **事件一律不嵌入导出文件。**

---

## 9 分阶段实施计划

### 立刻做（零代码，今天）

- 把 `src/vllm-omni/.codestrata/trace-minicpmo-duplex.json` 和 `parts-minicpmo-duplex/` 用 `cp -a` 备份到 `duplex-agents/vllm-omni/runs-backup/`。
- M1 合入之前，不用同名 case 重录。

### M1　录了不丢、录得全（约 2 天；下一次 GPU 录制之前必须完成）　✅ 已完成（M2 一并做了）

> 实现和计划的差别见 4.3 末尾「实现时补上的几条」。测试：`.venv/bin/python tests/test_runs.py`（CPU 假服务，24 个用例，含评审发现的每个问题的回归测试）。GPU 终验待用户同意。

**做什么**

- **第 0 步**：在 vllm-omni 上建软链 `src/vllm-omni/.codestrata/runs → ../../../runs`（`duplex-agents/vllm-omni/runs` 已指向 /mnt/data）。xref 的重写已经提交，直接在主分支上开发。
- **新增 `runs.py`**：`new_run`、`finalize`、`catalog`（含迁移）、`resolve`、`load_counts`、`load`、`file_state`、`tag` / `note` / `rm`、`merge`。
- **`trace.run()`**：
  - 写进 run 目录，不再清空任何旧数据；
  - 改用 `Popen(start_new_session=True)`，按三级信号停止，driver 自己处理 SIGINT；
  - 每 100 ms 轮询 PHASE。
- **`trace.merge()`**：两种 part 命名都认；阶段数据总是保留；输出 names，以及每个进程的 t0、t1、why、py。
- **hook**：按 4.3 改（事件除外），包括去掉 makedirs。
- **detail.json**：file_shas（对实际执行的文件取哈希）、mapped*、procs、pythons + dists、gpu、git，以及自动收集的 files 和 `--attach`。
- **`scan`**：`scan()` / `write_index` 写 `file_sha`。
- **`payload.load_hot`**：
  - 变成薄包装：签名不变，meta 保留原有的键，再加上新字段；
  - `_procs` 改读 `argv_cut`；
  - hot 里带上 `run_id`，让 `notes.prompt_pack` 的 runtime 那一行写明用的是哪个 run。
- **`__main__`**：
  - `_outdir` 写 `.gitignore` 和 `README.txt`；
  - `cmd_trace` 改调 runs；
  - 新增 `runs` 子命令（ls / show / tag / untag / note / rm / merge）；
  - trace 加 `--tag`、`--note`、`--env`、`--attach`、`--stop-grace`；
  - graph 的默认文件名做字符清洗。
- **`web/app.js`**：只改两处文案（见 6.1）。
- **README**：分工表写明运行数据「**不能**重建，在 `runs/` 里」，「`.codestrata/` 里除 runs/ 外都能删」；同步修正 agent 记忆里的同一说法。
- **新增 `tests/trace_cases/fake_service.{sh,py}`**：CPU 上的假服务 case，用来验证停止、残留、exec 和阶段。

**改哪些文件**：`runs.py`（新，约 350 行）、`trace.py`、`scan.py`（两处）、`payload.py`、`notes.py`（一行）、`__main__.py`、`web/app.js`、`README.md`、`tests/trace_cases/*`。

**验收**（全部在 CPU 上）

1. **迁移前准备**：先用**老代码**把 `load_hot(repo, idx, X)` 的 hot 存到 scratchpad，X 取 `minicpmo-duplex` 和它的 `@start`、`@serving`、`@shutdown` 四种。
2. **迁移结果**：`codestrata runs src/vllm-omni ls` 迁移进软链指向的目录，第一行打印 realpath。
   - `.codestrata/` 下不再有 `trace-*.json` 和 `parts-*/`；
   - 老 json 在 `legacy/` 里；
   - 四份 hot 都和第 1 步存下的**完全相等**。
3. **并发迁移**：两个 `runs ls` 同时跑，最后只有一个 run。
4. **重录不覆盖**：在 codestrata 上用同名 case 连录两次 `scan-export`，得到 3 个 run；`--hot scan-export` 解析到最新那个，并打印它的 id。
5. **fake_service 正常退出**：状态为 `ok`，各进程的 `why` 是 atexit 或 _exit，exec 之前的数据还在。
6. **fake_service 超时或 Ctrl+C**：
   - 状态为 `partial`，`stop` 是 timeout 或 interrupt；
   - setsid 出去的 server 收到了 SIGINT 并正常落盘；
   - 退出后，没有任何进程还带着这个 run 的 `CODESTRATA_OUT`；
   - run 目录里没有 `parts/`。
7. **老用法不变**：`serve --hot minicpmo-duplex@serving` 和 `graph --hot …` 的行为不变；帮助里仍然提示「argv 被截断」。
8. **git 干净**：vllm-omni 的 `git status` 不再显示 `.codestrata/`。
9. **过期判断**：在 codestrata 里改一个被跑到的文件，重新 scan，`runs show` 把它列为 changed；vllm-omni 那个 run 里的 demo 文件显示为 outside。

**GPU 终验**：征得用户同意后，录一次真实的 minicpmo。这会是第一个字段齐全的 run。

### M2　残留进程与中断恢复（约 0.5 天）　✅ 随 M1 完成

- **做什么**：
  - 用 `/proc/*/environ` 扫描残留进程，三级停止，记进 `leftovers`；
  - finalize 先停残留进程；
  - `runs merge` 在还有进程带着这个 run 的 `CODESTRATA_OUT` 时拒绝执行；
  - 判断 driver 死了时，同时比对 `driver.start`，防止 pid 复用。
- **验收**（用 fake_service）：
  - server 忽略 SIGINT 时，会被记进 leftovers 并被停掉；
  - 录到一半对 driver 发 `kill -9`：`runs ls` 显示「中断」，执行 `runs merge` 后得到一个 partial 的 run。

### M3　时序事件的录制端（约 1.5 天；排在后面所有 UI 之前）　✅ 已完成（CPU 部分；开销实测待 GPU）

- **做什么**：
  - hook 的事件记录（7.1）；
  - finalize 里的整理（7.3），原始日志保留；
  - `trace --events`；
  - `runs rm --events-only`。
- **验收**：
  - 7.1 的真值测试全部通过；
  - 在 fake_service 上，每个阶段 span 的 `Σrep` 和 counts 里这一阶段跨文件的 `func_edges` 总数一致（允许阶段偏差带来的误差）。
- **开销实测**：要征得用户同意，在 vllm-omni 上录两次，一次带事件、一次不带。比较 serving 阶段的时长、demo 是否通过、每个进程的行数、压缩后的大小，据此决定事件是否默认打开（见 11）。

### M4　不重启切换 run（约 1 天）　✅ 已完成

> 实现：`serve.Handler._hot`（按 run id、阶段、counts 的 mtime 缓存，最近 8 个）、`/api/runs`（「录制后改过几个文件」按 detail 的 mtime 缓存）；前端 `CS.ds.run` 一个值管住所有叠加相关的请求。浏览器验收：换 run 57 ms、换阶段 109 ms 出图；刷新后还是地址里那个 run；serve 开着时新录的 run 回到页面就在按钮上加点；选中的节点换 run 后还选着；换回静态图时自动关掉「只看跑到的」。

- **做什么**：
  - 第 5 节 serve 的改动；
  - `/api/runs`；graph、edge、refs、pack 接受 `run=`；
  - 前端：run 下拉、阶段按钮、hash、file_state 的显示。
- **改哪些文件**：`serve.py`、`payload.py`、`web/{ds,app}.js`、`web/index.html`、`web/app.css`。
- **验收**：
  - 不带 `--hot` 启动 serve，在下拉里切换 run 和阶段，每次都在 1 秒内出图；
  - 刷新页面后，仍停在 hash 里记的那个 run；
  - serve 开着的时候另录一个 run，下拉里就能看到它，不用重启。

### M5　时序图（约 4 天）　✅ 已完成（在 CPU 假数据和合成的 vllm 规模数据上；真 GPU 数据待录）

> 实现：`codestrata/seq.py`（每次请求现算：按切面映射、循环折叠、自动收窄、空闲、派生；块 LRU 16、概览按 index mtime 缓存）、serve 的 `/api/seq*`、`web/seq.js`。和设计的差别：
> - **画得下就不折**：设计是一律找周期折叠；实测三次请求被折成「loop ×3」反而看不出结构。现在先不折，超过行数上限才折（能不能画下的判断仍用折叠后的行数，所以二分依旧单调）。
> - **自动收窄分两步**：serving 阶段几十万次调用不能一次读进来折叠——窗口从 200 ms 起每次 ×4 放宽，直到折叠后放不下或到阶段终点，再在最后一次的消息里二分。合成的 44 万次调用（5 个进程、180 s）上：冷启动 450 ms、热 20 ms；60 s 的窗口太密时 460 ms 内返回 too_dense 和建议窗口。
> - 生命线头的按钮放在左边：右上角浮着搜索栏。
> - 导出的单文件不带时序图（§8 / M7 再说）。
> - M5 评审后补上的：点开 loop 用 `fold=0`（不折叠、长的分屏），否则大循环点开还是那一行；「下一屏」从服务端给的 `next_t0` 接着看（loop 的结束时刻里可能包着挂起时间，按它猜会跳过一段）；同一微秒的几次调用不拆到两屏；import 触发的模块顶层执行不画（和模块图一样），find 先在当前阶段里找；fork+exec 的子进程按 fork 的时刻画派生；统计只数显示的那一段；给定的窗口远远放不下时不整段折叠，按自动收窄算建议窗口（整个 run：1.9 s → 0.14 s）。前端：换 run 时在路上的请求作废、概览按 run 缓存；时序图里 Ctrl+滚轮不去缩放藏着的模块图，选中从别处变了时时序图跟着重画、不乱滚；「在时序图里看」滚到那条消息；给搜索栏让出地方；点消息不强开抽屉；两张图各记各的滚动位置；消息和 loop 行能用键盘；目录生命线上有 ＋。

- **M5a：`seq.py` 和 API（2 天）**
  - 做什么：overview、seq、find 三个接口，第二级折叠，`too_dense`。
  - 验收：serving 阶段的默认窗口折叠后不超过 300 行；接口在 300 ms 内返回；async 的 span 显示正确。
- **M5b：`seq.js` 和两张图的切换（2 天）**
  - 验收：两张图之间的选中和切面同步；「在时序图里看」能定位到对应的时刻。

### M6　qualname 回退（约 0.5 天）

- **做什么**：实现 `runs.remap`（见 3.5 第 3 条），在 `hotMeta` 里报 `unmatched`。
- **验收**：在 codestrata 自己的 case 跑到的文件里，把一个函数下移 5 行后重新 scan：这个函数的 `hot.symbols` 次数和移动前相同；包 `__init__.py` 里的函数也能对上。

### M7　对比与多 run 导出（约 1.5 天）

- **做什么**：`_hot_on_cut` 和 `cmp` 块；`edge_detail(hot_b)`；三种颜色；`graph --hot` 可以给多个、`--compare`、`hotBy`。
- **验收**：
  - MiniCPM@serving 对比 Qwen@serving 时，按颜色区分；
  - 导出两个 run 的 HTML 不超过 16 MB，离线能打开，能切换 run；
  - 在明暗两种主题下核对配色。

**合计约 11 天。**
- M1 做完：「今天 MiniCPM、明天 Qwen，两份都留着」就成立了，而且都能用 `--hot` 选（换 run 要重启 serve）。
- M3 做完：之后录的每个 run 都自带时序数据。
- M4 做完：网页上能来回切 run。
- M5 做完：能看时序图。

---

## 10 不做什么

- **静态分析**：不按 commit 存多份；run 里不存 index 快照。
- **存储**：
  - 不用 sqlite：run 只有几十个，一个 run 一个目录，按时间窗取数据靠分块加 `index.json` 就够；
  - 不做就地的 schema 升级。
- **case 定义**：不做 cases.toml、参数化、矩阵，也不做「声明的阶段」核对。variant 就是另一个 case 名。
- **REF**：不支持 id 前缀、`case/tag`、`case/latest`。
- **run 的去留**：
  - run 不进 git，不做远程同步和备份；
  - 不做 `runs export` / `import` / `mv`（run 目录自包含，`cp -r` 即可）；
  - 不自动删 run，不自动重录；
  - 迁移不删除老数据。
- **网页**：不在网页上录制、删 run、打 tag。serve 对 runs 只读。
- **serve**：不热加载 index，不做文件监视，不做常驻 daemon，不把 `to_package_graph` 的结果缓存到磁盘。
- **分析视图**：
  - 不做覆盖矩阵和「从没跑到的盲区」列表；
  - 引用列表里不按 run 列小标；
  - prompt_pack 里不写「哪些 run 跑到过」，只写用的是哪个 run；
  - 不做 N 路对比；
  - 对比时不重新排版，也不画节点角标和 ▲▼。
- **元数据**：不做 `code_fp`、模型权重的指纹，也不抓整份环境变量。
- **事件**：
  - 不记同一文件内部的调用，不记参数和返回值；
  - 不做 IPC 注入和因果追踪，不画启发式的 IPC 交接；
  - 不把事件嵌进导出文件；
  - 不做行级调用次数。
- **目录结构**：不把缓存挪进 `.codestrata/cache/`（要改 load_index / load_xref / write_index 的路径，收益只是少一个 README.txt）。

---

## 11 风险与未决问题

### 需要你拍板的（括号里是推荐的默认做法，没回复就按它做）

1. **runs 放在哪。**（推荐：放在 `.codestrata/runs/`，允许是软链。vllm-omni 在 M1 第 0 步建软链，指向 `duplex-agents/vllm-omni/runs/`。）注意：duplex-agents 不是 git 仓库，那里只有一份拷贝，codestrata 不负责备份。
2. **事件是否默认打开。**（推荐：M3 实测时，serving 阶段变慢不超过 1.3 倍、demo 照常通过，就默认打开；否则只在 `--events` 时录。）
3. **Qwen 用哪个模型、哪个 demo。**
   - （推荐 Qwen2.5-Omni-7B，要新写一份单卡 5090 的 deploy yaml。）
   - Qwen3-Omni 30B MoE 的 bf16 权重约 60 GB，单卡 32 GB 放不下。
   - 权重下载，以及 `common.sh`、`trace_case.sh` 的变量化，由用户那边做。
4. **serve 没给 `--hot` 时，要不要默认选最近的 run。**（推荐不选，但下拉按钮上显示「运行 (3)」。）
5. **GPU 录制一律先征得同意**，包括 M1 的终验和 M3 的开销实测。其余验收都在 fake_service 上做。

### 已知风险

- **行号映射。**
  - `co_qualname` 要 Python 3.11+，更老的解释器只能按行号映射；
  - 迁移来的 run 没有 names、t0、git，文件一改就只能按行号映射，界面上标 ⚠；
  - property 的 getter 和 setter 共用一个 qualname，会落到同一个符号上。
- **事件配对。** `sys._getframe(1)` 在 sys.monitoring 回调里的语义要靠真值测试确认；不成立时退回用栈配对，这时 asyncio 的 span 不可信，要在 run.json 里标出来。
- **平台限制。**
  - CLOCK_MONOTONIC 只在同一台机器、同一次开机内可比；
  - `/proc/*/environ` 只有 Linux 有，别的系统上残留进程只能靠停进程组来清。
- **事件改变时序。** 录事件会改变被测程序的时序，轮询次数跟着变。一个录了事件、一个没录的两个 run 对比时，界面上要标出来。
- **折叠效果。** 「p ≤ 8、至少重复 3 次」对「偶尔干点活的轮询」折不干净，要在 vllm-omni 上调参数。
- **阶段偏差。** 计数按各进程的落盘线程划分阶段，时间窗按 driver 的时间，两者可能差不到 1 秒。
- **index 落后。** index 落后于工作区时，叠加用的 file_state 仍然是对的，但全文窗口显示的是工作区的文件。serve 启动时要打印落后的文件数。
- **误删 runs/。** 旧的说法「`.codestrata` 可随时重建」可能让以后的会话 `rm -rf`。靠四样东西防：软链、`README.txt`、README、agent 记忆的修正。
