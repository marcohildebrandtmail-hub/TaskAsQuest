class TaskAsQuestPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) this._load();
  }

  connectedCallback() {
    this.innerHTML = `<style>
      :host { display:block; max-width:1180px; margin:0 auto; padding:28px 24px 48px; color:var(--primary-text-color); }
      .hero { display:flex; justify-content:space-between; align-items:end; gap:16px; margin-bottom:24px; }
      h1 { font-size:32px; margin:0; letter-spacing:-.7px; } .sub { color:var(--secondary-text-color); margin:6px 0 0; }
      .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-bottom:24px; }
      .stat, .rule, .quest { background:var(--card-background-color); border-radius:16px; box-shadow:var(--ha-card-box-shadow, 0 2px 8px #0002); padding:18px; }
      .number { display:block; font-size:30px; font-weight:700; margin-top:6px; } .label { color:var(--secondary-text-color); font-size:13px; }
      .section { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:30px 0 12px; } h2 { margin:0; font-size:20px; }
      .rules, .quests { display:grid; gap:12px; } .rule { display:grid; grid-template-columns:1fr auto; align-items:center; gap:16px; border-left:4px solid var(--primary-color); }
      .rule.off { opacity:.58; border-left-color:var(--disabled-text-color); } .title { font-weight:650; font-size:17px; } .meta { color:var(--secondary-text-color); font-size:14px; margin-top:5px; }
      button { border:0; border-radius:9px; background:var(--primary-color); color:var(--text-primary-color); padding:9px 14px; cursor:pointer; font:inherit; }
      button.quiet { background:transparent; color:var(--primary-color); } button.danger { color:var(--error-color); }
      .actions { display:flex; gap:4px; align-items:center; } .quest { display:flex; justify-content:space-between; gap:12px; } .empty { padding:24px; text-align:center; color:var(--secondary-text-color); border:1px dashed var(--divider-color); border-radius:14px; }
      .overlay { position:fixed; z-index:10; inset:0; background:#0008; display:grid; place-items:center; padding:16px; } .dialog { width:min(560px,100%); background:var(--card-background-color); border-radius:18px; padding:24px; box-sizing:border-box; } .dialog h2 { margin-bottom:18px; } .form { display:grid; grid-template-columns:1fr 1fr; gap:14px; } label { display:grid; gap:6px; font-size:13px; color:var(--secondary-text-color); } label.wide { grid-column:1/-1; } input, select { box-sizing:border-box; width:100%; padding:10px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font:inherit; } .dialog-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:22px; }
      @media(max-width:650px) { :host { padding:20px 16px; } .stats { grid-template-columns:1fr; } .hero { align-items:start; flex-direction:column; } .rule { grid-template-columns:1fr; } }
    </style><div id="app"><div class="empty">Task as Quest wird geladen …</div></div>`;
  }

  async _load() {
    this._loaded = true;
    try { this._data = await this._hass.callApi("GET", "taskasquest/dashboard"); this._render(); }
    catch (err) { this._error = err?.message || "Die Übersicht konnte nicht geladen werden."; this._render(); }
  }

  _esc(value) { const d=document.createElement("div"); d.textContent=String(value ?? ""); return d.innerHTML; }
  _condition(rule) { return {below:"kleiner als",above:"größer als",equals:"gleich",not_equals:"ungleich"}[rule.condition] || rule.condition; }

  _render() {
    const app=this.querySelector("#app"); if (!app) return;
    if (this._error) { app.innerHTML=`<div class="empty">${this._esc(this._error)}</div>`; return; }
    const entries=this._data?.entries || []; const rules=entries.flatMap(e => (e.rules||[]).map(r=>({...r,entry_id:e.entry_id}))); const tasks=entries.flatMap(e=>e.open_tasks||[]);
    const active=rules.filter(r=>r.enabled!==false).length; const total=entries.reduce((n,e)=>n+(e.tasks_created_total||0),0);
    app.innerHTML=`<div class="hero"><div><h1>Task as Quest</h1><p class="sub">Deine Automationen und offenen Quests auf einen Blick.</p></div><button id="refresh">Aktualisieren</button></div>
      <div class="stats"><div class="stat"><span class="label">Aktive Regeln</span><span class="number">${active}</span></div><div class="stat"><span class="label">Offene Quests</span><span class="number">${tasks.length}</span></div><div class="stat"><span class="label">Automatisch erstellt</span><span class="number">${total}</span></div></div>
      <div class="section"><h2>Aktivierte Automationen</h2><button id="add">+ Regel hinzufügen</button></div><div class="rules">${rules.length ? rules.map(r=>this._rule(r)).join("") : '<div class="empty">Noch keine Regel eingerichtet. Erstelle deine erste Quest-Automation.</div>'}</div>`;
    app.querySelector("#refresh").onclick=()=>this._reload(); app.querySelector("#add").onclick=()=>this._openEditor();
    app.querySelectorAll("[data-toggle]").forEach(b=>b.onclick=()=>this._toggle(b.dataset.entry,b.dataset.toggle,b.dataset.enabled!=="true"));
    app.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>this._openEditor(JSON.parse(decodeURIComponent(b.dataset.edit))));
    app.querySelectorAll("[data-delete]").forEach(b=>b.onclick=()=>this._delete(b.dataset.entry,b.dataset.delete));
  }

  _rule(r) { const encoded=encodeURIComponent(JSON.stringify(r)); const on=r.enabled!==false; return `<div class="rule ${on?'':'off'}"><div><div class="title">${this._esc(r.task_title)}</div><div class="meta">${this._esc(r.entity_id)} ist ${this._condition(r)} ${this._esc(r.value)} · ${this._esc(r.difficulty)} · ${r.cooldown} Min. Cooldown</div></div><div class="actions"><button class="quiet" data-toggle="${r.id}" data-entry="${r.entry_id}" data-enabled="${on}">${on?'Aktiv':'Pausiert'}</button><button class="quiet" data-edit="${encoded}">Bearbeiten</button><button class="quiet danger" data-delete="${r.id}" data-entry="${r.entry_id}">Löschen</button></div></div>`; }
  async _request(payload) { await this._hass.callApi("POST","taskasquest/dashboard",payload); await this._reload(); }
  async _reload() { this._loaded=false; await this._load(); }
  _toggle(entry_id,id,enabled) { return this._request({action:"toggle",entry_id,id,enabled}); }
  _delete(entry_id,id) { if(confirm("Diese Regel wirklich löschen?")) return this._request({action:"delete",entry_id,id}); }
  _openEditor(rule={}) {
    const entry_id=rule.entry_id || this._data?.entries?.[0]?.entry_id; if(!entry_id) return;
    const comps=this._data?.entries?.[0]?.companions||{}; const compItems=Object.entries(comps);
    const field=(label,name,value,wide=false,req=true)=>`<label class="${wide?'wide':''}">${label}<input name="${name}" value="${this._esc(value)}" ${req?'required':''}></label>`;
    const choices=(name,value,items)=>`<label>${name}<select name="${name}">${items.map(([v,l])=>`<option value="${v}" ${value===v?'selected':''}>${l}</option>`).join("")}</select></label>`;
    const multiChoices=(label,name,values,items)=>`<label class="wide">${label}<select name="${name}" multiple size="${Math.min(items.length||2, 5)}">${items.map(([v,l])=>`<option value="${v}" ${values.includes(v)?'selected':''}>${this._esc(l)}</option>`).join("")}</select><small style="color:var(--secondary-text-color)">Mehrere auswählen mit Strg/Cmd</small></label>`;
    const assigneesField=compItems.length ? multiChoices("Allianz (Gefährten)", "assignees", rule.assignees||[], compItems) : field("Allianz / Spieler-IDs (kommagetrennt)","assignees",(rule.assignees||[]).join(", "),true,false);
    const overlay=document.createElement("div"); overlay.className="overlay";
    overlay.innerHTML=`<form class="dialog"><h2>${rule.id?'Regel bearbeiten':'Neue Automation'}</h2><div class="form">${field("Quest-Titel","task_title",rule.task_title||"",true)}${field("Home-Assistant-Entität","entity_id",rule.entity_id||"",true)}${choices("condition",rule.condition||"equals",[["equals","Gleich"],["not_equals","Ungleich"],["below","Kleiner als"],["above","Größer als"]])}${field("Auslösewert","value",rule.value||"")}${choices("difficulty",rule.difficulty||"medium",[["easy","Leicht"],["medium","Mittel"],["hard","Schwer"],["epic","Episch"]])}${field("Cooldown (Minuten)","cooldown",rule.cooldown??1440)}${choices("trigger_mode",rule.trigger_mode||"edge",[["edge","Nur bei Änderung"],["level","Wiederholen"]])}${assigneesField}<label class="wide"><input type="checkbox" name="enabled" ${rule.enabled!==false?'checked':''}> Regel aktiviert</label></div><div class="dialog-actions"><button type="button" class="quiet">Abbrechen</button><button type="submit">Speichern</button></div></form>`;
    overlay.querySelector("button[type=button]").onclick=()=>overlay.remove(); overlay.onclick=e=>{if(e.target===overlay) overlay.remove();};
    overlay.querySelector("form").onsubmit=e=>{e.preventDefault(); const values=new FormData(e.currentTarget); const assigneesData=values.getAll("assignees"); const parsedAssignees=assigneesData.length===1&&typeof assigneesData[0]==="string"&&assigneesData[0].includes(",")?assigneesData[0].split(",").map(s=>s.trim()).filter(Boolean):assigneesData.filter(Boolean); const updated={...rule,entity_id:values.get("entity_id"),task_title:values.get("task_title"),value:values.get("value"),condition:values.get("condition"),difficulty:values.get("difficulty"),cooldown:Number(values.get("cooldown")),trigger_mode:values.get("trigger_mode"),assignees:parsedAssignees,enabled:values.get("enabled") === "on",notify_app:rule.notify_app!==false}; overlay.remove(); this._request({action:rule.id?"update":"create",entry_id,rule:updated});};
    this.querySelector("#app").append(overlay);
  }
}
customElements.define("taskasquest-panel", TaskAsQuestPanel);
