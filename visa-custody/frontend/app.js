/* 签证材料原件托管与领回系统 —— 前端单页应用（Vue 3，本地化运行） */
const { createApp } = Vue;

const STATUS_LABEL = {
  received: "在旅行社（已收件）",
  submitted: "在使馆·外部办理中",
  returned: "已退件·待领回",
  delivering: "配送中",
  signed: "已签收",
};
const ROLE_LABEL = { admin: "管理员", staff: "经手岗位", courier: "配送员" };

// ---- HTTP 客户端 ----------------------------------------------------------
const api = {
  token: localStorage.getItem("vcd_token") || "",
  user: JSON.parse(localStorage.getItem("vcd_user") || "null"),
  setSession(token, user) {
    this.token = token; this.user = user;
    localStorage.setItem("vcd_token", token);
    localStorage.setItem("vcd_user", JSON.stringify(user));
  },
  clear() {
    this.token = ""; this.user = null;
    localStorage.removeItem("vcd_token");
    localStorage.removeItem("vcd_user");
  },
  async req(method, url, body, isForm = false) {
    const headers = {};
    if (this.token) headers.Authorization = "Bearer " + this.token;
    let payload = null;
    if (body !== undefined && body !== null) {
      if (isForm) { payload = body; }
      else { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    }
    const res = await fetch(url, { method, headers, body: payload });
    const ct = res.headers.get("content-type") || "";
    if (!res.ok) {
      let detail = `请求失败（${res.status}）`;
      if (ct.includes("application/json")) {
        const data = await res.json().catch(() => null);
        if (data) detail = typeof data.detail === "string" ? data.detail
          : JSON.stringify(data.detail);
      }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (ct.includes("application/json")) return res.json();
    return res;
  },
  get(u) { return this.req("GET", u); },
  post(u, b) { return this.req("POST", u, b || {}); },
  postForm(u, fd) { return this.req("POST", u, fd, true); },
  async blob(u) {
    const res = await fetch(u, { headers: { Authorization: "Bearer " + this.token } });
    if (!res.ok) throw new Error("图片加载失败 " + res.status);
    return res.blob();
  },
};

createApp({
  data() {
    return {
      tab: "orders",
      loginForm: { username: "zhang", password: "zhang123" },
      loginErr: "",
      loading: false,
      toast: { kind: "", msg: "" },
      // 数据
      orders: [],
      customers: [],
      smsLogs: [],
      detail: null,
      selected: [],
      receipts: [],
      photoUrls: {},            // materialId -> objectURL
      agentPhotoUrls: {},       // authId -> objectURL
      // 弹窗
      modal: null,              // submit|return|deliver|pickup|sign|receive|newOrder|newAuth
      form: {},
      // 客户自助查询
      trackForm: { order_no: "", phone: "" },
      trackResult: null,
    };
  },
  computed: {
    loggedIn() { return !!api.token && !!api.user; },
    user() { return api.user; },
    role() { return api.user ? api.user.role : ""; },
    canEdit() { return this.role === "admin" || this.role === "staff"; },
    canSign() { return ["admin", "staff", "courier"].includes(this.role); },
    canViewPhoto() { return this.detail ? this.detail.can_view_photo : false; },
    selectedMats() {
      if (!this.detail) return [];
      return this.detail.materials.filter(m => this.selected.includes(m.id));
    },
    allChecked() {
      return !!(this.detail && this.detail.materials.length > 0
        && this.selected.length === this.detail.materials.length);
    },
  },
  methods: {
    roleLabel(r) { return ROLE_LABEL[r] || r; },
    fmt(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      return d.toLocaleString("zh-CN", { hour12: false });
    },
    showToast(kind, msg) {
      this.toast = { kind, msg };
      setTimeout(() => (this.toast.msg = ""), 4200);
    },

    // ---- 认证 ----
    async login() {
      this.loginErr = "";
      try {
        const r = await api.post("/api/auth/login", this.loginForm);
        api.setSession(r.token, r.user);
        this.tab = "orders";
        await this.loadOrders();
      } catch (e) { this.loginErr = e.message; }
    },
    logout() {
      api.clear();
      this.detail = null; this.orders = [];
    },

    // ---- 列表 ----
    async loadOrders() {
      this.orders = await api.get("/api/orders");
    },
    async loadCustomers() {
      this.customers = await api.get("/api/customers");
    },
    async loadSms() {
      this.smsLogs = await api.get("/api/sms-logs");
    },
    async switchTab(t) {
      this.tab = t;
      try {
        if (t === "orders") await this.loadOrders();
        if (t === "customers") await this.loadCustomers();
        if (t === "sms") await this.loadSms();
      } catch (e) { this.showToast("err", e.message); }
    },

    // ---- 新建订单/客户 ----
    openNewOrder() {
      this.form = { customer_id: this.customers[0] ? this.customers[0].id : null, embassy: "" };
      this.modal = "newOrder";
    },
    async submitNewOrder() {
      if (!this.form.customer_id || !this.form.embassy.trim()) {
        return this.showToast("err", "请选择客户并填写使馆");
      }
      try {
        const o = await api.post("/api/orders", this.form);
        this.close(); await this.loadOrders();
        this.showToast("ok", `订单 ${o.order_no} 已建立`);
        this.openDetail(o.id);
      } catch (e) { this.showToast("err", e.message); }
    },
    async submitNewCustomer() {
      try {
        await api.post("/api/customers", this.form);
        this.close(); await this.loadCustomers();
        this.showToast("ok", "客户已建档，归属当前经手岗位");
      } catch (e) { this.showToast("err", e.message); }
    },

    // ---- 订单详情 ----
    async openDetail(id) {
      this.detail = null; this.selected = [];
      this.revokePhotos();
      try {
        this.detail = await api.get(`/api/orders/${id}`);
        if (this.detail.can_view_photo) this.loadPhotos();
        this.loadReceipts(id);
        this.tab = "detail";
      } catch (e) { this.showToast("err", e.message); }
    },
    back() { this.revokePhotos(); this.detail = null; this.tab = "orders"; },
    async refreshDetail() {
      if (!this.detail) return;
      const id = this.detail.order.id;
      this.revokePhotos();
      this.detail = await api.get(`/api/orders/${id}`);
      if (this.detail.can_view_photo) this.loadPhotos();
      await this.loadReceipts(id);
    },
    async loadReceipts(id) {
      try { this.receipts = await api.get(`/api/orders/${id}/receipts`); }
      catch { this.receipts = []; }
    },

    // 证件照片：带鉴权头拉取为 blob，避免令牌进入 URL；按权限决定是否加载
    async loadPhotos() {
      for (const m of this.detail.materials) {
        if (!m.has_photo) continue;
        try {
          const blob = await api.blob(`/api/photos/material/${m.id}`);
          this.photoUrls[m.id] = URL.createObjectURL(blob);
        } catch { /* 无权限或缺失时不展示 */ }
      }
      for (const a of this.detail.authorizations) {
        if (!a.has_id_photo) continue;
        try {
          const blob = await api.blob(`/api/photos/authorization/${a.id}`);
          this.agentPhotoUrls[a.id] = URL.createObjectURL(blob);
        } catch { /* ignore */ }
      }
    },
    revokePhotos() {
      Object.values(this.photoUrls).forEach(u => URL.revokeObjectURL(u));
      Object.values(this.agentPhotoUrls).forEach(u => URL.revokeObjectURL(u));
      this.photoUrls = {}; this.agentPhotoUrls = {};
    },

    // ---- 选择 ----
    toggleAll(e) {
      if (e.target.checked) this.selected = this.detail.materials.map(m => m.id);
      else this.selected = [];
    },
    selCount(status) {
      return this.selectedMats.filter(m => m.status === status).length;
    },

    // ---- 交接操作 ----
    openAction(kind) {
      if (!this.selected.length) return this.showToast("err", "请先勾选要操作的材料");
      this.form = { note: "", courier_name: "", receiver_kind: "customer",
        receiver_name: this.detail.order.customer_name, receiver_id_no: "", sign: "" };
      this.modal = kind;
    },
    actionTitle() {
      return {
        submit: "递交使馆", embassy_return: "登记使馆退件",
        deliver: "交配送员送达", self_pickup: "改为客户自取", sign: "办理按件签收",
      }[this.modal] || "";
    },
    async runAction() {
      const kind = this.modal;
      const ids = [...this.selected];
      const url = `/api/orders/${this.detail.order.id}/` +
        { submit: "submit", embassy_return: "return", deliver: "deliver",
          self_pickup: "self-pickup", sign: "sign" }[kind];
      let body;
      if (kind === "deliver") body = { material_ids: ids, courier_name: this.form.courier_name, note: this.form.note };
      else if (kind === "sign") body = {
        material_ids: ids, receiver_kind: this.form.receiver_kind,
        receiver_name: this.form.receiver_name, receiver_id_no: this.form.receiver_id_no,
        sign: this.form.sign, note: this.form.note,
      };
      else body = { material_ids: ids, note: this.form.note };
      try {
        const r = await api.post(url, body);
        this.close(); this.selected = [];
        await this.refreshDetail();
        if (kind === "sign") {
          this.showToast("ok", r.order_completed
            ? `已签收 ${r.signed} 件，全部材料到齐，订单自动完成`
            : `已签收 ${r.signed} 件（仍有材料未归还，订单保持办理中）`);
        } else if (kind === "submit") {
          this.showToast("ok", `已递交，使馆回执号：${r.embassy_receipt_no}`);
        } else if (kind === "embassy_return") {
          this.showToast("ok", r.still_in_embassy.length
            ? `已退回 ${r.returned} 件；${r.still_in_embassy.length} 件仍在使馆办理中`
            : `已退回 ${r.returned} 件`);
        } else {
          this.showToast("ok", "操作成功，已追加交接记录");
        }
      } catch (e) { this.showToast("err", e.message); }
    },

    async notifyReceipt() {
      try {
        const r = await api.post(`/api/orders/${this.detail.order.id}/notify-receipt`);
        this.showToast("ok", r.message);
      } catch (e) { this.showToast("err", e.message); }
    },
    async forceComplete() {
      try {
        const r = await api.post(`/api/orders/${this.detail.order.id}/complete`);
        await this.refreshDetail();
        this.showToast("ok", r.message);
      } catch (e) {
        this.showToast("err", "整单完成被拒绝：" + e.message);
      }
    },

    // ---- 收件 ----
    openReceive() { this.form = { material_type: "", description: "", file: null }; this.modal = "receive"; },
    onFile(e) { this.form.file = e.target.files[0] || null; },
    async submitReceive() {
      if (!this.form.material_type.trim()) return this.showToast("err", "请填写材料名称");
      if (!this.form.file) return this.showToast("err", "请为该原件拍照并上传");
      const fd = new FormData();
      fd.append("material_type", this.form.material_type);
      fd.append("description", this.form.description || "");
      fd.append("photo", this.form.file);
      try {
        await api.postForm(`/api/orders/${this.detail.order.id}/materials`, fd);
        this.close(); await this.refreshDetail();
        this.showToast("ok", "已编号拍照入库，收件记录不可修改");
      } catch (e) { this.showToast("err", e.message); }
    },

    // ---- 代领授权 ----
    openNewAuth() {
      const now = new Date(); const until = new Date(Date.now() + 30 * 864e5);
      this.form = {
        agent_name: "", agent_id_no: "",
        valid_from: this.dtl(now), valid_until: this.dtl(until),
      };
      this.modal = "newAuth";
    },
    dtl(d) {
      const p = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    },
    async submitNewAuth() {
      try {
        await api.post(`/api/orders/${this.detail.order.id}/authorizations`, {
          agent_name: this.form.agent_name,
          agent_id_no: this.form.agent_id_no,
          valid_from: new Date(this.form.valid_from).toISOString(),
          valid_until: new Date(this.form.valid_until).toISOString(),
        });
        this.close(); await this.refreshDetail();
        this.showToast("ok", "代领授权已登记");
      } catch (e) { this.showToast("err", e.message); }
    },
    async revokeAuth(a) {
      const reason = prompt("撤销原因（可留空）：", "");
      if (reason === null) return;
      try {
        await api.post(`/api/orders/${this.detail.order.id}/authorizations/${a.id}/revoke`, { reason });
        await this.refreshDetail();
        this.showToast("ok", "授权已撤销");
      } catch (e) { this.showToast("err", e.message); }
    },
    async uploadAgentPhoto(e, a) {
      const file = e.target.files[0];
      if (!file) return;
      const fd = new FormData(); fd.append("photo", file);
      try {
        await api.postForm(
          `/api/orders/${this.detail.order.id}/authorizations/${a.id}/id-photo`, fd);
        await this.refreshDetail();
        this.showToast("ok", "代领人证件照已上传");
      } catch (err) { this.showToast("err", err.message); }
    },

    // ---- 客户自助查询 ----
    async track() {
      this.trackResult = null;
      try {
        this.trackResult = await api.post("/api/public/track", this.trackForm);
      } catch (e) { this.showToast("err", e.message); }
    },

    close() { this.modal = null; this.form = {}; },
  },
  async mounted() {
    if (this.loggedIn) { try { await this.loadOrders(); } catch {} }
  },
  template: `
  <div>
    <!-- 未登录：登录 + 客户自助查询 -->
    <div v-if="!loggedIn" class="login-wrap">
      <div class="panel login-card">
        <div class="brand"><span class="logo">签</span>签证材料原件托管系统</div>

        <div v-if="tab==='track'" class="panel" style="box-shadow:none;border:none;padding:0">
          <h2>客户自助查询</h2>
          <div class="sub">凭订单号与预留手机号，查询每件材料当前位置（不显示证件照片）。</div>
          <label class="field">订单号<input v-model="trackForm.order_no" placeholder="如 V20261005-0001"></label>
          <label class="field" style="margin-top:10px">预留手机号<input v-model="trackForm.phone" placeholder="收件时预留的手机号"></label>
          <button class="btn" style="margin-top:14px;width:100%" @click="track">查询</button>
          <div v-if="trackResult" class="mt">
            <div class="kv">
              <dt>订单</dt><dd class="mono">{{ trackResult.order_no }}</dd>
              <dt>使馆</dt><dd>{{ trackResult.embassy }}</dd>
            </div>
            <table style="margin-top:10px">
              <thead><tr><th>编号</th><th>材料</th><th>当前位置</th><th>最新交接</th></tr></thead>
              <tbody>
                <tr v-for="m in trackResult.materials" :key="m.material_no">
                  <td class="mono">{{ m.material_no }}</td>
                  <td>{{ m.material_type }}</td>
                  <td><span class="badge" :class="m.status"><span class="dot"></span>{{ m.status_label }}</span></td>
                  <td class="muted">{{ m.last_party }}<div class="tl-time">{{ fmt(m.last_time) }}</div></td>
                </tr>
              </tbody>
            </table>
          </div>
          <button class="btn-link" style="margin-top:14px" @click="tab='login'">返回员工登录</button>
        </div>

        <template v-else>
          <div v-if="loginErr" class="login-err">{{ loginErr }}</div>
          <label class="field">用户名<input v-model="loginForm.username" @keyup.enter="login"></label>
          <label class="field">密码<input type="password" v-model="loginForm.password" @keyup.enter="login"></label>
          <button class="btn" style="width:100%" @click="login">登录</button>
          <button class="btn-link" style="margin-top:12px;width:100%" @click="tab='track'">客户自助查询（无需登录）</button>
          <div class="hint">
            演示账号：<br>
            管理员 <code>admin / admin123</code><br>
            经手人 <code>zhang / zhang123</code>（负责：王芳）<br>
            经手人 <code>li / li123</code>（负责：陈强，验证跨客户隔离）<br>
            配送员 <code>wang / wang123</code>（不可查看证件照片）
          </div>
        </template>
      </div>
    </div>

    <!-- 已登录 -->
    <template v-else>
      <div class="topbar">
        <div class="brand"><span class="logo">签</span>签证材料托管</div>
        <div class="tabs">
          <div v-if="tab!=='detail'" class="tab" :class="{active:tab==='orders'}" @click="switchTab('orders')">订单</div>
          <div v-if="tab!=='detail' && canEdit" class="tab" :class="{active:tab==='customers'}" @click="switchTab('customers')">客户</div>
          <div v-if="tab!=='detail'" class="tab" :class="{active:tab==='sms'}" @click="switchTab('sms')">短信记录</div>
          <div v-if="tab==='detail'" class="tab active" @click="back">‹ 返回订单列表</div>
        </div>
        <div class="who"><b>{{ user.name }}</b> · {{ roleLabel(role) }}</div>
        <button class="btn-link" @click="logout">退出</button>
      </div>

      <div class="wrap">
        <div v-if="toast.msg" class="alert" :class="toast.kind==='err'?'err':'ok'">{{ toast.msg }}</div>

        <!-- 订单列表 -->
        <div v-if="tab==='orders'">
          <div class="panel">
            <div class="row">
              <h2>托管订单</h2>
              <div class="spacer"></div>
              <button v-if="canEdit" class="btn ghost" @click="loadCustomers().then(openNewOrder)">新建订单</button>
              <button class="btn gray" @click="loadOrders">刷新</button>
            </div>
            <div class="sub">整单仅在全部单件签收后才会完成；缺件订单始终保持“办理中”。</div>
            <table>
              <thead><tr><th>订单号</th><th>客户</th><th>使馆</th><th>进度</th><th>在使馆</th><th>状态</th><th></th></tr></thead>
              <tbody>
                <tr v-for="o in orders" :key="o.id" class="clickable" @click="openDetail(o.id)">
                  <td class="mono">{{ o.order_no }}</td>
                  <td>{{ o.customer_name }}<div class="muted" style="font-size:12px">{{ o.customer_phone }}</div></td>
                  <td>{{ o.embassy }}</td>
                  <td>{{ o.signed }} / {{ o.total }} 已签收</td>
                  <td>{{ o.in_external }}</td>
                  <td><span class="badge" :class="o.status"><span class="dot"></span>{{ o.status==='completed'?'已完成':'办理中' }}</span></td>
                  <td class="right"><button class="btn sm ghost" @click.stop="openDetail(o.id)">进入</button></td>
                </tr>
                <tr v-if="!orders.length"><td colspan="7" class="muted">暂无订单</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 客户 -->
        <div v-if="tab==='customers'">
          <div class="panel">
            <div class="row">
              <h2>客户档案</h2>
              <div class="spacer"></div>
              <button class="btn ghost" @click="form={name:'',phone:'',id_doc_no:''};modal='newCustomer'">新建客户</button>
            </div>
            <div class="sub">经手岗位只能查看本岗位名下客户的证件照片；列表信息供内部协作。</div>
            <table>
              <thead><tr><th>姓名</th><th>手机号</th><th>证件号</th><th>经手岗位</th></tr></thead>
              <tbody>
                <tr v-for="c in customers" :key="c.id">
                  <td>{{ c.name }}</td><td>{{ c.phone }}</td><td class="mono">{{ c.id_doc_no }}</td>
                  <td>{{ c.owner_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 短信 -->
        <div v-if="tab==='sms'">
          <div class="panel">
            <h2>模拟短信发送记录</h2>
            <div class="sub">系统不真正发送短信，仅落库并在服务端控制台打印。</div>
            <table>
              <thead><tr><th>时间</th><th>接收手机</th><th>类型</th><th>内容</th></tr></thead>
              <tbody>
                <tr v-for="s in smsLogs" :key="s.id">
                  <td class="muted" style="white-space:nowrap">{{ fmt(s.created_at) }}</td>
                  <td>{{ s.phone }}</td><td>{{ s.kind }}</td><td>{{ s.content }}</td>
                </tr>
                <tr v-if="!smsLogs.length"><td colspan="4" class="muted">暂无短信</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 订单详情 -->
        <div v-if="tab==='detail' && detail" class="grid">
          <div class="panel">
            <div class="row">
              <div>
                <h2 style="font-size:18px">{{ detail.order.embassy }} · 订单 {{ detail.order.order_no }}</h2>
                <div class="muted">客户：{{ detail.order.customer_name }}（{{ detail.order.customer_phone }}） · 建单 {{ fmt(detail.order.created_at) }}</div>
              </div>
              <div class="spacer"></div>
              <span class="badge" :class="detail.order.status"><span class="dot"></span>{{ detail.order.status==='completed'?'整单已完成':'办理中' }}</span>
            </div>
            <div class="stat-row mt">
              <div class="stat"><div class="n">{{ detail.order.total }}</div><div class="l">原件总数</div></div>
              <div class="stat external"><div class="n">{{ detail.order.in_external }}</div><div class="l">仍在使馆</div></div>
              <div class="stat pending"><div class="n">{{ detail.order.total - detail.order.signed }}</div><div class="l">未签收</div></div>
              <div class="stat signed"><div class="n">{{ detail.order.signed }}</div><div class="l">已签收</div></div>
            </div>
            <div class="row">
              <button v-if="canEdit" class="btn ghost" @click="openReceive">＋收件·编号拍照</button>
              <button v-if="canEdit" class="btn gray" @click="notifyReceipt">发送收件凭证短信</button>
              <div class="spacer"></div>
              <button class="btn danger" @click="forceComplete">整单完成（缺件将被拒绝）</button>
            </div>
          </div>

          <!-- 材料与操作 -->
          <div class="panel">
            <div class="row">
              <h2>每件材料 · 当前位置</h2>
              <div class="spacer"></div>
              <label class="muted" style="display:flex;align-items:center;gap:6px">
                <input type="checkbox" :checked="allChecked" @change="toggleAll"> 全选
              </label>
            </div>
            <div class="sub">勾选材料后执行交接；每件材料独立流转，部分退件/分批配送互不影响。
              <span v-if="!canViewPhoto" style="color:var(--danger)"> 当前岗位无权查看证件照片。</span></div>

            <div class="row mt" style="gap:8px">
              <button v-if="canEdit" class="btn sm" @click="openAction('submit')">递交使馆（{{ selCount('received') }}）</button>
              <button v-if="canEdit" class="btn sm gray" @click="openAction('embassy_return')">使馆退件（{{ selCount('submitted') }}）</button>
              <button v-if="canEdit" class="btn sm ghost" @click="openAction('deliver')">安排配送（{{ selCount('returned') }}）</button>
              <button v-if="canEdit" class="btn sm ghost" @click="openAction('self_pickup')">改为自取</button>
              <button v-if="canSign" class="btn sm" style="background:var(--ok);border-color:var(--ok)" @click="openAction('sign')">按件签收</button>
              <span class="muted" style="font-size:12px">（括号内为勾选材料中处于该可操作状态的件数）</span>
            </div>

            <div class="mats mt">
              <div v-for="m in detail.materials" :key="m.id" class="mat-card" :class="{sel:selected.includes(m.id)}">
                <div class="mat-photo">
                  <input type="checkbox" class="mat-check" :value="m.id" v-model="selected">
                  <img v-if="photoUrls[m.id]" :src="photoUrls[m.id]" alt="原件照片">
                  <span v-else>{{ m.has_photo ? '照片无权限' : '无照片' }}</span>
                </div>
                <div class="mat-body">
                  <div class="mat-no">{{ m.material_no }}</div>
                  <div class="mat-type">{{ m.material_type }}</div>
                  <div class="mat-meta">{{ m.description }}</div>
                  <span class="badge" :class="m.status" style="align-self:flex-start"><span class="dot"></span>{{ m.status_label }}</span>
                </div>
              </div>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px" class="auth-tl-grid">
            <!-- 授权与回执 -->
            <div class="panel">
              <h2>代领授权</h2>
              <div class="sub">代领签收时系统强制核验：授权存在、在有效期内、未撤销且代领人身份一致。</div>
              <button v-if="canEdit" class="btn sm ghost" @click="openNewAuth">登记授权</button>
              <table class="mt">
                <tbody>
                  <tr v-for="a in detail.authorizations" :key="a.id">
                    <td>
                      <div><b>{{ a.agent_name }}</b> <span class="mono muted" style="font-size:12px">{{ a.agent_id_no }}</span></div>
                      <div class="muted" style="font-size:12px">有效期 {{ fmt(a.valid_from) }} ～ {{ fmt(a.valid_until) }}</div>
                      <div v-if="a.status==='revoked'" class="muted" style="font-size:12px;color:var(--danger)">已撤销：{{ a.revoke_reason }}</div>
                      <img v-if="agentPhotoUrls[a.id]" :src="agentPhotoUrls[a.id]" style="width:70px;height:48px;object-fit:cover;border-radius:6px;margin-top:4px;border:1px solid var(--line)">
                    </td>
                    <td class="right" style="white-space:nowrap">
                      <span class="badge" :class="a.status"><span class="dot"></span>{{ a.status==='active'?'有效':'已撤销' }}</span>
                      <div style="margin-top:6px;display:flex;gap:6px;justify-content:flex-end">
                        <label v-if="canEdit && a.status==='active'" class="btn sm gray" style="cursor:pointer">
                          证件照<input type="file" accept="image/*" style="display:none" @change="uploadAgentPhoto($event,a)">
                        </label>
                        <button v-if="canEdit && a.status==='active'" class="btn sm danger" @click="revokeAuth(a)">撤销</button>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="!detail.authorizations.length"><td class="muted">暂无授权（本人领回无需授权）</td></tr>
                </tbody>
              </table>

              <h2 class="mt">使馆回执（模拟）</h2>
              <div v-if="receipts.length">
                <div v-for="r in receipts" :key="r.embassy_receipt_no" class="mono" style="font-size:12.5px">
                  {{ r.embassy_receipt_no }} <span class="muted">· {{ fmt(r.created_at) }}</span>
                </div>
              </div>
              <div v-else class="muted">尚未递交，无回执。</div>
            </div>

            <!-- 交接时间线（append-only） -->
            <div class="panel">
              <h2>交接记录（只追加，不可修改）</h2>
              <div class="sub">收件单为最初记录；分批送达、改自取、部分退件均在此追加。</div>
              <ul class="timeline mt">
                <li v-for="h in detail.handovers" :key="h.id"
                    :class="{sign:h.event_type==='sign', submit:h.event_type==='submit', return:h.event_type==='embassy_return'}">
                  <div>
                    <span class="tl-event">{{ h.event_label }}</span>
                    <span class="tl-tag mono">{{ h.material_no || '整单' }}</span>
                    <span v-if="h.embassy_receipt_no" class="tl-tag mono">回执 {{ h.embassy_receipt_no }}</span>
                    <span v-if="h.authorization_id" class="tl-tag">授权 #{{ h.authorization_id }}</span>
                  </div>
                  <div class="tl-sub">{{ h.from_party }} → {{ h.to_party }}
                    <span v-if="h.counterparty_name">· 对方：{{ h.counterparty_name }}</span>
                    <span v-if="h.location"> · {{ h.location }}</span>
                    <span v-if="h.note"> · {{ h.note }}</span>
                  </div>
                  <div v-if="h.counterparty_sign" class="tl-sign">✓ 签收码/签名：{{ h.counterparty_sign }}</div>
                  <div class="tl-time">{{ fmt(h.created_at) }} · 经办：{{ h.actor_name }}</div>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- 弹窗 -->
      <div v-if="modal" class="modal-mask" @click.self="close">
        <div class="panel modal">
          <h3>{{ actionTitle() }}</h3>

          <template v-if="['submit','embassy_return','deliver','self_pickup','sign'].includes(modal)">
            <div class="alert ok" style="background:#f7f9fc;color:var(--ink-soft)">
              将对已勾选的 <b>{{ selected.length }}</b> 件材料执行操作：
              <span v-for="m in selectedMats" :key="m.id" class="tl-tag mono">{{ m.material_no }}</span>
            </div>
          </template>

          <div v-if="modal==='deliver'" class="form-grid">
            <label class="field">配送员姓名<input v-model="form.courier_name" placeholder="如 王勇"></label>
            <label class="field full">备注<input v-model="form.note"></label>
          </div>

          <div v-else-if="modal==='sign'" class="form-grid">
            <label class="field">领回方式
              <select v-model="form.receiver_kind">
                <option value="customer">客户本人</option>
                <option value="agent">代领人（须有效授权）</option>
              </select>
            </label>
            <label class="field">签收人姓名<input v-model="form.receiver_name"></label>
            <label v-if="form.receiver_kind==='agent'" class="field full">代领人证件号（须与授权一致）
              <input v-model="form.receiver_id_no" placeholder="代领人身份证号"></label>
            <label class="field full">按件签收码 / 客户签名<input v-model="form.sign" placeholder="客户按件签收，不可为空"></label>
            <label class="field full">备注<input v-model="form.note"></label>
            <div v-if="form.receiver_kind==='agent'" class="alert err" style="grid-column:1/-1">
              系统将校验该订单存在有效（未撤销、在有效期内、姓名证件号一致）的代领授权，否则禁止签收。
            </div>
          </div>

          <div v-else-if="modal==='submit'||modal==='embassy_return'||modal==='self_pickup'" class="form-grid">
            <label class="field full">备注<input v-model="form.note"
              :placeholder="modal==='embassy_return'?'使馆分批退件，未选材料仍标注在外部办理':''"></label>
          </div>

          <div v-else-if="modal==='receive'" class="form-grid">
            <label class="field">材料名称<input v-model="form.material_type" placeholder="护照 / 户口本 / 在职证明…"></label>
            <label class="field full">描述<input v-model="form.description"></label>
            <label class="field full">原件拍照上传<input type="file" accept="image/*" @change="onFile"></label>
          </div>

          <div v-else-if="modal==='newOrder'" class="form-grid">
            <label class="field">客户
              <select v-model="form.customer_id">
                <option v-for="c in customers" :value="c.id">{{ c.name }}（{{ c.phone }}）</option>
              </select>
            </label>
            <label class="field">驻华使馆<input v-model="form.embassy" placeholder="如 法国驻华使馆"></label>
          </div>

          <div v-else-if="modal==='newCustomer'" class="form-grid">
            <label class="field">姓名<input v-model="form.name"></label>
            <label class="field">手机号<input v-model="form.phone"></label>
            <label class="field full">证件号<input v-model="form.id_doc_no"></label>
          </div>

          <div v-else-if="modal==='newAuth'" class="form-grid">
            <label class="field">代领人姓名<input v-model="form.agent_name"></label>
            <label class="field">代领人证件号<input v-model="form.agent_id_no"></label>
            <label class="field">授权开始<input type="datetime-local" v-model="form.valid_from"></label>
            <label class="field">授权截止<input type="datetime-local" v-model="form.valid_until"></label>
          </div>

          <div class="foot">
            <button class="btn gray" @click="close">取消</button>
            <button v-if="modal==='submit'||modal==='embassy_return'||modal==='deliver'||modal==='self_pickup'||modal==='sign'" class="btn" @click="runAction">确认交接</button>
            <button v-if="modal==='receive'" class="btn" @click="submitReceive">编号入库</button>
            <button v-if="modal==='newOrder'" class="btn" @click="submitNewOrder">建立订单</button>
            <button v-if="modal==='newCustomer'" class="btn" @click="submitNewCustomer">建档</button>
            <button v-if="modal==='newAuth'" class="btn" @click="submitNewAuth">登记授权</button>
          </div>
        </div>
      </div>
    </template>
  </div>
  `,
}).mount("#app");
