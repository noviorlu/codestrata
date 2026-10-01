/* 浏览器端源码高亮：highlight.py（Pygments）的 JS 版，边详情里的代码片段（调用那一行、签名）用它。
 * 照抄 Pygments 的 Python / C / C++ / CUDA 词法状态表，每个状态拼成一条粘连大正则。
 * 保真第一：token 文本原样取自源码，按 \n 切行；Pygments 去掉的 BOM、\r 最后原样补回。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  // 正则占位符 `X，编译时展开
  var CI = '(?!\\p{Nd})(?:[\\p{L}\\p{N}_$]|\\\\u[0-9a-fA-F]{4}|\\\\U[0-9a-fA-F]{8}';
  var CS1 = /\/\/(?:[^\n]|(?<=\\)\n)*\n/.source;
  var CM = /\/(?:\\\n)?[*](?:[^*]|[*](?!(?:\\\n)?\/))*[*](?:\\\n)?\//.source;
  var PH = {
    L: '(?<![^\\n])',                  // Pygments 的 ^（行首）
    B: '(?![\\p{L}\\p{N}_])',          // 词尾 \b，按 Unicode
    w: '[\\p{L}\\p{N}_]',
    U: '[_\\p{XID_Start}]\\p{XID_Continue}*',
    I: CI + ')+',
    J: CI + '|::)+',
    S: /\s*(?:\/[*][^\n]*?[*]\/\s*)?/.source,
    P: '\\s*(?:(?:' + CS1 + '|' + CM + ')\\s*)*',
    H: "[0-9a-fA-F](?:'?[0-9a-fA-F])*",
    D: "\\d(?:'?\\d)*"
  };

  // Pygments 的 words()：长词在前
  function w(s, pre) {
    return (pre || '') + '(?:' + s.split(' ').sort(function (a, b) { return b.length - a.length; })
      .join('|').replace(/~/g, ' ') + ')`B';
  }

  // 规则 [正则, 类名 | bygroups 数组（元素为类名或状态栈 = using(this)）, 新状态]
  // 'N' = 普通 Name（C 系类型重标只认它），'n' = 其他无色 Name
  function py() {
    var d = {}, S = [];
    var EB = /\\(?:[\\abfnrtv"']|\n|x[a-fA-F0-9]{2}|[0-7]{1,3})/.source;
    var ES = /\\(?:N\{[^\n]*?\}|u[a-fA-F0-9]{4}|U[a-fA-F0-9]{8})/.source + '|' + EB;
    var ER = /\{\{|\}\}/.source;
    var IN = /%(?:\(`w+\))?[-#0 +]*(?:[0-9]+|[*])?(?:\.(?:[0-9]+|[*]))?[hlL]?[E-GXc-giorsaux%]|\{(?:`w+(?:\.`w+|\[[^\]]+\])*)?(?:![sra])?(?::(?:[^\n]?[<>=^])?[-+ ]?#?0?(?:\d+)?,?(?:\.\d+)?[E-GXb-gnosx%]?)?\}|[^\\'"%{\n]+|['"\\]|%|\{\{?/.source;
    var FT = /[^\\'"{}\n]+|['"\\]/.source;
    // 字符串：前缀（rf、f、r/rb、u/无、b）× 引号，各一个状态
    [['[rR][fFtT]|[fFtT][rR]', ER, 1], ['[fFtT]', ER + '|' + ES, 1], ['[rR][bB]|[bB][rR]|[rR]', '', 0],
     ['[uU]?', ES, 0], ['[bB]', EB, 0]].forEach(function (k, a) {
      ['"""', "'''", '"', "'"].forEach(function (q, b) {
        var id = 's' + a + b, one = q.length === 1, e = k[1] ? [k[1]] : [];
        if (one) e.push(/\\\\|\\\n|\\/.source + q);
        S.push(['(?:' + k[0] + ')' + q, 'str', id]);
        d[id] = [[q, 'str', '#pop']].concat(k[2]
          ? [[e.concat('\\}').join('|'), 'str'], ['\\{', 'str', 'efs'], [FT + (one ? '' : '|\\n'), 'str']]
          : [[e.concat(IN, one ? [] : '\\n').join('|'), 'str']]);
      });
    });
    var MAG = /__(?:[ir]?(?:add|and|floordiv|lshift|matmul|mod|mul|or|pow|rshift|sub|truediv|xor)|r?divmod|abs|aenter|aexit|aiter|anext|await|bool|bytes|call|complex|contains|del|delattr|delete|delitem|dir|enter|eq|exit|float|format|ge|get|getattr|getattribute|getitem|gt|hash|index|init|instancecheck|int|invert|iter|le|len|length_hint|lt|missing|ne|neg|new|next|pos|prepare|repr|reversed|round|set|setattr|setitem|str|subclasscheck)__`B/;
    var KW = 'assert async await break continue del elif else except finally for global if lambda pass raise nonlocal return try while yield as with';
    var SP = '((?:\\s|\\\\\\s)+)';
    d.root = [
      [/\n/, ''],
      [/`L(\s*)([rRuUbB]{0,2})("""[\s\S]*?"""|'''[\s\S]*?''')/, ['', 'str', 'doc']],
      [/^#![^\n]+/, 'com'],
      [/#[^\n]*/, 'com'],
      [/\\\n?/, ''],
      [w(KW + ' yield~from'), 'kw'],
      [w('True False None'), 'const'],
      // 软关键字 match / case：行首、后面不像普通表达式
      ['(`L[ \\t]*)(match|case)`B(?![ \\t]*(?:[:,;=^&|@~)\\]}]|(?:' + (KW + ' and class def from import in is not or').replace(/ /g, '|') + ')`B))', ['', 'kw'], 'skw'],
      ['(def)' + SP, ['kw', ''], 'fname'],
      ['(class)' + SP, ['kw', ''], 'cname'],
      ['(?:`L(lazy)' + SP + ')?(from)' + SP, ['kw', '', 'kw', ''], 'fimp'],
      ['(?:`L(lazy)' + SP + ')?(import)' + SP, ['kw', '', 'kw', ''], 'imp'],
      'expr'];
    d.expr = S.concat([
      [/[^\S\n]+/, ''],
      [/(?:\d(?:_?\d)*\.(?:\d(?:_?\d)*)?|(?:\d(?:_?\d)*)?\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?|\d(?:_?\d)*[eE][+-]?\d(?:_?\d)*j?|0[oO](?:_?[0-7])+|0[bB](?:_?[01])+|0[xX](?:_?[a-fA-F0-9])+|\d(?:_?\d)*/, 'num'],
      [/!=|==|<<|>>|:=|[-~+\/*%=<>&^|.]|[\]{}:(),;[]/, ''],
      [w('in is and or not async~for await else for if lambda yield yield~from'), 'kw'],
      [w('True False None'), 'const'],
      [w('__import__ abs aiter all any bin bool bytearray breakpoint bytes callable chr classmethod compile complex delattr dict dir divmod enumerate eval filter float format frozendict frozenset getattr globals hasattr hash hex id input int isinstance issubclass iter len list locals map max memoryview min next object oct open ord pow print property range repr reversed round sentinel set setattr slice sorted staticmethod str sum super tuple type vars zip', '(?<!\\.)'), 'bi'],
      [/(?<!\.)(?:self|Ellipsis|NotImplemented|cls)`B/, 'self'],
      [MAG, 'fn'],
      [/@`U/, 'dec'],
      [/@/, ''],
      [/`U/, 'N']]);
    d.fname = [[MAG, 'fn'], [/`U/, 'fn', '#pop'], ['', '', '#pop']];
    d.cname = [[/`U/, 'cls', '#pop']];
    d.imp = [[/(\s+)(as)(\s+)/, ['', 'kw', '']], [/\.|`U/, 'ns'], [/\s*,\s*/, ''], ['', '', '#pop']];
    d.fimp = [[/(\s+)(import)`B/, ['', 'kw'], '#pop'], [/\./, 'ns'], [/None`B/, 'const', '#pop'], [/`U/, 'ns'], ['', '', '#pop']];
    d.efs = [[/[{([]/, '', 'efsi'], [/(?:=\s*)?(?:![sraf])?[}:]/, 'str', '#pop'], [/\s+/, ''], 'expr'];   // f-string 的 {…}
    d.efsi = [[/[{([]/, '', 'efsi'], [/[\])}]/, '', '#pop'], [/\s+/, ''], 'expr'];
    d.skw = [[/(\s+)([^\n_]*)(_`B)/, ['', ['root'], 'kw']], ['', '', '#pop']];
    return d;
  }

  function cf(cpp) {
    var R = ['root'], W = ['root', 'ws'], FA = [R, W, 'fn', W, R, W, R, ''], MA = [R, 'pre', R, 'pre', R, 'com'];
    var FN = /(`J[&*\s]+)(`P)(`J)(`P)(\([^;"')]*?\))(`P)/.source;
    var ANN = [/(\[\[)(=)(`I)/, ['', '', 'dec'], 'annot'], ATT = [/\[\[(?=[^\[\]]*\]\])/, '', 'attr'];
    var d = {
      ws: [
        [/`L#if\s+0/, 'pre', 'if0'],
        [/`L#/, 'pre', 'macro'],
        [/`L(`S)(#if\s+0)/, [R, 'pre'], 'if0'],
        [/`L(`S)(#)/, [R, 'pre'], 'macro'],
        [/(`L[ \t]*)(?!(?:public|private|protected|default)`B)(`I)(\s*)(:)(?!:)/, ['', 'n', '', '']],
        [/\n|[^\S\n]+|\\\n/, ''],
        [CS1 + '|' + CM, 'com'],
        [/\/(?:\\\n)?[*][\s\S]*/, 'com']],
      statements: (cpp ? [[/(?:[LuU]|u8)?R"(?<d>[^\\()\s]{0,16})\([\s\S]*?\)\k<d>"/, 'str'], ANN] : []).concat([ATT,
        'keywords', 'types',
        [/(?:[LuU]|u8)?"/, 'str', 'string'],
        [/(?:[LuU]|u8)?'(?:\\[^\n]|\\[0-7]{1,3}|\\x[a-fA-F0-9]{1,2}|[^\\'\n])'/, 'str'],
        ['0[xX](?:`H\\.`H|\\.`H|`H)[pP][+-]?`H[lL]?|-?(?:`D\\.`D|\\.`D|`D)[eE][+-]?`D[fFlL]?|-?(?:`D\\.(?:`D)?|\\.`D)[fFlL]?|`D[fFlL]|' +
         '-?(?:0[xX]`H|0[bB][01](?:\'?[01])*|0(?:\'?[0-7])+|`D)(?:[uU]?[zZ]|[zZ][uU]|[uU][lL]{0,2}|[lL]{1,2}[uU]?)?', 'num'],
        [/[~!%^&*+=|?:<>\/-]|[()\[\],.]/, ''],
        [/(?:true|false|NULL|nullptr)`B/, 'bi'],
        [/`I/, 'N']]),
      keywords: (cpp ? [
        [/(class|concept|typename)(\s+)/, ['kw', ''], 'cname'],
        [/namespace`B/, 'kw', 'namespace'],
        [/(enum)(\s+)/, ['kw', ''], 'ename']] : []).concat([
        [/(struct|union)(\s+)/, ['kw', ''], 'cname'],
        [/case`B/, 'kw', 'casev'],
        [w('asm auto break const constexpr continue countof default defer do else enum extern for goto if register restricted return sizeof struct static switch typedef typeof typeof_unqual volatile while union thread_local alignas alignof static_assert _Pragma fortran inline _inline __inline naked restrict thread ' + (cpp
          ? 'catch const_cast delete dynamic_cast explicit export friend mutable new operator private protected public reinterpret_cast class __restrict static_cast template this throw throws try typeid using virtual concept decltype noexcept override final constinit consteval co_await co_return co_yield requires import module typename and and_eq bitand bitor compl not not_eq or or_eq xor xor_eq contract_assert pre post'
          : '_Alignas _Alignof _Noreturn _Countof _Generic _Thread_local _Static_assert _Imaginary noreturn imaginary complex')) +
         '|__(?:m(?:128[id]?|64)|asm|based|except|stdcall|cdecl|fastcall|declspec|finally|try|leave|w64|unaligned|raise|noop|identifier|forceinline|assume|null)`B', 'kw']]),
      types: [
        [/__(?:int8|int16|int32|int64|wchar_t)`B/, 'kw'],
        [w('bool int long float short double char unsigned signed void _BitInt __int128 ' +
           (cpp ? 'char16_t char32_t char8_t' : '_Bool _Complex _Atomic _Decimal32 _Decimal64 _Decimal128')), 'type']],
      // 函数定义 / 声明：各组再递归词法（using(this)）
      root: ['ws', 'keywords',
        [FN + /([^;{\/"']*)(\{)/.source, FA, 'function'],
        [FN + /([^;\/"']*)(;)/.source, FA],
        'types',
        ['', '', 'statement']],
      statement: ['ws', 'statements', [/\}/, ''], [/[{;]/, '', '#pop']],
      function: ['ws', 'statements', [/;/, ''], [/\{/, '', '#push'], [/\}/, '', '#pop']],
      string: [[/"/, 'str', '#pop'], [/\\(?:[\\abfnrtv"']|x[a-fA-F0-9]{2,4}|u[a-fA-F0-9]{4}|U[a-fA-F0-9]{8}|[0-7]{1,3})|[^\\"\n]+|\\\n|\\/, 'str']],
      macro: [
        [/(`S)(include)(`S)("[^"]+"|<[^>]+>)([^\S\n]*)([^\/\n]*\/[*][\s\S]*?[*]\/)/, MA],
        [/(`S)(include)(`S)("[^"]+"|<[^>]+>)([^\S\n]*)([^\n]*)/, MA],
        [/[^\/\n]+/, 'pre'],
        [/\/[*][\s\S]*?[*]\//, 'com'],
        [/\/\/[^\n]*?\n/, 'com', '#pop'],
        [/\/|(?<=\\)\n/, 'pre'],
        [/\n/, 'pre', '#pop']],
      if0: [
        [/`L\s*#if[^\n]*?(?<!\\)\n/, 'pre', '#push'],
        [/`L\s*#el(?:se|if)[^\n]*\n/, 'pre', '#pop'],
        [/`L\s*#endif[^\n]*?(?<!\\)\n/, 'pre', '#pop'],
        [/[^\n]*?\n/, 'com']],
      cname: ['ws'].concat(cpp ? [ANN] : [], [ATT, [/`I/, 'cls', '#pop'], [/\s*(?=>)/, '', '#pop'], ['', '', '#pop']]),
      casev: [[/(?<!:):(?!:)/, '', '#pop'], [/`I/, 'n'], 'ws', 'statements'],
      attr: (cpp ? [[/using`B/, 'kw'], [/:/, '']] : []).concat([[/\]\]/, '', '#pop'], [/`I/, 'n'], [/\(/, '', 'attrargs'], [/::|,/, ''], 'ws']),
      attrargs: [[/\)/, '', '#pop'], [/\(/, '', '#push'], 'statements']
    };
    if (cpp) {
      d.namespace = [[/;/, '', ['#pop', 'root']], [/\{/, '', ['#pop', 'nsbody']], [/inline`B/, 'kw'], [/`I/, 'ns'], 'statement'];
      d.nsbody = [[/\}/, '', '#pop'], 'root'];
      d.ename = ['ws', [/(?:class|struct)`B/, 'kw'], ANN, ATT, [/`I/, 'cls', '#pop'], [/\s*(?=>)/, '', '#pop'], ['', '', '#pop']];
      d.annot = [[/\]\]/, '', '#pop'], [/\(/, '', 'annotargs'], [/::|,/, ''], [/`I/, 'dec'], 'ws'];
      d.annotargs = [[/\)/, '', '#pop'], [/\(/, '', '#push'], 'statements'];
    }
    return d;
  }

  // 每条规则包一组、拼成一条大正则；记下外包组号
  function build(defs) {
    var L = {};
    function flat(k) {
      return defs[k].reduce(function (o, r) { return o.concat(typeof r === 'string' ? flat(r) : [r]); }, []);
    }
    Object.keys(defs).forEach(function (k) {
      var src = [], R = [], g = 1;
      flat(k).forEach(function (r) {
        var s = (typeof r[0] === 'string' ? r[0] : r[0].source).replace(/`(\w)/g, function (_, x) { return PH[x]; });
        R.push({ g: g, a: r[1], s: r[2] ? [].concat(r[2]) : null });
        src.push('(' + s + ')');
        g += new RegExp('|' + s, 'u').exec('').length;
      });
      L[k] = { re: new RegExp(src.join('|'), 'uy'), r: R };
    });
    return L;
  }

  var CACHE = {};
  function lexer(lang) {
    var k = lang === 'triton' ? 'python' : lang === 'cuda' ? 'cpp' : lang;
    return CACHE[k] || (CACHE[k] = build(k === 'python' ? py() : cf(k === 'cpp')));
  }

  // 照搬 RegexLexer.get_tokens_unprocessed；结果推进 C（类名）/ V（文本）
  function lex(L, text, stack, C, V) {
    var st = stack.slice(), S = L[st[st.length - 1]], pos = 0, n = text.length, z = 0, m, r, a, i, j, t, k0, p;
    while (pos < n) {
      S.re.lastIndex = pos;
      m = S.re.exec(text);
      if (m && (m[0] || ++z < 64)) {            // 连续空匹配太多：当没匹配，防死循环
        if (m[0]) z = 0;
        for (i = 0; m[S.r[i].g] === undefined; i++);
        r = S.r[i]; a = r.a;
        if (typeof a === 'string') {
          if (m[0]) { C.push(a); V.push(m[0]); }
        } else {
          k0 = C.length; p = 0;
          for (j = 0; j < a.length; j++) {
            t = m[r.g + 1 + j];
            if (!t) continue;
            if (typeof a[j] === 'string') { C.push(a[j]); V.push(t); } else lex(L, t, a[j], C, V);
            p += t.length;
          }
          if (p !== m[0].length) { C.length = V.length = k0; C.push(''); V.push(m[0]); }  // 组没盖满：整段无色
        }
        pos += m[0].length;
        if (r.s) {
          for (j = 0; j < r.s.length; j++) {
            t = r.s[j];
            if (t === '#pop') { if (st.length > 1) st.pop(); } else st.push(t === '#push' ? st[st.length - 1] : t);
          }
          S = L[st[st.length - 1]];
        }
      } else if (text.charCodeAt(pos) === 10) {    // 行尾无规则：回 root
        st = ['root']; S = L.root; z = 0;
        C.push(''); V.push('\n'); pos++;
      } else {                                     // 出错字符：原样吐一个码点
        z = 0; j = text.codePointAt(pos) > 0xffff ? 2 : 1;
        C.push(''); V.push(text.substr(pos, j)); pos += j;
      }
    }
  }

  var NAMES = { N: 1, n: 1, fn: 1, cls: 1, dec: 1, ns: 1, bi: 1, self: 1 };
  var CTYPE = /^(?:(?:s?size|off|wchar|ptrdiff|sig_atomic|fpos|clock|time|l?div|mbstate|wctrans|wint|wctype|clockid|cpu_set|cpumask|dev|gid|id|ino|key|mode|nfds|pid|rlim|sig(?:handler|info|set|val)?|socklen|timer|uid)_t|va_list|jmp_buf|FILE|DIR|byte|u?int(?:_least|_fast)?(?:8|16|32|64)_t|u?int(?:ptr|max)_t|atomic_(?:u?(?:char|short|int|long|llong)|bool|schar|char(?:16|32)_t|wchar_t|u?int_(?:least|fast)(?:8|16|32|64)_t|u?int(?:ptr|max)_t|size_t|ptrdiff_t))$/;
  var CUVEC = /^(?:u?(?:char|short|int|long)[1-4]|u?longlong[12]|float[1-4]|double[12])$/;
  var CUFN = /^__(?:threadfence_(?:block|system)|syncthreads_(?:count|and|or))$/;
  var CUDA = /^(?:__(?:global|device|host|shared|constant|managed|restrict|forceinline|noinline|launch_bounds)__|__(?:syncthreads|syncwarp|threadfence|ldg|half|nv_bfloat16|float2half|half2float)|__shfl_(?:down_|up_|xor_)?sync|(?:thread|block)Idx|(?:block|grid)Dim|warpSize|dim3|cuda(?:Stream|Error)_t|atomic(?:Add|Max|Min|CAS|Exch))$/;

  // 词法器自带的重标（C 系类型、CUDA）+ highlight._tokens 的 Triton / CUDA 重标
  function retag(lang, C, V) {
    for (var i = 0, n = C.length, c, v; i < n; i++) {
      c = C[i]; v = V[i];
      if (lang === 'triton') {
        if (v === 'tl' && NAMES[c] && i + 2 < n && V[i + 1] === '.' && NAMES[C[i + 2]]) { C[i] = C[i + 1] = C[i + 2] = 'tri'; i += 2; }
        else if (c === 'dec' && v.lastIndexOf('@triton', 0) === 0) C[i] = 'tridec';
      } else if (lang !== 'python') {
        if (c === 'N') {
          if (CTYPE.test(v)) C[i] = 'type';
          else if (lang === 'cuda') { if (CUVEC.test(v)) C[i] = 'type'; else if (CUFN.test(v)) C[i] = 'fn'; }
        }
        if (lang === 'cuda' && CUDA.test(v)) C[i] = 'cuda';
      }
    }
  }

  var EM = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };
  function esc(s) { return s.replace(/[&<>"']/g, function (c) { return EM[c]; }); }   // = html.escape

  var LABEL = { python: 'Python', triton: 'Python · Triton', cpp: 'C++', c: 'C', cuda: 'C++ · CUDA', text: '文本' };
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  var EXT = {};
  'py:python pyi:python c:c cc:cpp cpp:cpp cxx:cpp c++:cpp h:cpp hh:cpp hpp:cpp hxx:cpp inl:cpp cu:cuda cuh:cuda'
    .split(' ').forEach(function (x) { x = x.split(':'); EXT[x[0]] = x[1]; });
  var TRITON = /(?<![^\n])\s*(?:import\s+triton(?![\p{L}\p{N}_])|from\s+triton(?![\p{L}\p{N}_])|@triton\.)/u;

  // 同 highlight.detect：按 Path.suffix 的规则取后缀
  function detect(path, text) {
    var nm = String(path || '').replace(/\/+$/, ''), i, x;
    nm = nm.slice(nm.lastIndexOf('/') + 1);
    i = nm.lastIndexOf('.');
    x = i > 0 && i < nm.length - 1 ? nm.slice(i + 1).toLowerCase() : '';
    if (!has(EXT, x)) return 'text';
    return EXT[x] === 'python' && TRITON.test(text || '') ? 'triton' : EXT[x];
  }

  // 同 highlight.to_lines：第 N 个元素就是第 N 行；跨行 token 在换行处闭合、下一行重开
  function lines(text, lang) {
    text = text == null ? '' : String(text);
    if (lang === 'text' || !has(LABEL, lang)) return text.split('\n').map(esc);
    var bom = text.charCodeAt(0) === 0xfeff, body = bom ? text.slice(1) : text,
        crlf = body.indexOf('\r\n') >= 0, C = [], V = [], k, o, q, v, s, e, c, part;
    lex(lexer(lang), crlf ? body.replace(/\r\n/g, '\n') : body, ['root'], C, V);
    retag(lang, C, V);
    if (crlf) {                                   // \r 补回它后面那个 \n 所在的 token
      for (k = 0, o = 0; k < V.length; k++) {
        v = V[k];
        if (v.indexOf('\n') < 0) { o += v.length; continue; }
        for (s = '', q = 0; q < v.length; q++, o++) {
          if (v[q] === '\n' && body.charCodeAt(o) === 13) { s += '\r'; o++; }
          s += v[q];
        }
        V[k] = s;
      }
    }
    if (bom) { C.unshift(''); V.unshift('\ufeff'); }
    var out = [], line = '', cc = '', buf = '';
    function flush() {
      if (buf) { line += cc ? '<span class="t-' + cc + '">' + esc(buf) + '</span>' : esc(buf); buf = ''; }
    }
    for (k = 0; k < V.length; k++) {
      c = C[k]; v = V[k]; s = 0;
      if (c === 'N' || c === 'n') c = '';
      for (;;) {
        e = v.indexOf('\n', s);
        part = e < 0 ? (s ? v.slice(s) : v) : v.slice(s, e);
        if (part) { if (c !== cc) { flush(); cc = c; } buf += part; }
        if (e < 0) break;
        flush(); out.push(line); line = ''; s = e + 1;
      }
    }
    flush(); out.push(line);
    return out;
  }

  CS.hl = { detect: detect, label: function (lang) { return has(LABEL, lang) ? LABEL[lang] : lang; }, lines: lines };
})(window.CS);
