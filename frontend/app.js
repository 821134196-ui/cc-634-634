/* 签证材料原件托管与领回系统 —— Vue 3 单文件前端（CDN/本地 vendor） */
const { createApp, reactive, computed, onMounted, watch, h } = Vue;

const STATUS_LABEL = {
  received: "在库保管", submitted: "外部办理中", returned: "已退件待领回", held: "已领回",
};
const ROLE_LABEL = { admin: "管理员", reception: "前台收件岗", handler: "经办岗", viewer: "只读统计岗" };

function api(path, opts = {}) {
  const token = localStorage.getItem("vcd_token");
  const headers = Object.assign({}, opts.headers || {});
  if (token) headers.Authorization = "Bearer " + token;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  return fetch("/api" + path, Object.assign({}, opts, { headers })).then(async (r) => {
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!r.ok) throw new Error((data && data.detail) || `请求失败 ${r.status}`);
    return data;
  });
}

/* ---------------- 登录页 ---------------- */
const LoginPage = {
  emits: ["logged-in"],
  setup(_, { emit }) {
    const s = reactive({ username: "reception", password: "recep123", err: "", loading: false });
    const submit = async () => {
      s.err = ""; s.loading = true;
      try {
        const r = await api("/auth/login", { method: "POST", body: { username: s.username, password: s.password } });
        localStorage.setItem("vcd_token", r.token);
        localStorage.setItem("vcd_user", JSON.stringify(r.user));
        emit("logged-in", r.user);
      } catch (e) { s.err = e.message; } finally { s.loading = false; }
    };
    return { s, submit };
  },
  template: `
  <div class="login-wrap">
    <div class="login-card">
      <h1>签证材料原件托管与领回</h1>
      <div class="sub">旅行社内部工作台 · 请按岗位登录</div>
      <div class="field"><label>账号</label><input v-model="s.username" @keyup.enter="submit" /></div>
      <div class="field"><label>口令</label><input v-model="s.password" type="password" @keyup.enter="submit" /></div>
      <div v-if="s.err" class="banner err">{{ s.err }}</div>
      <button class="btn" style="width:100%" :disabled="s.loading" @click="submit">{{ s.loading ? '登录中…' : '登 录' }}</button>
      <div class="login-accounts">
        演示账号（口令见括号）：<br/>
        <code>admin / admin123</code> 管理员｜<code>reception / recep123</code> 收件岗<br/>
        <code>handler / handle123</code> 经办岗（经手演示订单）<br/>
        <code>handler2 / handle123</code> 经办岗（未经手，用于验证跨客户拦截）<br/>
        <code>viewer / view123</code> 只读岗（无权看证件照）
      </div>
    </div>
  </div>`,
};

/* ---------------- 收件页 ---------------- */
const ReceivePage = {
  emits: ["open-order"],
  setup(_, { emit }) {
    const s = reactive({
      destination: "某国驻华使馆签证中心", visaType: "旅游签",
      name: "", phone: "", idNo: "",
      docs: [{ docType: "护照", docName: "", photo: null, photoUrl: "" }],
      err: "", ok: "", busy: false,
    });
    const addDoc = () => s.docs.push({ docType: "护照", docName: "", photo: null, photoUrl: "" });
    const delDoc = (i) => { s.docs.splice(i, 1); };
    const onPhoto = (i, e) => {
      const f = e.target.files[0];
      if (!f) return;
      s.docs[i].photo = f;
      s.docs[i].photoUrl = URL.createObjectURL(f);
    };
    const submit = async () => {
      s.err = ""; s.ok = "";
      if (!s.name || !s.phone || !s.idNo) { s.err = "请填写客户姓名、手机、证件号"; return; }
      for (let i = 0; i < s.docs.length; i++) {
        const d = s.docs[i];
        if (!d.docName || !d.photo) { s.err = `第 ${i + 1} 件缺少材料描述或照片`; return; }
      }
      const fd = new FormData();
      fd.append("destination", s.destination);
      fd.append("visa_type", s.visaType);
      fd.append("customer_name", s.name);
      fd.append("customer_phone", s.phone);
      fd.append("customer_id_no", s.idNo);
      s.docs.forEach((d) => {
        fd.append("doc_types", d.docType);
        fd.append("doc_names", d.docName);
        fd.append("photos", d.photo);
      });
      s.busy = true;
      try {
        const order = await api("/orders", { method: "POST", body: fd });
        s.ok = `收件完成：${order.order_no}，共 ${order.total_count} 件，已向客户发送收件凭证短信（模拟）。`;
        setTimeout(() => emit("open-order", order.id), 700);
      } catch (e) { s.err = e.message; } finally { s.busy = false; }
    };
    return { s, addDoc, delDoc, onPhoto, submit };
  },
  template: `
  <div>
    <div class="panel">
      <h2>收件建档 · 每件原件逐件编号拍照</h2>
      <div v-if="s.err" class="banner err">{{ s.err }}</div>
      <div v-if="s.ok" class="banner ok">{{ s.ok }}</div>
      <div class="row">
        <div class="field" style="flex:1;min-width:200px"><label>客户姓名</label><input v-model="s.name" /></div>
        <div class="field" style="flex:1;min-width:160px"><label>手机号</label><input v-model="s.phone" /></div>
        <div class="field" style="flex:1;min-width:200px"><label>证件号</label><input v-model="s.idNo" /></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>递交机构（使馆/签证中心）</label><input v-model="s.destination" /></div>
        <div class="field" style="flex:1"><label>签证类型</label><input v-model="s.visaType" /></div>
      </div>
      <h3>原件清单（每件一张照片）</h3>
      <div v-for="(d,i) in s.docs" :key="i" class="doc-card">
        <label class="thumb" :style="d.photoUrl ? {backgroundImage:'url('+d.photoUrl+')'} : {}">
          <span v-if="!d.photoUrl">拍照/上传</span>
          <input type="file" accept="image/*" capture="environment" style="display:none" @change="onPhoto(i,$event)" />
        </label>
        <div style="flex:1">
          <div class="row">
            <div class="field" style="width:130px;margin:0">
              <label>第 {{ i+1 }} 件 · 类型</label>
              <select v-model="d.docType">
                <option>护照</option><option>身份证</option><option>户口本</option>
                <option>在职证明</option><option>资产证明</option><option>照片</option><option>其他</option>
              </select>
            </div>
            <div class="field" style="flex:1;margin:0"><label>材料描述（如护照号尾号）</label><input v-model="d.docName" placeholder="例：普通护照 E12345678" /></div>
            <button class="btn ghost sm" style="margin-top:18px" @click="delDoc(i)" :disabled="s.docs.length===1">删除</button>
          </div>
        </div>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn secondary" @click="addDoc">+ 增加一件</button>
        <div class="spacer"></div>
        <button class="btn" :disabled="s.busy" @click="submit">{{ s.busy ? '提交中…' : '完成收件并出具凭证' }}</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 交接动作弹窗 ---------------- */
const ActionModal = {
  props: ["order", "kind", "auths"],
  emits: ["close", "done"],
  setup(props, { emit }) {
    const pickable = computed(() => {
      if (props.kind === "submit") return props.order.materials.filter(m => ["received", "returned"].includes(m.status));
      if (props.kind === "embassy_return") return props.order.materials.filter(m => m.status === "submitted");
      return props.order.materials.filter(m => ["received", "returned"].includes(m.status));
    });
    const s = reactive({
      selected: [], counterparty: "", note: "",
      signMode: "self", delivery: "office", signerName: props.order.customer.name,
      signerId: "", proxyAuthId: null, err: "", busy: false,
    });
    const validAuths = computed(() => (props.auths || []).filter(a => a.valid_now));
    watch(() => props.kind, () => {
      s.selected = pickable.value.map(m => m.id);
      s.proxyAuthId = validAuths.value[0]?.id || null;
    }, { immediate: true });

    const title = computed(() => ({
      submit: "递交使馆/签证中心", embassy_return: "使馆退件登记（可分批）", pickup: "客户领回 · 按件签收",
    })[props.kind]);

    const toggle = (id) => {
      const i = s.selected.indexOf(id);
      if (i >= 0) s.selected.splice(i, 1); else s.selected.push(id);
    };
    const submit = async () => {
      s.err = "";
      if (!s.selected.length) { s.err = "请至少选择一件"; return; }
      try {
        if (props.kind === "submit") {
          if (!s.counterparty) { s.err = "请填写使馆/窗口经办人"; return; }
          await api(`/orders/${props.order.id}/submit`, { method: "POST", body: { material_ids: s.selected, counterparty_name: s.counterparty, note: s.note } });
        } else if (props.kind === "embassy_return") {
          if (!s.counterparty) { s.err = "请填写退件窗口/交接人"; return; }
          await api(`/orders/${props.order.id}/embassy-return`, { method: "POST", body: { material_ids: s.selected, counterparty_name: s.counterparty, note: s.note } });
        } else {
          const body = {
            material_ids: s.selected, sign_mode: s.signMode, delivery_mode: s.delivery,
            signer_name: s.signerName, signer_id_no: s.signerId || null,
            proxy_auth_id: s.signMode === "proxy" ? s.proxyAuthId : null, note: s.note,
          };
          await api(`/orders/${props.order.id}/pickup`, { method: "POST", body });
        }
        emit("done");
      } catch (e) { s.err = e.message; }
    };
    return { s, props, pickable, validAuths, title, toggle, submit, STATUS_LABEL, fmt: (d) => d };
  },
  template: `
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <h2>{{ title }}</h2>
      <div v-if="s.err" class="banner err">{{ s.err }}</div>
      <div v-if="pickable.length===0" class="banner warn">当前没有可操作此动作的材料。</div>
      <div class="checklist">
        <label v-for="m in pickable" :key="m.id">
          <input type="checkbox" :checked="s.selected.includes(m.id)" @change="toggle(m.id)" />
          <span><b>{{ m.item_no }}</b> · {{ m.doc_type }}｜{{ m.doc_name }}
            <span class="badge" :class="m.status">{{ STATUS_LABEL[m.status] }}</span></span>
        </label>
      </div>
      <template v-if="kind==='submit' || kind==='embassy_return'">
        <div class="field" style="margin-top:12px"><label>对方交接人 / 窗口</label><input v-model="s.counterparty" placeholder="例：签证中心 3 号窗口 刘女士" /></div>
      </template>
      <template v-if="kind==='pickup'">
        <div class="field"><label>领回方式</label>
          <select v-model="s.delivery"><option value="office">客户到社自取</option><option value="courier">分批送达（仅追加交接记录）</option></select>
        </div>
        <div class="field"><label>签收人</label>
          <select v-model="s.signMode">
            <option value="self">客户本人</option><option value="proxy">代领人（须有效授权）</option>
          </select>
        </div>
        <div v-if="s.signMode==='proxy'">
          <div class="field"><label>选择授权书</label>
            <select v-model="s.proxyAuthId">
              <option :value="null" disabled>-- 请选择 --</option>
              <option v-for="a in auths" :key="a.id" :value="a.id" :disabled="!a.valid_now">
                {{ a.proxy_name }}（{{ a.proxy_id_no }}）{{ a.valid_now ? '· 有效' : (a.revoked ? '· 已撤销' : '· 已过期') }}
              </option>
            </select>
          </div>
          <div v-if="validAuths.length===0" class="banner err">当前没有有效代领授权，不能代领。请先登记授权。</div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>{{ s.signMode==='proxy' ? '代领人姓名（须与授权书一致）' : '本人姓名' }}</label><input v-model="s.signerName" /></div>
          <div class="field" style="flex:1"><label>{{ s.signMode==='proxy' ? '代领人证件号（须与授权书一致）' : '本人证件号（可留空）' }}</label><input v-model="s.signerId" /></div>
        </div>
      </template>
      <div class="field"><label>备注</label><textarea v-model="s.note"></textarea></div>
      <div class="row" style="justify-content:flex-end">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn" @click="submit">确认交接并按件记录</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 授权登记弹窗 ---------------- */
const AuthModal = {
  props: ["order"],
  emits: ["close", "done"],
  setup(props, { emit }) {
    const today = new Date().toISOString().slice(0, 10);
    const until = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
    const s = reactive({ name: "", idNo: "", from: today, until, note: "", scope: [], err: "" });
    const toggle = (id) => {
      const i = s.scope.indexOf(id);
      if (i >= 0) s.scope.splice(i, 1); else s.scope.push(id);
    };
    const submit = async () => {
      s.err = "";
      if (!s.name || !s.idNo) { s.err = "请填写代领人姓名和证件号"; return; }
      try {
        await api(`/orders/${props.order.id}/proxy-auths`, {
          method: "POST",
          body: { proxy_name: s.name, proxy_id_no: s.idNo, valid_from: s.from, valid_until: s.until, note: s.note, scope_material_ids: s.scope },
        });
        emit("done");
      } catch (e) { s.err = e.message; }
    };
    return { s, props, toggle, submit };
  },
  template: `
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <h2>登记代领授权</h2>
      <div v-if="s.err" class="banner err">{{ s.err }}</div>
      <div class="row">
        <div class="field" style="flex:1"><label>代领人姓名</label><input v-model="s.name" /></div>
        <div class="field" style="flex:1"><label>代领人证件号</label><input v-model="s.idNo" /></div>
      </div>
      <div class="row">
        <div class="field" style="flex:1"><label>授权起</label><input type="date" v-model="s.from" /></div>
        <div class="field" style="flex:1"><label>授权止</label><input type="date" v-model="s.until" /></div>
      </div>
      <div class="field"><label>授权材料范围（不勾=全部材料）</label>
        <div class="checklist">
          <label v-for="m in props.order.materials" :key="m.id">
            <input type="checkbox" :checked="s.scope.includes(m.id)" @change="toggle(m.id)" />
            <span>{{ m.item_no }} · {{ m.doc_type }}｜{{ m.doc_name }}</span>
          </label>
        </div>
      </div>
      <div class="field"><label>备注</label><textarea v-model="s.note"></textarea></div>
      <div class="row" style="justify-content:flex-end">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn" @click="submit">保存授权</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 订单详情 ---------------- */
const OrderDetail = {
  props: ["orderId", "user"],
  emits: ["back"],
  setup(props, { emit }) {
    const s = reactive({ order: null, err: "", modal: "", photo: null, photoErr: "" });
    const load = async () => {
      try { s.order = await api(`/orders/${props.orderId}`); } catch (e) { s.err = e.message; }
    };
    onMounted(load);
    const canReceive = computed(() => ["admin", "reception"].includes(props.user.role));
    const canHandle = computed(() => ["admin", "handler"].includes(props.user.role));
    const openPhoto = async (m) => {
      s.photo = null; s.photoErr = "";
      try {
        const r = await fetch(`/api/materials/${m.id}/photo`, {
          headers: { Authorization: "Bearer " + localStorage.getItem("vcd_token") },
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          s.photoErr = d.detail || "无法查看照片";
          return;
        }
        const blob = await r.blob();
        s.photo = { url: URL.createObjectURL(blob), item: m.item_no };
      } catch (e) { s.photoErr = e.message; }
    };
    const revoke = async (a) => {
      if (!confirm(`确认撤销 ${a.proxy_name} 的代领授权？`)) return;
      await api(`/proxy-auths/${a.id}/revoke`, { method: "POST" });
      load();
    };
    const receiptUrl = (batch) => `/api/orders/${s.order.id}/receipt?batch_no=${encodeURIComponent(batch)}&token_ignored=1`;
    const downloadReceipt = (batch) => {
      // 带 token 下载
      fetch(receiptUrl(batch), { headers: { Authorization: "Bearer " + localStorage.getItem("vcd_token") } })
        .then(async r => {
          if (!r.ok) { alert("回执不可用"); return; }
          const blob = await r.blob();
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob); a.download = `${batch}_回执.txt`; a.click();
        });
    };
    const pubLink = computed(() => location.origin + "/#/receipt/" + (s.order ? s.order.receipt_token : ""));
    const copyLink = () => { navigator.clipboard?.writeText(pubLink.value); };
    return { s, load, canReceive, canHandle, openPhoto, revoke, downloadReceipt, pubLink, copyLink, emit, STATUS_LABEL };
  },
  template: `
  <div v-if="s.err" class="banner err">{{ s.err }}</div>
  <div v-if="s.order">
    <div class="row" style="margin-bottom:12px">
      <button class="btn ghost sm" @click="emit('back')">← 返回列表</button>
      <div class="spacer"></div>
      <button v-if="canHandle" class="btn secondary sm" @click="s.modal='submit'">递交使馆</button>
      <button v-if="canHandle" class="btn secondary sm" @click="s.modal='embassy_return'">使馆退件登记</button>
      <button v-if="canHandle" class="btn sm" @click="s.modal='pickup'">客户领回签收</button>
    </div>

    <div class="stat-row">
      <div class="stat"><div class="n">{{ s.order.total_count }}</div><div class="l">原件总数</div></div>
      <div class="stat"><div class="n">{{ s.order.submitted_count }}</div><div class="l">外部办理中</div></div>
      <div class="stat warn"><div class="n">{{ s.order.returned_count }}</div><div class="l">已退件待领回</div></div>
      <div class="stat ok"><div class="n">{{ s.order.held_count }}</div><div class="l">已按件签收</div></div>
      <div class="stat" :class="s.order.missing_count ? 'warn':'ok'"><div class="n">{{ s.order.missing_count }}</div><div class="l">缺件未归还</div></div>
    </div>

    <div class="panel">
      <div class="row">
        <div>
          <h2 style="margin:0">{{ s.order.order_no }}
            <span v-if="s.order.completed" class="badge held">已完结</span>
            <span v-else class="badge returned">进行中</span>
          </h2>
          <div class="muted" style="margin-top:4px">
            {{ s.order.customer.name }}｜{{ s.order.customer.phone }}｜证件号 {{ s.order.customer.id_number }}
            ｜{{ s.order.destination }}｜{{ s.order.visa_type }}
          </div>
          <div class="banner warn" style="margin:10px 0 0">{{ s.order.current_stage }}</div>
        </div>
        <div class="spacer"></div>
        <div style="width:330px">
          <div class="tag-note">客户收件凭证链接（不含证件影像）</div>
          <div class="copy-link">{{ pubLink }}</div>
          <button class="btn ghost sm" style="margin-top:6px" @click="copyLink">复制链接</button>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>逐件去向（每件独立状态，缺件不会被整单覆盖）</h2>
      <table>
        <thead><tr><th>件号</th><th>原件</th><th>当前位置</th><th>状态</th><th>最新交接</th><th>证件照片</th></tr></thead>
        <tbody>
          <tr v-for="m in s.order.materials" :key="m.id">
            <td class="mono">{{ m.item_no }}</td>
            <td>{{ m.doc_type }}<div class="muted">{{ m.doc_name }}</div></td>
            <td>{{ m.location_text }}</td>
            <td><span class="badge" :class="m.status">{{ STATUS_LABEL[m.status] }}</span></td>
            <td>
              <template v-if="m.events.length">
                {{ m.events[m.events.length-1].event_type_label }}
                <div class="muted">{{ m.events[m.events.length-1].counterparty_name }} · {{ m.events[m.events.length-1].created_at.replace('T',' ').slice(0,16) }}</div>
              </template>
            </td>
            <td><button class="btn ghost sm" @click="openPhoto(m)">查看</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="s.photoErr" class="banner err" style="margin-top:10px">证件照片访问被拒绝：{{ s.photoErr }}（系统已记录审计日志）</div>
    </div>

    <div class="panel">
      <div class="row"><h2 style="margin:0">代领授权</h2><div class="spacer"></div>
        <button v-if="canReceive || canHandle" class="btn secondary sm" @click="s.modal='auth'">+ 登记授权</button>
      </div>
      <table style="margin-top:8px">
        <thead><tr><th>代领人</th><th>证件号</th><th>范围</th><th>有效期</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="a in s.order.proxy_auths" :key="a.id">
            <td>{{ a.proxy_name }}</td><td class="mono">{{ a.proxy_id_no }}</td>
            <td>{{ a.scope_material_ids.length ? a.scope_material_ids.length + ' 件（限定）' : '全部材料' }}</td>
            <td>{{ a.valid_from }} 至 {{ a.valid_until }}</td>
            <td>
              <span v-if="a.revoked" class="auth-expired">已撤销</span>
              <span v-else-if="a.valid_now" class="auth-ok">有效</span>
              <span v-else class="auth-expired">已过期</span>
            </td>
            <td><button v-if="!a.revoked" class="btn danger sm" @click="revoke(a)">撤销</button></td>
          </tr>
          <tr v-if="!s.order.proxy_auths.length"><td colspan="6" class="muted">暂无授权</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>交接流水（只追加，不可修改）</h2>
      <div class="timeline">
        <div class="tl-item" v-for="e in [...s.order.events].reverse()" :key="e.id">
          <div class="tl-type">{{ e.event_type_label }} · <span class="mono">{{ e.item_no || '' }}</span>
            <span class="muted mono" v-if="e.batch_no">批次 {{ e.batch_no }}</span></div>
          <div class="tl-meta">
            件号 <span class="mono">{{ s.order.materials.find(m=>m.id===e.material_id)?.item_no }}</span>
            ｜{{ e.from_party }} → {{ e.to_party }}｜交接人：{{ e.counterparty_name }}
            <template v-if="e.sign_mode==='self'">｜本人签收</template>
            <template v-if="e.sign_mode==='proxy'">｜代领签收（证件 {{ e.counterparty_id }}）</template>
            ｜经办：{{ e.actor_name }}｜{{ e.created_at.replace('T',' ').slice(0,16) }}
            <template v-if="e.has_embassy_receipt">｜<button class="btn ghost sm" @click="downloadReceipt(e.batch_no)">使馆回执</button></template>
            <div v-if="e.note" class="tag-note">备注：{{ e.note }}</div>
          </div>
        </div>
      </div>
    </div>

    <ActionModal v-if="['submit','embassy_return','pickup'].includes(s.modal)" :kind="s.modal" :order="s.order" :auths="s.order.proxy_auths"
      @close="s.modal=''" @done="s.modal='';load()" />
    <AuthModal v-if="s.modal==='auth'" :order="s.order" @close="s.modal=''" @done="s.modal='';load()" />
    <div v-if="s.photo" class="modal-mask photo-modal" @click.self="s.photo=null">
      <div class="modal photo-modal">
        <h2>{{ s.photo.item }} 证件原件照片</h2>
        <img :src="s.photo.url" />
        <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn ghost" @click="s.photo=null">关闭</button></div>
      </div>
    </div>
  </div>`,
};

/* ---------------- 订单列表 ---------------- */
const OrderList = {
  emits: ["open"],
  setup(_, { emit }) {
    const s = reactive({ orders: [], q: "", filter: "", err: "" });
    const load = async () => {
      const p = new URLSearchParams();
      if (s.q) p.set("q", s.q);
      if (s.filter) p.set("status_filter", s.filter);
      try { s.orders = await api("/orders?" + p.toString()); } catch (e) { s.err = e.message; }
    };
    onMounted(load);
    watch(() => [s.q, s.filter], load);
    return { s, emit, STATUS_LABEL };
  },
  template: `
  <div class="panel">
    <h2>订单与原件去向</h2>
    <div v-if="s.err" class="banner err">{{ s.err }}</div>
    <div class="row" style="margin-bottom:10px">
      <input v-model="s.q" placeholder="搜订单号 / 客户姓名" style="max-width:260px" />
      <select v-model="s.filter" style="max-width:180px">
        <option value="">全部</option><option value="active">进行中（含缺件）</option><option value="completed">已完结</option>
      </select>
    </div>
    <table>
      <thead><tr><th>订单号</th><th>客户</th><th>机构/签证</th><th>件数</th><th>在外部</th><th>待领回</th><th>已领回</th><th>缺件</th><th>当前阶段</th><th></th></tr></thead>
      <tbody>
        <tr v-for="o in s.orders" :key="o.id">
          <td class="mono">{{ o.order_no }}</td>
          <td>{{ o.customer.name }}<div class="muted">{{ o.customer.phone }}</div></td>
          <td>{{ o.destination }}<div class="muted">{{ o.visa_type }}</div></td>
          <td>{{ o.total_count }}</td><td>{{ o.submitted_count }}</td><td>{{ o.returned_count }}</td>
          <td>{{ o.held_count }}</td>
          <td><b :style="{color: o.missing_count ? '#b7791f' : '#1b873f'}">{{ o.missing_count }}</b></td>
          <td>{{ o.current_stage }}</td>
          <td><button class="btn secondary sm" @click="emit('open',o.id)">查看</button></td>
        </tr>
      </tbody>
    </table>
  </div>`,
};

/* ---------------- 短信模拟 ---------------- */
const SmsPage = {
  setup() {
    const s = reactive({ msgs: [] });
    onMounted(async () => { s.msgs = await api("/sms").catch(() => []); });
    return { s };
  },
  template: `
  <div class="panel">
    <h2>短信出站记录（模拟发送，未真实下发）</h2>
    <table>
      <thead><tr><th>时间</th><th>类型</th><th>手机号</th><th>内容</th></tr></thead>
      <tbody>
        <tr v-for="m in s.msgs" :key="m.id">
          <td class="muted">{{ m.created_at.replace('T',' ').slice(0,16) }}</td>
          <td>{{ m.kind }}</td><td>{{ m.phone }}</td><td>{{ m.content }}</td>
        </tr>
      </tbody>
    </table>
  </div>`,
};

/* ---------------- 客户凭证（公开，凭 token） ---------------- */
const PublicReceipt = {
  props: ["token"],
  setup(props) {
    const s = reactive({ order: null, err: "" });
    onMounted(async () => {
      try { s.order = await api("/public/orders/" + props.token); } catch (e) { s.err = e.message; }
    });
    return { s, STATUS_LABEL };
  },
  template: `
  <div class="public-wrap">
    <div v-if="s.err" class="banner err">{{ s.err }}</div>
    <div v-if="s.order" class="panel">
      <h2>收件凭证 · {{ s.order.order_no }}</h2>
      <div class="muted">{{ s.order.customer.name }}｜{{ s.order.destination }}｜{{ s.order.visa_type }}</div>
      <div class="banner warn" style="margin-top:10px">{{ s.order.current_stage }}</div>
      <table style="margin-top:8px">
        <thead><tr><th>件号</th><th>原件</th><th>当前位置</th><th>状态</th><th>最新交接</th></tr></thead>
        <tbody>
          <tr v-for="m in s.order.materials" :key="m.id">
            <td class="mono">{{ m.item_no }}</td><td>{{ m.doc_type }}｜{{ m.doc_name }}</td>
            <td>{{ m.location_text }}</td><td><span class="badge" :class="m.status">{{ STATUS_LABEL[m.status] }}</span></td>
            <td>{{ m.events.length ? m.events[m.events.length-1].event_type_label + ' · ' + m.events[m.events.length-1].counterparty_name : '' }}</td>
          </tr>
        </tbody>
      </table>
      <h3>交接流水</h3>
      <div class="timeline">
        <div class="tl-item" v-for="e in [...s.order.events].reverse()" :key="e.id">
          <div class="tl-type">{{ e.event_type_label }}</div>
          <div class="tl-meta">件号 {{ s.order.materials.find(m=>m.id===e.material_id)?.item_no }}
            ｜{{ e.from_party }} → {{ e.to_party }}｜{{ e.counterparty_name }}
            ｜{{ e.created_at.replace('T',' ').slice(0,16) }}</div>
        </div>
      </div>
      <div class="tag-note" style="margin-top:10px">本凭证仅展示去向与交接记录，不展示证件影像。</div>
    </div>
  </div>`,
};

/* ---------------- 根组件 ---------------- */
const App = {
  components: { LoginPage, ReceivePage, OrderList, OrderDetail, SmsPage, PublicReceipt },
  setup() {
    const route = reactive({ hash: location.hash });
    window.addEventListener("hashchange", () => { route.hash = location.hash; });
    const user = reactive(JSON.parse(localStorage.getItem("vcd_user") || "null"));
    const s = reactive({ tab: "orders", openOrderId: null });
    const onLogin = (u) => { Object.assign(user, u); };
    const logout = () => { localStorage.removeItem("vcd_token"); localStorage.removeItem("vcd_user"); location.href = "/"; };
    const pubToken = computed(() => {
      const m = route.hash.match(/^#\/receipt\/(.+)$/);
      return m ? m[1] : null;
    });
    return { user, s, onLogin, logout, pubToken };
  },
  template: `
  <PublicReceipt v-if="pubToken" :token="pubToken" />
  <LoginPage v-else-if="!user" @logged-in="onLogin" />
  <template v-else>
    <div class="topbar">
      <div class="brand" @click="s.tab='orders';s.openOrderId=null">签证材料原件托管与领回系统</div>
      <div class="who">{{ user.display_name }}（{{ {admin:'管理员',reception:'收件岗',handler:'经办岗',viewer:'只读岗'}[user.role] }}）
        <button class="btn ghost sm" @click="logout">退出</button>
      </div>
    </div>
    <div class="layout">
      <div class="sidebar">
        <button class="nav-item" :class="{active:s.tab==='orders' && !s.openOrderId}" @click="s.tab='orders';s.openOrderId=null">订单列表</button>
        <button v-if="['admin','reception'].includes(user.role)" class="nav-item" :class="{active:s.tab==='receive'}" @click="s.tab='receive';s.openOrderId=null">收件建档</button>
        <button v-if="['admin','reception','handler'].includes(user.role)" class="nav-item" :class="{active:s.tab==='sms'}" @click="s.tab='sms';s.openOrderId=null">短信记录</button>
      </div>
      <div class="content">
        <OrderDetail v-if="s.openOrderId" :order-id="s.openOrderId" :user="user" @back="s.openOrderId=null" />
        <ReceivePage v-else-if="s.tab==='receive'" @open-order="(id)=>{s.openOrderId=id}" />
        <SmsPage v-else-if="s.tab==='sms'" />
        <OrderList v-else @open="(id)=>s.openOrderId=id" />
      </div>
    </div>
  </template>`,
};

createApp(App).mount("#app");
