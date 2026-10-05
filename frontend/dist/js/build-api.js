/* 建筑导入 · 真实接口客户端（替换 mock-build.js）
   ============================================================================
   后端 12 条路由（`backend/app/routers/build.py`，已挂载）对应的前端调用唯一出处。

   为什么要有这一层（而不是页面里直接 API.get/post）：
   后端的字段比 UI 需要的**更丰富**，两侧名字也不完全一致，例如任务：

     后端 BuildTask.to_dict(): { task_id, status, stage, message, progress, total, percent, … }
     页面需要:                { task_id, state,  written_chunks, total_chunks, error, … }

   适配层把后端形状归一成页面已经渲染的字段（`state` / `written_chunks` / `total_chunks`），
   于是 `build.js` 的渲染逻辑**一行都不用改**；同时保留 `stage`/`message`/`percent`/`result`
   等后端真实字段给后续 UI 用。

   铁律（契约 §1.15）：`palette_unmapped` / `warnings` / `chunks_touched` / `engine_recommended`
   **只渲染后端返回值**，前端绝不算、不估、不兜底编造。

   失败约定：所有方法 **resolve `{ok:false, error}`**（而不是 reject），
   因为调用点原来是同步取 `r.ok` / `r.error` 的写法，保持同构可以少改一遍。
   ========================================================================== */
window.Build = (function () {

  /* 终端态：页面用它判断"任务是否已结束、要不要停轮询" */
  var TERMINAL = { done: 1, failed: 1, cancelled: 1 };

  function fail(e) {
    return { ok: false, error: (e && e.message) || String(e || '请求失败'),
             status: (e && e.status) || 0 };
  }

  function base(iid) { return '/api/instances/' + iid + '/build'; }

  /* ---------------------------------------------------------------- 支持格式 */
  function formats() {
    return API.get('/api/build/formats').then(function (d) {
      /* 后端 ext 带点（'.schem'），老 mock 不带 —— 归一成带点并补 name 字段 */
      var list = (d.formats || []).map(function (f) {
        var ext = String(f.ext || '');
        if (ext && ext.charAt(0) !== '.') ext = '.' + ext;
        return {
          ext: ext, ext_bare: ext.replace(/^\./, ''),
          name: f.label || f.name || ext,
          label: f.label || f.name || ext,
          versions: f.versions || '',
          supported: f.supported !== false,
          recognized: f.recognized !== false,
          needs_convert: f.supported === false,
          note: f.note || ''
        };
      });
      return { ok: true, formats: list,
               max_size: d.max_upload_bytes || 0,
               limits: d.limits || {}, engines: d.engines || [],
               security: d.security || [] };
    }).catch(function (e) { return Object.assign(fail(e), { formats: [] }); });
  }

  /* ---------------------------------------------------------------- 上传 */
  /* file: File 对象；onProgress(percent) */
  function upload(iid, file, onProgress) {
    return API.upload(base(iid) + '/upload', file, {}, onProgress).then(function (r) {
      return Object.assign({ ok: true }, r);
    }).catch(function (e) { return fail(e); });
  }

  /* 已上传列表（按 upload_id 取回，供"上次传的文件还在"场景） */
  function uploads(iid) {
    return API.get(base(iid) + '/uploads').then(function (r) { return r; })
      .catch(function (e) { return Object.assign(fail(e), { uploads: [] }); });
  }

  function dropUpload(iid, uploadId) {
    return API.del(base(iid) + '/uploads/' + encodeURIComponent(uploadId))
      .catch(function (e) { return fail(e); });
  }

  /* ---------------------------------------------------------------- 预检 */
  function preview(iid, uploadId, opts) {
    opts = opts || {};
    var body = {
      upload_id: uploadId,
      x: Number(opts.x) || 0, y: Number(opts.y) || 0, z: Number(opts.z) || 0,
      dimension: opts.dimension || 'overworld',
      rotate: Number(opts.rotate) || 0,
      mirror: opts.mirror || 'none',
      place_mode: opts.place_mode || 'only_air',
      replace_list: opts.replace_list || [],
      include_entities: !!opts.include_entities,
      include_biome: !!opts.include_biome,
      mc_version: opts.mc_version || '',
      engine: opts.engine || 'auto',
      member: opts.member || '',
      strict: !!opts.strict
    };
    return API.post(base(iid) + '/preview', body).then(function (r) {
      /* 后端直接返回报告（含 ok 字段）；这里只补齐"格式带点"的一致性 */
      if (r && r.format) {
        var f = String(r.format);
        r.format_bare = f.replace(/^\./, '');
      }
      return r;
    }).catch(function (e) {
      /* 预检失败通常是**有意义的业务拒绝**（越界/未映射/格式不支持）→ 原样带回来 */
      var r = fail(e);
      r.rejected = true;
      return r;
    });
  }

  /* ---------------------------------------------------------------- 导入任务 */
  function importBuild(iid, opts) {
    opts = opts || {};
    var body = {
      upload_id: opts.upload_id,
      x: Number(opts.x) || 0, y: Number(opts.y) || 0, z: Number(opts.z) || 0,
      dimension: opts.dimension || 'overworld',
      rotate: Number(opts.rotate) || 0,
      mirror: opts.mirror || 'none',
      place_mode: opts.place_mode || 'only_air',
      replace_list: opts.replace_list || [],
      include_entities: !!opts.include_entities,
      include_biome: !!opts.include_biome,
      mc_version: opts.mc_version || '',
      engine: opts.engine || 'auto',
      member: opts.member || '',
      backup: opts.backup !== false,
      allow_empty: !!opts.allow_empty,
      abort_on_unmapped: !!opts.abort_on_unmapped,
      allow_missing_chunks: !!opts.allow_missing_chunks
    };
    return API.post(base(iid) + '/import', body).catch(function (e) { return fail(e); });
  }

  /* 任务归一：后端形状 → 页面渲染用的形状 */
  function normalizeTask(d) {
    if (!d || typeof d !== 'object') return d;
    var t = Object.assign({}, d);
    t.raw_status = d.status;
    /* 页面读 `state`；后端叫 `status`。终态名字两边一致，直接映射。 */
    t.state = d.status || d.state || 'queued';
    t.finished = !!TERMINAL[t.state];
    var total = Number(d.total || d.report && d.report.chunks_touched || 0);
    var done = Number(d.progress || 0);
    t.total_chunks = total || Number(d.total_chunks || 0);
    t.written_chunks = t.total_chunks ? Math.min(t.total_chunks, done) : done;
    t.progress = done;
    if (d.percent !== undefined) t.percent = d.percent;
    t.error = d.error || '';
    return t;
  }

  function task(iid, taskId) {
    return API.get(base(iid) + '/tasks/' + encodeURIComponent(taskId))
      .then(normalizeTask)
      .catch(function (e) { return fail(e); });
  }

  function cancel(iid, taskId) {
    return API.post(base(iid) + '/tasks/' + encodeURIComponent(taskId) + '/cancel', {})
      .catch(function (e) { return fail(e); });
  }

  function rollback(iid, taskId) {
    return API.post(base(iid) + '/rollback/' + encodeURIComponent(taskId), {})
      .catch(function (e) { return fail(e); });
  }

  /* 导入记录（历史）：后端返回 {ok, tasks:[…]} */
  function history(iid, limit) {
    return API.get(base(iid) + '/tasks?limit=' + (limit || 30))
      .then(function (r) {
        return (r.tasks || []).map(normalizeTask);
      })
      .catch(function () { return []; });
  }

  /* 导入备份列表（回滚用得上） */
  function backups(iid) {
    return API.get(base(iid) + '/backups')
      .then(function (r) { return r.backups || []; })
      .catch(function () { return []; });
  }

  /* 版本注册表可用性（"未映射方块"清单的可信度取决于它） */
  function registry(iid, mcVersion) {
    return API.get(base(iid) + '/registry' + (mcVersion ? '?mc_version=' + encodeURIComponent(mcVersion) : ''))
      .catch(function (e) { return Object.assign(fail(e), { available: false }); });
  }

  return { formats: formats, upload: upload, uploads: uploads, dropUpload: dropUpload,
           preview: preview, importBuild: importBuild, task: task, cancel: cancel,
           rollback: rollback, history: history, backups: backups, registry: registry,
           normalizeTask: normalizeTask, TERMINAL: TERMINAL, isTerminal: function (s) { return !!TERMINAL[s]; } };
})();
