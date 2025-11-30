function s(e) {
  c(e);
  const t = a(e);
  return e.on = t.on, e.off = t.off, e.fire = t.fire, e;
}
function a(e) {
  let t = /* @__PURE__ */ Object.create(null);
  return {
    on: function(n, r, f) {
      if (typeof r != "function")
        throw new Error("callback is expected to be a function");
      let o = t[n];
      return o || (o = t[n] = []), o.push({ callback: r, ctx: f }), e;
    },
    off: function(n, r) {
      if (typeof n > "u")
        return t = /* @__PURE__ */ Object.create(null), e;
      if (t[n])
        if (typeof r != "function")
          delete t[n];
        else {
          const l = t[n];
          for (let i = 0; i < l.length; ++i)
            l[i].callback === r && l.splice(i, 1);
        }
      return e;
    },
    fire: function(n) {
      const r = t[n];
      if (!r)
        return e;
      let f;
      arguments.length > 1 && (f = Array.prototype.slice.call(arguments, 1));
      for (let o = 0; o < r.length; ++o) {
        const l = r[o];
        l.callback.apply(l.ctx, f);
      }
      return e;
    }
  };
}
function c(e) {
  if (!e)
    throw new Error("Eventify cannot use falsy object as events subject");
  const t = ["on", "fire", "off"];
  for (let n = 0; n < t.length; ++n)
    if (e.hasOwnProperty(t[n]))
      throw new Error("Subject cannot be eventified, since it already has property '" + t[n] + "'");
}
export {
  s as default
};
//# sourceMappingURL=ngraph.events.es.js.map
