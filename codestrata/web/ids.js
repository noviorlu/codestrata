/* 节点 id 的写法，和 cut.py 是同一套（按路径，不认语言）：
   单元是文件相对仓库根的路径（vllm_omni/engine/core.py），目录是路径加 /（vllm_omni/engine/），
   本层文件是 <目录>*（vllm_omni/engine/*），仓库根目录直接放着的脚本在 ./ 里。
   显示名不从 id 拆：用数据里的 names（短名）和 label（显示名）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var ROOT = './';

  CS.ids = {
    ROOT: ROOT,
    isResidual: function (id) { return /\/\*$/.test(id); },
    /* 本层文件节点 → 它的目录；别的原样 */
    base: function (id) { return /\/\*$/.test(id) ? id.slice(0, -1) : id; },
    residual: function (d) { return d + '*'; },
    /* 单元所在的目录 */
    dirOf: function (unit) { var i = unit.lastIndexOf('/'); return i >= 0 ? unit.slice(0, i + 1) : ROOT; },
    /* x（目录、本层文件、单元）在目录 d 的子树里（不含 d 自己） */
    within: function (x, d) {
      if (d === ROOT) return x !== d && (x === ROOT + '*' || x.indexOf('/') < 0);
      return x !== d && x.indexOf(d) === 0;
    },
    /* 路径的最后一段（数据里没有显示名时兜底用） */
    last: function (id) {
      var p = String(id).replace(/\*$/, '').replace(/\/$/, '').split('/');
      return p[p.length - 1] || String(id);
    }
  };
})(window.CS);
