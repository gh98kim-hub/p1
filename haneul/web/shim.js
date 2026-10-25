// exe판에서 claude.ai 뷰어 대신 window.claude를 채운다.
// 화면(index.html)은 웹판과 같은 파일이고, Claude 호출과 자료 저장만 이 PC의 프로그램에 맡긴다.
(function () {
  "use strict";
  const HDR = { "Content-Type": "application/json", "X-Haneul": "1" };

  function api(path, body) {
    return fetch(path, { method: "POST", headers: HDR, body: JSON.stringify(body || {}) })
      .then(r => r.json().catch(() => ({ error: { code: "upstream_error", message: "HTTP " + r.status } })))
      .then(j => { if (j.error) throw j.error; return j; },
            e => { if (e && e.code) throw e; throw { code: "upstream_error", message: String(e), detail: "편집툴 프로그램과 연결이 끊겼습니다. 프로그램 창이 켜져 있는지 확인하세요." }; });
  }

  function parseJson(t) {
    try { return JSON.parse(t); } catch (_) {}
    const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (fence) { try { return JSON.parse(fence[1]); } catch (_) {} }
    const i = t.search(/[[{]/), j = Math.max(t.lastIndexOf("}"), t.lastIndexOf("]"));
    if (i >= 0 && j > i) return JSON.parse(t.slice(i, j + 1));
    throw new Error("no json");
  }

  // ---- sample: 한 번에 답을 받는다(스트리밍 없음)
  function call(input, opts, asJson) {
    opts = opts || {};
    const prompt = typeof input === "string" ? input
      : input.map(t => (t.role === "assistant" ? "[이전 답]\n" : "") + t.content).join("\n\n");
    if (opts.signal && opts.signal.aborted) return Promise.reject({ code: "cancelled", message: "aborted" });
    return new Promise((resolve, reject) => {
      let done = false;
      if (opts.signal) opts.signal.addEventListener("abort", () => { if (!done) { done = true; reject({ code: "cancelled", message: "aborted" }); } });
      api("/api/sample", { prompt, json: !!asJson }).then(j => {
        if (done) return; done = true;
        const text = String(j.text || "");
        if (opts.onText) { try { opts.onText({ text, delta: text }); } catch (_) {} }
        if (!asJson) return resolve({ text, truncated: false, modelTierApplied: "default" });
        try { resolve(parseJson(text)); } catch (_) { reject({ code: "invalid_json", message: "bad json", text }); }
      }, e => { if (!done) { done = true; reject(e); } });
    });
  }
  const sample = (i, o) => call(i, o, false);
  sample.json = (i, o) => call(i, o, true);
  sample.limits = () => Promise.resolve({ maxPromptBytes: 262144 });

  // ---- db: 이 PC의 haneul_data.json
  const META = { fromCache: false, hasPendingWrites: false };
  const listeners = new Set();
  // 여러 건을 잇달아 저장할 때 목록을 매번 다시 읽지 않도록 잠깐 모았다가 한 번에 알린다.
  let pending = null;
  const notify = () => { clearTimeout(pending); pending = setTimeout(() => listeners.forEach(fn => fn()), 200); };
  const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  const docSnap = (id, data) => ({ id, exists: data != null, data: () => (data == null ? undefined : data), metadata: META });
  function watch(run, next, err) {
    let live = true;
    const fire = () => { if (live) run().then(s => { if (live) next(s); }, e => { if (live && err) err(e); }); };
    listeners.add(fire); fire();
    return () => { live = false; listeners.delete(fire); };
  }
  function docRef(path) {
    const ref = {
      id: path.split("/").pop(), path,
      get: () => api("/api/db/get", { path }).then(j => docSnap(ref.id, j.data)),
      set: data => api("/api/db/set", { path, data }).then(notify),
      update: data => api("/api/db/update", { path, data }).then(notify),
      delete: () => api("/api/db/delete", { path }).then(notify),
      onSnapshot: (next, err) => watch(ref.get, next, err),
      collection: sub => collRef(path + "/" + sub),
      acquire: () => Promise.resolve({ acquired: true }),
    };
    return ref;
  }
  function query(path, q) {
    const run = () => api("/api/db/list", { collection: path, orderBy: q.orderBy, dir: q.dir, limit: q.limit }).then(j => {
      const docs = j.docs.map(d => docSnap(d.id, d.data));
      return { docs, size: docs.length, empty: !docs.length, docChanges: () => [], metadata: META };
    });
    return {
      where() { return this; },
      orderBy: (f, dir) => query(path, { ...q, orderBy: f, dir: dir || "asc" }),
      limit: n => query(path, { ...q, limit: n }),
      get: run,
      onSnapshot: (next, err) => watch(run, next, err),
    };
  }
  function collRef(path) {
    return Object.assign(query(path, {}), {
      path,
      doc: id => docRef(path + "/" + (id || newId())),
      add: data => { const r = docRef(path + "/" + newId()); return r.set(data).then(() => r); },
    });
  }
  const db = { doc: docRef, collection: collRef };

  const user = {
    isOwner: () => Promise.resolve(true), canEdit: () => Promise.resolve(true), can: () => Promise.resolve(true),
    id: () => Promise.resolve("local"), me: () => Promise.resolve({ id: "local", name: "", guest: false }),
    profiles: () => Promise.resolve({}),
  };

  const caps = { sample, db, user };
  window.claude = Object.freeze({ use: name => Promise.resolve(caps[name] || null) });
})();
