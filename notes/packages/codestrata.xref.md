---
written_by: claude-opus-5-5
target: codestrata.xref
kind: package
code_sha: f36558a7de602b4f
status: draft
refs: __main__.py:87@d89a80ca,xref.py:1348@6f3d4dd5,xref.py:1@33710441,xref.py:295@ad481400,xref.py:615@02ccb7c9,xref.py:830@0ac1d1cb,xref.py:1324@988dc59e,xref.py:1370@299f2f56,xref.py:857@cf9b4e61,xref.py:1327@eecf9796,xref.py:232@59c04e0c,xref.py:334@dac70f9a,xref.py:915@dd64dbbd,xref.py:1236@7666ecb2,xref.py:941@0289caaf,xref.py:461@7cb35e9c,xref.py:390@d2d72128,xref.py:547@0421ea56,xref.py:767@6f648bce,xref.py:732@738ebce6,xref.py:1212@e1368d8e,xref.py:1317@1b6b0495,xref.py:1214@c48b7ec3,xref.py:1381@7362486b,xref.py:1363@e0a460f7,tests/test_runs.py:2120@c253a295,payload.py:961@8e0ec840
---

## 是什么
交叉引用：代码里每个名字指向哪个定义。scan 结束时顺带建一份 `.codestrata/xref.json`（__main__.py:87），给全文窗口的 Ctrl+点击用——点一个名字跳到它的定义；点一个定义，由 `payload.refs` 列出所有引用它的地方。另外顺带给边详情一张小表 `names`：边上引用了、符号表里却没有的名字（模块级变量、`__init__` 再导出的），指向哪个定义。只用 `ast`，静态地、尽力而为地解析。

总原则是**宁可不跳，也不跳错**：跳错一次，用户就不再信这个功能。所以只记能确定的；遮住了、类型拿不准、MRO 上有仓库外的基类，一律不记。

## 为什么这样切
- **和符号表同一时刻的快照**：它复用 scan 的 index（`files` 给模块名，`symbols` 给类 / 函数的限定名和行），不自己再认一遍定义；`s:` 目标的位置直接查符号表。在 scan 里建，行号才和 `symbols.json` 对得上。
- **只产出数据**：serve 端 `payload.load_xref` 按修改时间缓存整份 JSON，`xref_for` 按文件（或行段）切出 token，`refs` 用 `invert` 建的反向表列引用，`_name_def` 查 `names` 给边详情的「to」。本模块不知道前端长什么样，只保证列号能直接当 JS 字符串下标用。
- **过期检测放在产出里**：`fp` 记下构建时每个 `.py` 的大小和 mtime_ns，`payload._stale` 比一下就知道文件在 scan 之后改过——改过的文件行列号已经对不上，链接会落在别的字上，宁可不给 Ctrl+点击。先 stat 再读（xref.py:1348）：读完之后才改的，一定会被认成改过。

## 读法
1. 模块 docstring（xref.py:1）——解析哪些、不解析哪些、xref.json 每个字段的格式。先读它
2. `_Repo`（xref.py:295）——全仓的名字表。先看 `__init__` 里各个表的注释（绑定的几种表示），再看 `lookup_top` / `at_line` / `from_import` / `member`，最后是类的部分：`bases` → `mro` → `class_member` / `unsure`
3. `_Collect`（xref.py:615）——第一遍：模块顶层绑定（`top_block` / `bind`）、`__all__`、类属性和实例属性（`klass` / `func_body` / `inst`）、基类线索（`base_spec`）
4. `_Walk`（xref.py:830）——第二遍：`stmt` 按语句维护作用域，`ex` 解析表达式并记 token；`span` 把字节列换成 UTF-16
5. `build` / `_build`（xref.py:1324）——两遍的驱动、`names` 的追查、attrs 的过滤；`invert` 给 serve 用

## 关键算法
### 产出格式
`targets` 是目标字符串表，其余地方都用下标引用它：`s:模块:限定名`（类 / 函数，位置查符号表）、`v:模块:限定名`（模块变量、类属性、实例属性，位置记在 `_Repo.vars`）、`m:模块`、`x:点分路径`（仓库外，只记路径，前端据此说「定义不在仓库里」）。`where` 与之对齐，`files` 是每个文件的 `[行, 起, 止, 目标下标, 种类]`，种类 0 引用、1 调用、2 import、3 定义本身。`names` 是 {"模块:名字": 目标下标}，只收 s: / v: 目标（xref.py:1370），见下面「names」一节。内部还有三种只在解析时用、不写出去的绑定：`n:`（命名空间包）、`self:类`（方法的第一个参数）、`super:类`（`super()` 的结果）。

几个格式细节都是为了前端：
- 起止是 **UTF-16 码元下标**（JS 字符串下标），不是 ast 给的 UTF-8 字节列，也不是码点；`span` 负责换算，并核对那个位置上的文字确实是这个名字，不是就不记（免得下划线画歪，xref.py:857）。文件开头的 BOM 去掉，因为 Pygments 高亮时也去掉它。
- import 的点分路径**每段一个 token**，各自指向到这一段为止的前缀（`dotted`）：前端只能包住落在同一个高亮文本节点里的 token。
- def / class 的名字位置 ast 不给，`find_kw` 在关键字之后找；属性名用节点的结束位置倒着算。
- 同名的 def 出现几次（property 的 getter / setter、overload）：符号表留最后一个，`_Collect.first` 另记第一个，`where` 优先用它——跳到 getter。

### 两遍、逐个文件、关掉 GC
第一遍（`_Collect`）收模块顶层绑定、类属性、实例属性、基类线索；第二遍（`_Walk`）带作用域走一遍记 token。两遍都是**逐个文件 parse、用完就丢**：整仓 AST 一起攥着太贵，vllm-omni 的 1600 个文件要吃掉近 1 GB。跨文件的信息只有第一遍收的那些小表。

内存上还有两处刻意的写法：
- `build` 关掉分代 GC（xref.py:1327）：建 AST 时一路触发的 GC 白白扫描几百万个节点，这里又不产生循环引用。代价是**不能有环**——所以 `_local_walk` 写成模块级函数而不是递归闭包：闭包引用自己成了环，关着 GC 时会把整个文件的状态攥到最后（xref.py:232 的 docstring）。
- 行号、目标下标这些要留到最后的 int，一律换成 `_Repo.ints` 里事先建好的对象（xref.py:334）：留住 AST 里的 int 会把它所在的整块内存、连同周围早该释放的 AST 节点的空位一直钉住。

`block` 按语句接住 `RecursionError`（xref.py:915），还原作用域后接着走下一条——生成的代码里有嵌套上千层的表达式；左嵌套的长 `a + b + c + …` 则改成循环（xref.py:1236），不递归下去。

### 模块顶层的名字
同一个名字绑定几次（`_Collect.bind`）：默认第一次算——`if` / `try` 里的备选（`try: import a except: import b`）通常第一个才是真正想用的；**顶层无条件的 def / class** 盖掉前面的 import / 赋值，被盖掉的旧绑定连同行号记进 `hist`。第二遍的 `_Walk.lookup` 据此区分执行时机：模块顶层的代码（包括 `class Base(Base)` 自己的基类、装饰器、类体）按当前这条顶层语句的行用 `at_line` 取当时的绑定；函数体、lambda、注解（按 PEP 563 / 649 推迟求值，xref.py:941）在模块跑完之后才执行，取最终的。

`if TYPE_CHECKING:` 块和别的 if 一样收绑定：scan 把这种 import 算成「仅类型」、不是依赖，但标注里的名字照样能 Ctrl+点击——xref 自己解析 import，不看 scan 的边。

from-import 先存成 `("from", 模块, 名字)`，用到时才由 `from_import` 追：
- `from pkg import name` 先看 pkg 自己把 name 绑成了什么——`from .x import x` 会把子模块 x 换成函数 x；绑的就是 `from . import name` 本身时才是子模块（xref.py:461）；再看星号导入，最后才是子模块 `pkg.name`。这样再导出能一路追到真正定义它的文件，否则所有引用都会停在 `__init__` 上。
- `from x import *`：x 在仓库里时按它字面量的 `__all__`（`=`、`+=`、`.extend`、`.append` 全是字面量才算，`dunder_all`），没有就按不以 _ 开头的顶层名字，星号链递归展开；仓库外的模块不知道带出什么，当它不带。
- 追的过程会成环（两个包互相再导出）。`_memo_call` 带缓存，但成环的那一圈结果不缓存（xref.py:390），免得把「环上暂时找不到」记成定论。
- 没有 `__init__.py` 的目录是命名空间包（`n:`）：能穿过去找子模块，自己没有文件可跳，不出 token。

### 类：C3 MRO 与成员
`self.x` / `cls.x` / `Class.x` 都走 `class_member`：沿 MRO 找方法、嵌套类（符号表）和类属性、实例属性（`vars`）。

- 基类的线索在第一遍记下（`base_spec`）：外层函数局部 / 类体里的名字直接取绑定；模块顶层的名字带上 class 语句的行——之后才出现的同名 def / class 不影响它；函数里的类等函数跑起来才建，取最终绑定。`Generic[T]` 取 `Generic`；调用之类不是点分名字的，记不知道。
- `bases` 把基类分三种：仓库里的类；`_TRANSPARENT`（`typing.Generic`、`Protocol`、`abc.ABC`）和 `object`，记 `~`，它们不带普通属性，MRO 上碰到接着往后找，只有 dunder 不行；其余记 `?`，同一个仓库外的类用同一个记号，C3 合并时才认得出是同一个。
- `_mro` 按 C3 线性化；不一致时返回 None（xref.py:547）——Python 自己也建不出这个类，不猜。
- 找成员时 MRO 上**先碰到 `?` 就放弃**：那个仓库外的基类自己可能就有 x，跳到后面仓库里的同名成员就是跳错。
- 实例属性：每个类里第一次 `self.x = …` 的地方算定义（`inst`，第一个参数由 `_first_param` 认，staticmethod 没有）；方法里的闭包也算，除非里层函数自己有同名参数（xref.py:767）。类属性先收齐再收实例属性（xref.py:732），类体里声明过的（dataclass 字段之类）优先。第二遍在那个位置记成定义（种类 3，xref.py:1212）。
- `super()`：只认方法里无参的 `super()`，和第一个参数是本类、第二个是 self 的 `super(本类, self)`（`super_call`），从 MRO 上本类的下一个开始找；`super` 被遮住、在 lambda 里（xref.py:1317）都不解析。

### 作用域
- 函数：`_fn_locals` 进函数前一次收齐所有局部名字（参数，赋值 / for / with / except / match / del 的目标，里面的 def / class 和 import）——Python 的规则是函数里任何地方绑定过就是整个函数的局部。局部变量记 None：遮住外面的同名名字，但不知道指向什么，于是不解析。同一个名字绑了几次取第一次（`x = None` 之后又 import x，宁可不跳）。`global` 直接去模块顶层找，`nonlocal` 往外层找。文件里有 `:=` 时才额外走表达式找海象赋值。
- 类体（`_ClsScope`）：类体里的语句看得见前面已经绑定的名字（`@x.setter` 的 x 是上面的 getter），方法体看不见——进函数、lambda、推导式、另一个类体时由 `outer_chain` 把它滤掉，这是 Python 的规则。
- 推导式的第一个可迭代对象在外面求值，循环变量只在里面遮；lambda 的参数、PEP 695 的类型参数同理。
- match 的捕获名字（`_Walk.pattern`）、except 的 as，以及模块顶层 / 类体里 for / with 的目标，在对应的语句体里临时遮住同名的全局（`shadowed`）。

### attrs：解析不了的同名 `.attr`
`engine.generate()` 这种通过局部变量、调用结果调用的，静态分析不知道接收者的类型，不能给跳转；但引用面板想列出「同名调用，接收者类型没核实」。`ex` 解析不出属性时（xref.py:1214），满足三条才记进 `attrs`：
- 属性名是仓库里某个类的成员名（`finish_first_pass` 收的 `member_names`）；
- 接收者不是字面量 / 推导式（`"".join`、`[...].append` 的类型一眼就知道）；
- `unsure` 为真：接收者不知道是什么（局部变量、调用结果、模块级变量），或是 MRO 上有 `?` 的类。模块、仓库外的东西、函数、MRO 全在仓库里却哪儿都没定义 attr 的类都不算——那是确定「不是它」。

最后按名字过滤（xref.py:1381）：数 `targets` 里限定名带点、最后一段是这个名字的类 / 函数和变量目标（基本就是类成员），超过 `ATTRS_MAX_SAME`（3）个的名字整组丢掉。`get`、`shape`、`to`、`append` 这种名字按名字列出来一大半都不是它，还会占掉 xref.json 的三分之一。

### names：边详情的「to」和 Ctrl+点击落在同一处
scan 的边明细 `edge_uses` 按「模块:名字」记被引用的东西，payload 拿它查符号表给「to」（定义在哪、签名）。可符号表只有类和函数：`from .models import LIMIT` 引用的模块级变量、`from rx import DEFAULT_LIMIT`（包的 `__init__` 再导出、还改了名）这种键查不到，面板只能说没找到定义。追到真正的定义要的正是 `from_import` 那一套——包自己的绑定优先、星号导入、同名重绑取哪次——而那些表只在 scan 的这一趟里有（第一遍收的，建完就丢）。所以在第二遍之后（xref.py:1363 起），把 `edge_uses` 里不在符号表的键逐个按 `from 模块 import 名字` 追一次：追到的是类 / 函数 / 变量、而且知道定义在哪（`where` 不为空）才记下目标下标（xref.py:1370）。子模块（`m:`）和仓库外（`x:`）不记：面板要的是一个定义的位置和签名。`payload._name_def` 查这张表，变量的签名就是赋值那一行。

同一套解析的好处是两处答案一致：边详情里 DEFAULT_LIMIT 的 to 和 Ctrl+点击它跳到的都是 rx/models.py 的 `LIMIT: int = 30`（test_edge_defs_vars_and_reexports，tests/test_runs.py:2120）。表很小——只有边上引用、又不在符号表里的名字。追的过程可能给 `targets` 添上没有 token 指向的新目标，`where` 在那之后才整表算，仍然对齐。老的 xref.json 没有 `names`，payload 照旧说没找到定义。

### invert
`invert`：目标下标 → 所有引用它的 `[文件, 行, 列, 种类]`，不含定义本身。serve 第一次有人要引用列表时才建，每份 xref 只建一次（payload.py:961）。

## 局限
- `names` 只收 scan 边明细里出现的键：边详情以外（比如引用面板）用不上它；追不到定义的（仓库外、命名空间包、`from_import` 回 None）照旧没有「to」。
- 没有类型推断：局部变量的属性（`x = Foo(); x.bar`）、调用结果的属性、`getattr` 之类一律不解析，只能进 attrs 的「没核实」那一组。
- 仓库外的类：torch.nn.Linear 这种只记点分路径，不知道它有哪些成员；仓库里的类一旦继承了仓库外的类，它的 `self.xxx` 在 MRO 走到那个基类之前找不到的，全部放弃。
- 模块顶层的非 def / class 重复绑定一律取第一次：`from m import f` 之后 `f = wrap(f)`，后面的 `f` 仍指向 m 里那个 f。
- 模块顶层 for / with 的目标只在语句体里遮住同名的全局，语句结束后的同名引用又回到全局那个绑定。

## 不确定
- 第一遍没见过的类（index 里有、但文件在两者之间改过）`bases` 当成不知道的基类；scan 和 build 在同一个进程里前后脚跑，实际很少碰到。
