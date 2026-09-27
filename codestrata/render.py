"""把 layout 的结果渲染成一个自包含的 HTML。

一个文件，不依赖外部资源（语法高亮是可选的 Pygments，没装就退化成纯文本）。
支持把 runtime trace 叠在同一套坐标上：节点填充深浅 = 被调次数，边的粗细 = 调用次数。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from .layout import lane_legend

try:
    from pygments import highlight as _pyg_highlight
    from pygments.lexers import PythonLexer as _PyLexer
    from pygments.formatters import HtmlFormatter as _HtmlFmt
    _HAS_PYGMENTS = True
except Exception:                                   # pragma: no cover
    _HAS_PYGMENTS = False


def _excerpt(root: Path, rel: str, line: int, n: int = 30) -> str:
    try:
        src = (root / rel).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return ""
    a = max(0, line - 1)
    return "\n".join(src[a:a + n])


def _hl(code: str) -> str:
    if not code:
        return ""
    if _HAS_PYGMENTS:
        return _pyg_highlight(code, _PyLexer(), _HtmlFmt(nowrap=True))
    return html.escape(code)


def collect_sources(index: dict, root: Path, *, per_pkg: int = 14,
                    lines: int = 30, budget_kb: int = 900) -> dict:
    """给每个包挑几个「代表符号」并抽源码。

    挑选规则：类优先（架构信息密度高于函数），再按定义位置靠前排序——
    文件顶部的类通常是那个模块的主角。
    """
    syms = index.get("symbols") or {}
    by_pkg: dict[str, list] = {}
    for key, s in syms.items():
        if "." in s["n"]:            # 跳过方法，保留顶层类/函数
            continue
        by_pkg.setdefault(s["p"], []).append((key, s))
    out: dict[str, dict] = {}
    total = 0
    for pkg, items in by_pkg.items():
        items.sort(key=lambda kv: (kv[1]["k"] != "class", kv[1]["f"], kv[1]["l"]))
        for key, s in items[:per_pkg]:
            if total > budget_kb * 1024:
                break
            code = _excerpt(root, s["f"], s["l"], lines)
            total += len(code)
            out[key] = {"n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"],
                        "p": pkg, "b": s.get("b", []), "c": _hl(code)}
    return out


def render(index: dict, graph: dict, root: Path, *,
           hot: dict | None = None, hot_meta: dict | None = None,
           title: str | None = None, per_pkg: int = 14) -> str:
    repo = index["repo"]
    name = title or repo["name"]
    sources = collect_sources(index, root, per_pkg=per_pkg)

    # 每个包的符号清单（不含源码，用来在详情里列出来）
    syms = index.get("symbols") or {}
    pkg_syms: dict[str, list] = {}
    for key, s in syms.items():
        if "." in s["n"]:
            continue
        pkg_syms.setdefault(s["p"], []).append(
            {"key": key, "n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"],
             "b": s.get("b", [])})
    for v in pkg_syms.values():
        v.sort(key=lambda d: (d["k"] != "class", d["f"], d["l"]))

    data = {
        "repo": repo,
        "graph": graph,
        "lanes": lane_legend(graph["lanes"]),
        "pkgs": index["packages"],
        "pkgSyms": pkg_syms,
        "sources": sources,
        "hot": hot or None,
        "hotMeta": hot_meta or None,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    pyg_css = _HtmlFmt().get_style_defs(".pyg") if _HAS_PYGMENTS else ""

    return _TEMPLATE.replace("__TITLE__", html.escape(name)) \
                    .replace("__PYGCSS__", pyg_css) \
                    .replace("__DATA__", blob)


_TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__ · codestrata</title>
<style>
:root{
  color-scheme:light;
  --ink:#11161f; --body:#39424f; --muted:#6b7686; --faint:#9aa4b2;
  --paper:#f6f7f9; --card:#fff; --sunk:#eef0f4; --line:#dde1e8; --rule:#e6e9ef;
  --hot:#b4690e; --hot-bg:#fdf3e2; --cool:#0f7b74; --cool-bg:#e6f4f2;
  --edge:#c3cad5; --shadow:0 1px 2px rgba(17,22,31,.06),0 8px 24px rgba(17,22,31,.05);
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  color-scheme:dark;
  --ink:#e6eaf1; --body:#b6bfcc; --muted:#8792a3; --faint:#697485;
  --paper:#10141b; --card:#171c25; --sunk:#1d232e; --line:#2a3140; --rule:#242b37;
  --hot:#e8a33d; --hot-bg:#2a2113; --cool:#4db6ac; --cool-bg:#12262a;
  --edge:#39424f; --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.28);
}}
:root[data-theme=dark]{
  color-scheme:dark;
  --ink:#e6eaf1; --body:#b6bfcc; --muted:#8792a3; --faint:#697485;
  --paper:#10141b; --card:#171c25; --sunk:#1d232e; --line:#2a3140; --rule:#242b37;
  --hot:#e8a33d; --hot-bg:#2a2113; --cool:#4db6ac; --cool-bg:#12262a;
  --edge:#39424f; --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.28);
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--body);
  font:14.5px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}
.mono,code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:1240px;margin:0 auto;padding:0 18px 60px}
header{padding:30px 0 16px}
.kick{font:600 11px/1 ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--hot)}
h1{margin:8px 0 6px;font-size:clamp(23px,3.6vw,32px);color:var(--ink);letter-spacing:-.02em;line-height:1.15}
.lede{margin:0;max-width:70ch;font-size:15px}
.stats{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:14px;font:12px/1.5 ui-monospace,monospace;color:var(--muted)}
.stats b{color:var(--ink);font-weight:600}
.bar{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 13px;margin:16px 0 12px;
  background:var(--card);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow)}
.bar .lbl{font:11px/1 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.chip{font:11.5px/1 ui-monospace,monospace;padding:5px 10px;border-radius:13px;cursor:pointer;
  border:1px solid var(--line);background:var(--sunk);color:var(--muted)}
.chip[aria-pressed=true]{background:var(--hot-bg);border-color:var(--hot);color:var(--hot);font-weight:600}
.bar input{font:12.5px/1 ui-monospace,monospace;padding:6px 10px;border-radius:6px;
  border:1px solid var(--line);background:var(--sunk);color:var(--ink);width:180px}
.sp{margin-left:auto}
.hotbanner{display:flex;gap:10px;align-items:baseline;padding:11px 14px;margin:0 0 12px;
  border-left:3px solid var(--hot);background:var(--hot-bg);border-radius:0 7px 7px 0;font-size:13.5px}
.hotbanner b{color:var(--ink)}
.hotbanner .cmd{font:11.5px/1.5 ui-monospace,monospace;color:var(--muted);word-break:break-all}
.gbox{border:1px solid var(--line);border-radius:11px;background:var(--card);box-shadow:var(--shadow);overflow-x:auto}
svg.g{display:block;min-width:900px;width:100%;height:auto}
svg.g text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.laneband{fill:var(--sunk);opacity:.4}
.lanerule{stroke:var(--rule);stroke-width:1}
.lanetxt{font-size:9.5px;fill:var(--faint);letter-spacing:.08em;text-transform:uppercase;font-weight:600}
.lanealt{font-size:9px;fill:var(--faint)}
.e{fill:none;stroke:var(--edge);stroke-width:1.2}
.e.dim{opacity:.08}.e.hi{stroke:var(--hot);stroke-width:2.4;opacity:1}
.e.warm{stroke:var(--hot);opacity:.85}
.nd{cursor:pointer}
.nd rect{fill:var(--card);stroke:var(--line);stroke-width:1.2;rx:6}
.nd .nl{font-size:11.5px;font-weight:600;fill:var(--ink);dominant-baseline:middle}
.nd .ns{font-size:8.5px;fill:var(--faint);dominant-baseline:middle}
.nd.dim{opacity:.18}
.nd.sel rect{stroke:var(--hot);stroke-width:2.4}
.nd.match rect{stroke:var(--hot);stroke-width:2}
.nd.warm rect{fill:var(--hot-bg);stroke:var(--hot)}
.nd.cold rect{stroke-dasharray:3 2;opacity:.75}
.nd:focus{outline:none}.nd:focus rect{stroke:var(--hot);stroke-width:2.4}
.det{margin-top:13px;background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:15px 17px;box-shadow:var(--shadow);min-height:110px}
.det h2{margin:0 0 2px;font:600 16px/1.3 ui-monospace,monospace;color:var(--ink);word-break:break-word}
.det .sub{font:11.5px/1.5 ui-monospace,monospace;color:var(--muted);margin-bottom:10px}
.det .hint{color:var(--muted);font-size:13.5px;margin:0}
.kv{display:flex;flex-wrap:wrap;gap:4px 14px;font:11.5px/1.6 ui-monospace,monospace;color:var(--muted);margin-bottom:10px}
.kv b{color:var(--ink)}
.slist{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:5px;margin-top:8px}
.si{display:flex;gap:7px;align-items:baseline;padding:5px 8px;border:1px solid var(--rule);border-radius:6px;
  background:var(--sunk);cursor:pointer;min-width:0}
.si:hover{border-color:var(--hot)}
.si .k{font:9px/1 ui-monospace,monospace;padding:2px 4px;border-radius:3px;background:var(--card);
  color:var(--muted);flex:none;border:1px solid var(--rule)}
.si .k.c{color:var(--cool);border-color:var(--cool)}
.si .n{font:11.5px/1.4 ui-monospace,monospace;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.si .h{font:10px/1 ui-monospace,monospace;color:var(--hot);margin-left:auto;flex:none}
.srcbox{margin-top:13px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--sunk)}
.srchead{display:flex;gap:9px;align-items:center;padding:7px 11px;background:var(--card);
  border-bottom:1px solid var(--line);font:11.5px/1.4 ui-monospace,monospace}
.srchead .p{color:var(--muted);flex:1;min-width:0;word-break:break-all}
.srchead .p b{color:var(--ink)}
.srchead button,.srchead a{font:11px/1 ui-monospace,monospace;padding:4px 9px;border-radius:5px;
  border:1px solid var(--line);background:var(--sunk);color:var(--body);cursor:pointer;
  text-decoration:none;white-space:nowrap}
.srchead button:hover,.srchead a:hover{border-color:var(--hot);color:var(--hot)}
.srcscroll{overflow:auto;max-height:420px}
.srcgrid{display:flex;align-items:flex-start}
.gut{white-space:pre;text-align:right;padding:10px 9px 10px 11px;color:var(--faint);
  background:var(--card);border-right:1px solid var(--rule);
  font:12px/1.6 ui-monospace,monospace;user-select:none;flex:none;font-variant-numeric:tabular-nums}
pre.code{margin:0;padding:10px 15px 10px 11px;font:12px/1.6 ui-monospace,monospace;
  color:var(--ink);white-space:pre;flex:1;min-width:0}
footer{margin-top:40px;padding-top:18px;border-top:1px solid var(--rule);font-size:12.5px;color:var(--muted)}
__PYGCSS__
</style>

<div class="wrap">
<header>
  <div class="kick">codestrata</div>
  <h1 id="h1"></h1>
  <p class="lede" id="lede"></p>
  <div class="stats" id="stats"></div>
</header>

<div id="hotbanner"></div>

<div class="bar">
  <span class="lbl">边</span>
  <button class="chip" id="cEdges" aria-pressed="true">import 依赖</button>
  <button class="chip" id="cHot" aria-pressed="true">runtime 调用</button>
  <span class="lbl" style="margin-left:8px">视图</span>
  <button class="chip" id="cOnly" aria-pressed="false">只看跑到的</button>
  <span class="sp"></span>
  <input id="q" type="search" placeholder="高亮包 / 符号…">
  <button class="chip" id="cReset">重置</button>
</div>

<div class="gbox"><svg class="g" id="g"></svg></div>
<div class="det" id="det"></div>

<footer id="foot"></footer>
</div>

<script type="application/json" id="d">__DATA__</script>
<script>
(function(){
var D = JSON.parse(document.getElementById('d').textContent);
var G = D.graph, NS='http://www.w3.org/2000/svg';
var hotPk = (D.hot && D.hot.packages) || {}, hotEd = (D.hot && D.hot.edges) || {},
    hotSym = (D.hot && D.hot.symbols) || {};
var hasHot = !!D.hot;
function el(t,a){var e=document.createElementNS(NS,t);for(var k in a)e.setAttribute(k,a[k]);return e;}
function esc(s){return String(s).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}

// ---- 头部 ----
var r=D.repo;
document.getElementById('h1').textContent = r.name + ' 架构';
document.getElementById('lede').innerHTML =
  '纵轴是<b>架构高度</b> <code>(出−入)/(出+入)</code>：最上面一条泳道谁都不依赖它、它依赖一切；'+
  '最下面一条只被依赖。横轴用重心排序减少连线交叉。'+
  (hasHot ? ' 橙色是这次 <b>runtime</b> 真正跑到的部分。' : ' 点节点看它的符号与源码。');
var st=[['文件',r.n_files],['包',Object.keys(D.pkgs).length],['符号',D.repo.n_symbols||Object.keys(D.sources).length],
        ['import 边',G.edges.length],['解析失败',r.n_parse_errors]];
document.getElementById('stats').innerHTML = st.map(function(p){
  return '<span>'+p[0]+' <b>'+p[1]+'</b></span>';}).join('')+
  '<span>粒度 <b>depth='+r.depth+'</b></span>';

if(hasHot && D.hotMeta){
  var m=D.hotMeta;
  document.getElementById('hotbanner').innerHTML =
    '<div class="hotbanner"><div><b>hot 图</b>：case <b>'+esc(m.case||'?')+'</b>　'+
    (m.n_procs?('跨 '+m.n_procs+' 个进程　'):'')+
    (m.unmapped?('未映射调用 '+m.unmapped+'　'):'')+
    '<div class="cmd">'+esc((m.cmd||[]).join(' '))+'</div></div></div>';
}

// ---- 画布 ----
var svg=document.getElementById('g');
svg.setAttribute('viewBox','0 0 '+G.width+' '+G.height);
var lg=el('g',{});
D.lanes.forEach(function(L){
  var y=G.top+L.i*G.lane_h;
  if(L.i%2===0) lg.appendChild(el('rect',{x:0,y:y,width:G.width,height:G.lane_h,class:'laneband'}));
  lg.appendChild(el('line',{x1:0,y1:y,x2:G.width,y2:y,class:'lanerule'}));
  if(L.name){var t=el('text',{x:8,y:y+14,class:'lanetxt'});t.textContent=L.name;lg.appendChild(t);}
  var a=el('text',{x:8,y:y+(L.name?26:14),class:'lanealt'});
  a.textContent=(L.hi>0?'+':'')+L.hi.toFixed(2)+'…'+(L.lo>0?'+':'')+L.lo.toFixed(2);
  lg.appendChild(a);
});
svg.appendChild(lg);
var defs=el('defs',{});
[['a','var(--edge)'],['ah','var(--hot)']].forEach(function(p){
  var mk=el('marker',{id:p[0],viewBox:'0 0 8 8',refX:'7',refY:'4',markerWidth:'5.5',
    markerHeight:'5.5',orient:'auto-start-reverse'});
  mk.appendChild(el('path',{d:'M0,0 L8,4 L0,8 z',fill:p[1]}));defs.appendChild(mk);});
svg.appendChild(defs);

var N={}; G.nodes.forEach(function(n){ n.cx=n.x*G.width; n.cy=G.top+n.lane*G.lane_h+G.lane_h/2; N[n.id]=n; });

// 边
var eg=el('g',{}); svg.appendChild(eg); var EE=[];
var maxHotE=1; for(var k in hotEd) maxHotE=Math.max(maxHotE,hotEd[k]);
G.edges.forEach(function(e){
  var a=N[e[0]],b=N[e[1]]; if(!a||!b) return;
  var y1=a.cy+a.h/2, y2=b.cy-b.h/2-3;
  if(b.cy<a.cy){y1=a.cy-a.h/2;y2=b.cy+b.h/2+3;}
  var my=(y1+y2)/2, d;
  if(Math.abs(a.cy-b.cy)<2){ d='M'+(a.cx+a.w/2+3)+','+a.cy+' L'+(b.cx-b.w/2-4)+','+b.cy; }
  else { d='M'+a.cx+','+y1+' C'+a.cx+','+my+' '+b.cx+','+my+' '+b.cx+','+y2; }
  var hits=hotEd[e[0]+'|'+e[1]]||0;
  var p=el('path',{d:d,class:'e'+(hits?' warm':''),'marker-end':'url(#'+(hits?'ah':'a')+')'});
  if(hits) p.setAttribute('stroke-width', (1.2+2.2*Math.log1p(hits)/Math.log1p(maxHotE)).toFixed(2));
  p.dataset.a=e[0];p.dataset.b=e[1];p.dataset.w=e[2];p.dataset.hits=hits;
  eg.appendChild(p);EE.push(p);
});

// 节点
var ng=el('g',{}); svg.appendChild(ng); var NE={};
var maxHotP=1; for(var k2 in hotPk) maxHotP=Math.max(maxHotP,hotPk[k2]);
G.nodes.forEach(function(n){
  var hits=hotPk[n.id]||0;
  var g=el('g',{class:'nd'+(hasHot?(hits?' warm':' cold'):''),tabindex:'0',role:'button'});
  g.dataset.id=n.id;
  g.appendChild(el('rect',{x:n.cx-n.w/2,y:n.cy-n.h/2,width:n.w,height:n.h}));
  var t=el('text',{x:n.cx,y:n.cy-3,class:'nl','text-anchor':'middle'});t.textContent=n.label;g.appendChild(t);
  var s=el('text',{x:n.cx,y:n.cy+9,class:'ns','text-anchor':'middle'});
  s.textContent=n.files+'f · '+n.classes+'c'+(hits?(' · '+hits+' hits'):'');g.appendChild(s);
  ng.appendChild(g);NE[n.id]=g;
});

// ---- 交互 ----
var det=document.getElementById('det'), sel=null, onlyHot=false,
    showE=true, showH=true;
function nb(id){var i=[],o=[];G.edges.forEach(function(e){
  if(e[0]===id)o.push(e[1]); if(e[1]===id)i.push(e[0]);});return{i:i,o:o};}
function vis(id){ return !onlyHot || (hotPk[id]||0)>0; }
function paint(){
  EE.forEach(function(p){
    var hot=+p.dataset.hits>0;
    var show=(hot?showH:showE) && vis(p.dataset.a) && vis(p.dataset.b);
    p.style.display=show?'':'none';
    p.classList.toggle('dim', !!sel && show && p.dataset.a!==sel && p.dataset.b!==sel);
    p.classList.toggle('hi', !!sel && show && (p.dataset.a===sel||p.dataset.b===sel));
  });
  var keep=null;
  if(sel){var x=nb(sel);keep={};keep[sel]=1;x.i.concat(x.o).forEach(function(i){keep[i]=1;});}
  G.nodes.forEach(function(n){var g=NE[n.id];
    g.style.display=vis(n.id)?'':'none';
    g.classList.toggle('dim',!!keep&&!keep[n.id]);
    g.classList.toggle('sel',sel===n.id);});
}
function srcBox(key){
  var s=D.sources[key];
  if(!s) return '';
  var loc=s.f+':'+s.l, g=[],n=(s.c?s.c.split('\n').length:0);
  for(var i=0;i<n;i++)g.push(s.l+i);
  var hits=hotSym[key]||0;
  return '<div class="srcbox"><div class="srchead"><span class="p"><b>'+esc(s.n)+'</b>　'+esc(loc)+
    (s.b&&s.b.length?('　继承 '+esc(s.b.join(', '))):'')+
    (hits?('　<span style="color:var(--hot)">runtime '+hits+' 次</span>'):'')+
    '</span><button data-copy="'+esc(loc)+'">复制路径</button>'+
    '<a href="/open?f='+encodeURIComponent(s.f)+'&l='+s.l+'" data-open>编辑器打开</a>'+
    '</div><div class="srcscroll"><div class="srcgrid"><div class="gut">'+g.join('\n')+
    '</div><pre class="code pyg"><code>'+(s.c||'')+'</code></pre></div></div></div>';
}
function wire(){
  Array.prototype.forEach.call(det.querySelectorAll('[data-go]'),function(b){
    b.onclick=function(){ pick(b.dataset.go); };});
  Array.prototype.forEach.call(det.querySelectorAll('[data-sym]'),function(b){
    b.onclick=function(){ showSym(b.dataset.pkg, b.dataset.sym); };});
  Array.prototype.forEach.call(det.querySelectorAll('[data-copy]'),function(b){
    b.onclick=function(){ var t=b.dataset.copy;
      if(navigator.clipboard&&navigator.clipboard.writeText)
        navigator.clipboard.writeText(t).then(function(){b.textContent='已复制';
          setTimeout(function(){b.textContent='复制路径';},1200);},function(){});
    };});
  // 只有本地 serve 时「编辑器打开」才有意义
  var local=/^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  Array.prototype.forEach.call(det.querySelectorAll('[data-open]'),function(a){
    if(!local){ a.remove(); return; }
    a.onclick=function(ev){ ev.preventDefault(); fetch(a.getAttribute('href')).catch(function(){}); };
  });
}
function pkgDetail(id, symKey){
  var n=N[id], v=D.pkgs[id]||{}, x=nb(id), list=D.pkgSyms[id]||[];
  function pills(a,l){ if(!a.length)return '';
    return '<div class="kv"><span>'+l+'</span>'+a.map(function(i){
      return '<button class="chip" data-go="'+esc(i)+'">'+esc((N[i]||{}).label||i)+'</button>';}).join('')+'</div>';}
  var hits=hotPk[id]||0;
  det.innerHTML='<h2>'+esc(id)+'</h2>'+
    '<div class="sub">架构高度 '+(v.alt>=0?'+':'')+(v.alt||0).toFixed(2)+
      '　出 '+(v.out||0)+' / 入 '+(v.in||0)+
      (hasHot?('　runtime '+(hits?(hits+' 次调用'):'未跑到')):'')+'</div>'+
    '<div class="kv"><span>文件 <b>'+(v.files||0)+'</b></span><span>行 <b>'+(v.loc||0)+'</b></span>'+
      '<span>类 <b>'+(v.classes||0)+'</b></span><span>函数 <b>'+(v.funcs||0)+'</b></span></div>'+
    pills(x.o,'依赖 →')+pills(x.i,'← 被依赖')+
    (list.length?('<div class="slist">'+list.slice(0,40).map(function(s){
      var h=hotSym[s.key]||0;
      return '<div class="si" data-sym="'+esc(s.key)+'" data-pkg="'+esc(id)+'">'+
        '<span class="k'+(s.k==='class'?' c':'')+'">'+(s.k==='class'?'C':'f')+'</span>'+
        '<span class="n" title="'+esc(s.n)+'">'+esc(s.n)+'</span>'+
        (h?('<span class="h">'+h+'</span>'):'')+'</div>';}).join('')+'</div>'):'')+
    (symKey?srcBox(symKey):'');
  wire();
}
function showSym(pkg,key){ pkgDetail(pkg,key);
  var b=det.querySelector('.srcbox'); if(b&&b.scrollIntoView)b.scrollIntoView({block:'nearest',behavior:'smooth'}); }
function pick(id){ sel=id; paint(); pkgDetail(id,null);
  var g=NE[id]; if(g&&g.scrollIntoView)g.scrollIntoView({block:'nearest',inline:'center',behavior:'smooth'}); }
function reset(){ sel=null; document.getElementById('q').value='';
  G.nodes.forEach(function(n){NE[n.id].classList.remove('match');});
  det.innerHTML='<p class="hint"><b>怎么读：</b>每条泳道是一段架构高度区间，越上面越靠入口、越下面越是被依赖的叶子。'+
    '节点大小编码文件数。点节点看它依赖谁、被谁依赖，以及它里面的类和函数；'+
    '再点一个符号会展开源码（带真实行号）。'+
    (hasHot?' 橙色节点和粗边是这次 runtime 真正跑到的。':'')+'</p>';
  paint(); }
Object.keys(NE).forEach(function(id){
  NE[id].onclick=function(){pick(id);};
  NE[id].onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(id);}};});
document.getElementById('cEdges').onclick=function(){showE=this.getAttribute('aria-pressed')!=='true';
  this.setAttribute('aria-pressed',showE);paint();};
document.getElementById('cHot').onclick=function(){showH=this.getAttribute('aria-pressed')!=='true';
  this.setAttribute('aria-pressed',showH);paint();};
document.getElementById('cOnly').onclick=function(){onlyHot=this.getAttribute('aria-pressed')!=='true';
  this.setAttribute('aria-pressed',onlyHot);paint();};
document.getElementById('cReset').onclick=reset;
document.getElementById('q').oninput=function(){
  var t=this.value.trim().toLowerCase();
  G.nodes.forEach(function(n){
    var hit=false;
    if(t){ hit=(n.id+' '+n.label).toLowerCase().indexOf(t)!==-1;
      if(!hit) (D.pkgSyms[n.id]||[]).some(function(s){
        if(s.n.toLowerCase().indexOf(t)!==-1){hit=true;return true;} return false;}); }
    NE[n.id].classList.toggle('match',hit);});};
if(!hasHot) document.getElementById('cHot').style.display='none';
if(!hasHot) document.getElementById('cOnly').style.display='none';
document.getElementById('foot').innerHTML =
  'codestrata · 静态部分由 <code>ast</code> 遍历 <code>'+esc((r.roots||[]).join(', '))+
  '</code> 得出（'+r.n_files+' 文件，解析失败 '+r.n_parse_errors+'）'+
  (hasHot?'；hot 部分来自 runtime hook。':'。');
reset();
})();
</script>
"""
