// Reference implementation of digital_twin_visualization_api.md for three.js (r150+).
// Framework-agnostic: no UI, no network, no render loop of its own. Adapt freely to the host application.
//
//   const layer = new DigitalTwinFaultLayer({ root: gltf.scene, camera, controls,
//                                             faultRegistry, componentRegistry, matrix });
//   layer.setFault({ faultId: 'MISFIRE', cylinder: 3, alertLevel: 'ORANGE' });
//   ...in the host render loop: layer.update(deltaSeconds);
import * as THREE from 'three';

const TAU = Math.PI * 2;
const hash01 = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

export class DigitalTwinFaultLayer extends EventTarget {
  constructor({ root, camera = null, controls = null, faultRegistry, componentRegistry, matrix, options = {} }) {
    super();
    this.root = root;
    this.camera = camera;
    this.controls = controls;
    this.faults = new Map(faultRegistry.faults.map((f) => [f.faultId, f]));
    this.renderStates = new Map(faultRegistry.componentRenderStates.map((s) => [s.state, s]));
    this.modifiers = new Map(faultRegistry.renderModifiers.map((m) => [m.modifier, m]));
    this.levelToState = faultRegistry.alertLevelToFaultVisualState;
    this.matrix = matrix;
    this.components = new Map(componentRegistry.components.map((c) => [c.componentId, c]));
    this.options = { enableMicroJitter: false, focusSeconds: 0.8, ...options };

    // --- cached node / mesh references (built once) -------------------------------------------
    this.nodes = new Map();
    root.traverse((o) => { const id = o.userData && o.userData.registry_id; if (id) this.nodes.set(id, o); });
    this.missingComponents = [...this.components.keys()].filter((id) => !this.nodes.has(id));
    this.meshesOf = new Map();
    for (const [id, node] of this.nodes) {
      const list = [];
      node.traverse((o) => {
        if (!o.isMesh) return;
        let owner = o;                                   // nearest registered ancestor (or self)
        while (owner && !(owner.userData && owner.userData.registry_id)) owner = owner.parent;
        const isGroup = this.components.get(id)?.nodeType === 'GROUP';
        if (owner === node || isGroup) list.push(o);
      });
      this.meshesOf.set(id, list);
      for (const m of list) if (!m.userData.__dtBase) m.userData.__dtBase = m.material;
    }

    this.groupOf = new Map();        // part componentId -> group componentId (crankcase halves -> ROTAX_915IS_CRANKCASE)
    for (const c of this.components.values()) {
      if (c.nodeType === 'GROUP') for (const child of c.highlightTargets || []) this.groupOf.set(child, c.componentId);
    }
    this.sources = new Map();        // componentId -> Map(sourceKey -> {state, level, animation, xray})
    this.effective = new Map();      // componentId -> resolved descriptor
    this.telemetry = new Map();      // channel -> value state
    this.activeFaults = new Map();   // matrix key -> fault event payload
    this.recovering = new Map();     // componentId -> expiry time (s)
    this.ghosted = new Set();
    this.variants = new Map();       // cache key -> material
    this.pulsing = new Set();        // variant materials that need per-frame updates
    this.time = 0;
    this.focusTween = null;
  }

  // ============================================================================ faults
  resolveFault({ faultId, cylinder = null, channel = null, magnitude = null }) {
    const entry = this.matrix.faults[faultId];
    if (!entry) throw new Error(`unknown faultId ${faultId}`);
    let key;
    if (entry.scope === 'PER_CYLINDER') {
      key = cylinder == null ? String(entry.nullCylinder.resolvesTo) : String(cylinder);   // null: 'ALL' or the code default
    } else key = entry.scope === 'INSTRUMENT' ? channel : 'ENGINE';
    let resolved = entry.resolved[key];
    if (!resolved) throw new Error(`${faultId}: no mapping for ${entry.scope === 'PER_CYLINDER' ? 'cylinder' : 'channel'} ${key}`);
    const prog = entry.progression;
    if (prog && magnitude != null && magnitude > prog.magnitudeThreshold && key !== 'ALL') {
      const partner = entry.resolved[String(prog.partnerCylinder[key])];
      const direct = [...new Set([...resolved.directComponents, ...partner.directComponents])];
      const context = [...new Set([...resolved.contextComponents, ...partner.contextComponents])].filter((i) => !direct.includes(i));
      const details = [...resolved.componentDetails, ...partner.componentDetails]
        .filter((d, i, arr) => arr.findIndex((x) => x.componentId === d.componentId) === i)
        .map((d) => ({ ...d, role: direct.includes(d.componentId) ? 'direct' : 'context' }));
      resolved = { ...resolved, key: `${resolved.key}+${prog.partnerCylinder[key]}`, progressedTo: prog.partnerCylinder[key],
                   directComponents: direct, contextComponents: context, componentDetails: details,
                   telemetry: { primary: [...new Set([...resolved.telemetry.primary, ...partner.telemetry.primary])],
                                context: [...new Set([...resolved.telemetry.context, ...partner.telemetry.context])] } };
    }
    return { entry, resolved };
  }

  buildFaultEvent(fault, event = 'FAULT_ACTIVATED') {
    const { entry, resolved } = this.resolveFault(fault);
    const def = this.faults.get(fault.faultId);
    const level = fault.alertLevel || fault.severity || def.defaultAlertLevel;
    const payload = {
      event, faultId: fault.faultId, key: resolved.key, scope: entry.scope,
      cylinder: fault.cylinder ?? null, resolvedCylinders: resolved.cylinder != null ? [resolved.cylinder, ...(resolved.progressedTo ? [resolved.progressedTo] : [])]
        : (entry.scope === 'PER_CYLINDER' ? [1, 2, 3, 4] : []),
      magnitude: fault.magnitude ?? null, channel: fault.channel ?? null,
      severity: level, faultState: fault.faultState || (fault.faultId === 'SENSOR_DRIFT' ? (fault.valueState || 'SUSPECT') : this.levelToState[level]),
      ruleId: fault.ruleId ?? null,
      directComponents: resolved.directComponents, contextComponents: resolved.contextComponents,
      telemetry: [...new Set([...resolved.telemetry.primary, ...resolved.telemetry.context])],
      telemetryStates: fault.faultId === 'SENSOR_DRIFT'
        ? Object.fromEntries(resolved.telemetry.primary.map((c) => [c, fault.valueState || 'SUSPECT'])) : {},
      animation: entry.animation, camera: resolved.camera, timestamp: fault.timestamp ?? Date.now() / 1000,
    };
    return payload;
  }

  setFault(fault) {
    const payload = this.buildFaultEvent(fault);
    const { resolved } = this.resolveFault(fault);
    const src = `fault:${resolved.key}`;
    const directState = payload.faultState === 'CRITICAL' ? 'HIGHLIGHT_CRITICAL'
      : payload.faultState === 'SUSPECT' ? 'HIGHLIGHT_SUSPECT'
      : payload.faultState === 'INVALID' ? 'HIGHLIGHT_INVALID' : 'HIGHLIGHT_WARNING';
    for (const d of resolved.componentDetails) {
      const state = d.role === 'direct' ? directState : 'HIGHLIGHT_CONTEXT';
      this.#addSource(d.componentId, src, { state, level: payload.severity, animation: d.role === 'direct' ? payload.animation : 'NONE' });
      this.recovering.delete(d.componentId);
    }
    for (const [ch, st] of Object.entries(payload.telemetryStates)) this.setTelemetryState(ch, st, { emitInstrument: false });
    this.activeFaults.set(resolved.key, payload);
    this.#flush();
    this.#emit('FAULT_ACTIVATED', payload);
    return payload;
  }

  clearFault(faultId, { cylinder = null, channel = null, recover = true } = {}) {
    const keys = [...this.activeFaults.keys()].filter((k) => k === faultId || k.startsWith(`${faultId}#`));
    const target = keys.filter((k) => {
      const p = this.activeFaults.get(k);
      return (cylinder == null || p.cylinder === cylinder) && (channel == null || p.channel === channel);
    });
    const cleared = [];
    for (const k of target) {
      const p = this.activeFaults.get(k);
      for (const id of [...p.directComponents, ...p.contextComponents]) this.#removeSource(id, `fault:${k}`);
      if (recover) {
        const decay = this.renderStates.get('HIGHLIGHT_RECOVERING').decaySeconds ?? 3;
        for (const id of p.directComponents) {
          this.#addSource(id, 'recovering', { state: 'HIGHLIGHT_RECOVERING', animation: 'NONE' });
          this.recovering.set(id, this.time + decay);
        }
      }
      for (const ch of Object.keys(p.telemetryStates)) this.setTelemetryState(ch, 'VALID', { emitInstrument: false });
      this.activeFaults.delete(k);
      const ev = { ...p, event: 'FAULT_CLEARED', faultState: recover ? 'RECOVERING' : 'HEALTHY', timestamp: Date.now() / 1000 };
      cleared.push(ev);
    }
    this.#flush();
    for (const ev of cleared) this.#emit('FAULT_CLEARED', ev);
    return cleared;
  }

  clearAll() {
    for (const k of [...this.activeFaults.keys()]) this.clearFault(k.split('#')[0], { recover: false });
    this.recovering.clear();
    for (const id of [...this.sources.keys()]) this.clearComponentState(id, { all: true });
    this.clearFocus();
  }

  // ============================================================================ components
  setComponentState(componentId, state, { level = null, xray = false, source = 'manual', animation = 'PULSE_STEADY' } = {}) {
    if (!this.renderStates.has(state)) throw new Error(`unknown render state ${state}`);
    this.#addSource(componentId, source, { state, level, xray, animation });
    this.#flush();
  }

  clearComponentState(componentId, { source = 'manual', all = false } = {}) {
    const m = this.sources.get(componentId);
    if (!m) return;
    if (all) { this.sources.delete(componentId); this.recovering.delete(componentId); }
    else this.#removeSource(componentId, source);
    this.#flush();
  }

  getComponentState(componentId) {
    return this.effective.get(componentId)?.state || 'NORMAL';
  }

  selectAt(ndcX, ndcY, raycaster = new THREE.Raycaster()) {
    raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), this.camera);
    const hit = raycaster.intersectObject(this.root, true)[0];
    let o = hit ? hit.object : null;
    while (o && !(o.userData && o.userData.registry_id)) o = o.parent;
    const id = o ? (o.userData.selection_resolves_to || o.userData.registry_id) : null;
    const c = id ? this.components.get(id) : null;
    this.#emit('COMPONENT_SELECTED', {
      event: 'COMPONENT_SELECTED', componentId: id, pickedObject: o ? o.userData.registry_id : null,
      displayName: c?.displayName ?? null, subsystem: c?.subsystem ?? null,
      renderState: id ? this.getComponentState(id) : null,
      activeFaults: id ? [...this.activeFaults.values()].filter((p) => p.directComponents.includes(id) || p.contextComponents.includes(id)).map((p) => p.key) : [],
      timestamp: Date.now() / 1000,
    });
    return id;
  }

  // ============================================================================ telemetry
  setTelemetryState(channel, state, { emitInstrument = true } = {}) {
    const prev = this.telemetry.get(channel) || 'VALID';
    this.telemetry.set(channel, state);
    if (emitInstrument) {
      // instrument geometry follows its channel's data-quality state; STALE never highlights hardware
      for (const [id, c] of this.components) {
        if (!c.instrument || !c.instrument.channels.includes(channel)) continue;
        const src = `telemetry:${channel}`;
        if (state === 'SUSPECT') this.#addSource(id, src, { state: 'HIGHLIGHT_SUSPECT', animation: 'PULSE_STEADY' });
        else if (state === 'INVALID') this.#addSource(id, src, { state: 'HIGHLIGHT_INVALID', animation: 'NONE' });
        else this.#removeSource(id, src);
      }
      this.#flush();
    }
    if (prev !== state) this.#emit('TELEMETRY_STATE_CHANGED', { event: 'TELEMETRY_STATE_CHANGED', channel, previous: prev, state, timestamp: Date.now() / 1000 });
  }

  // ============================================================================ focus
  focusComponent(componentId, { direction = null, distanceFactor = 3.2, minDistance = 0.45, ghost = false } = {}) {
    return this.#focus([componentId], { direction, distanceFactor, minDistance, ghostKeep: ghost ? [componentId] : null, xray: [] });
  }

  focusFault(faultId, { cylinder = null, channel = null, magnitude = null, ghost = null } = {}) {
    const { resolved } = this.resolveFault({ faultId, cylinder, channel, magnitude });
    const cam = resolved.camera;
    const useGhost = ghost ?? cam.ghostNonInvolved;
    const keep = useGhost ? [...resolved.directComponents, ...resolved.contextComponents] : null;
    const frame = resolved.progressedTo ? resolved.directComponents.concat(resolved.contextComponents.filter((i) => i.includes('CYLINDER_HEAD')))
      : (cam.frameComponents && cam.frameComponents.length ? cam.frameComponents : ['ROTAX_915IS_CRANKCASE']);
    return this.#focus(frame, { direction: cam.viewDirectionGltf, distanceFactor: cam.distanceFactor ?? 3.2,
                                minDistance: cam.minDistanceM ?? 0.45, ghostKeep: keep, xray: useGhost ? cam.xray || [] : [] });
  }

  clearFocus() {
    this.ghosted.clear();
    for (const [id, m] of this.sources) if (m.has('focus:xray')) this.#removeSource(id, 'focus:xray');
    this.#flush();
  }

  // ============================================================================ per-frame
  update(dt) {
    this.time += dt;
    let dirty = false;
    for (const [id, until] of this.recovering) {
      if (this.time >= until) { this.recovering.delete(id); this.#removeSource(id, 'recovering'); dirty = true; }
    }
    if (dirty) this.#flush();
    for (const mat of this.pulsing) {             // only the few materials that are currently pulsing
      const p = mat.userData.__dtPulse;
      let amp = p.amplitude;
      const beat = Math.floor(this.time * p.hz);
      if (p.animation === 'PULSE_INTERMITTENT' && hash01(beat) < 0.3) amp = 0;
      if (p.animation === 'PULSE_IRREGULAR') amp *= 0.6 + 0.8 * hash01(beat);
      mat.emissiveIntensity = p.base * (1 + amp * Math.sin(TAU * p.hz * this.time));
    }
    if (this.options.enableMicroJitter) this.#jitter();
    if (this.focusTween && this.camera) {
      const t = Math.min(1, (this.time - this.focusTween.t0) / this.options.focusSeconds);
      const e = t * t * (3 - 2 * t);
      this.camera.position.lerpVectors(this.focusTween.fromPos, this.focusTween.toPos, e);
      if (this.controls) this.controls.target.lerpVectors(this.focusTween.fromTarget, this.focusTween.toTarget, e);
      else this.camera.lookAt(this.focusTween.toTarget);
      if (t >= 1) this.focusTween = null;
    }
  }

  dispose() {
    for (const list of this.meshesOf.values()) for (const m of list) m.material = m.userData.__dtBase;
    for (const v of this.variants.values()) v.dispose();
    this.variants.clear(); this.pulsing.clear();
  }

  // ============================================================================ internals
  #addSource(id, src, desc) {
    if (!this.nodes.has(id)) throw new Error(`unknown componentId ${id}`);
    if (!this.sources.has(id)) this.sources.set(id, new Map());
    this.sources.get(id).set(src, desc);
  }

  #removeSource(id, src) {
    const m = this.sources.get(id);
    if (!m) return;
    m.delete(src);
    if (!m.size) this.sources.delete(id);
  }

  #resolve(id) {
    const m = this.sources.get(id);
    const g = this.groupOf.has(id) ? this.sources.get(this.groupOf.get(id)) : null;
    let best = null;
    for (const src of [m, g]) {
      if (!src) continue;
      for (const d of src.values()) {
        if (d.state === undefined) continue;
        const rank = this.renderStates.get(d.state).precedence;
        if (!best || rank > best.rank || (rank === best.rank && (d.level === 'ORANGE') && best.level !== 'ORANGE')) best = { ...d, rank };
      }
    }
    const xray = !!(m && m.has('focus:xray'));
    const ghost = this.ghosted.size > 0 && !this.ghosted.has(id) && !best;
    return { state: best ? best.state : 'NORMAL', level: best?.level ?? null, animation: best?.animation ?? 'NONE', xray, ghost };
  }

  #flush() {
    this.pulsing.clear();
    for (const id of this.nodes.keys()) {
      const r = this.#resolve(id);
      const prev = this.effective.get(id);
      const same = prev && prev.state === r.state && prev.level === r.level && prev.xray === r.xray && prev.ghost === r.ghost && prev.animation === r.animation;
      if (!same) {
        this.effective.set(id, r);
        if (this.components.get(id)?.nodeType !== 'GROUP') {
          for (const mesh of this.meshesOf.get(id)) mesh.material = this.#variant(mesh.userData.__dtBase, r);
        }
        if (!prev || prev.state !== r.state) {
          this.#emit('COMPONENT_STATE_CHANGED', { event: 'COMPONENT_STATE_CHANGED', componentId: id, previous: prev ? prev.state : 'NORMAL',
                                                  state: r.state, level: r.level, xray: r.xray, ghosted: r.ghost, timestamp: Date.now() / 1000 });
        }
      }
      for (const mesh of this.meshesOf.get(id)) if (mesh.material.userData.__dtPulse) this.pulsing.add(mesh.material);
    }
  }

  #variant(base, r) {
    if (r.state === 'NORMAL' && !r.xray && !r.ghost) return base;
    const key = `${base.uuid}|${r.state}|${r.level}|${r.animation}|${r.xray}|${r.ghost}`;
    let v = this.variants.get(key);
    if (v) return v;
    v = base.clone();
    if (r.state !== 'NORMAL') {
      const spec = this.renderStates.get(r.state);
      const colour = new THREE.Color(spec.emissive);
      v.color.lerp(colour, spec.baseColorTint ?? 0);
      v.emissive = colour.clone();
      const base_ = typeof spec.emissiveIntensity === 'object' ? (spec.emissiveIntensity[r.level] ?? spec.emissiveIntensity.ORANGE) : spec.emissiveIntensity;
      v.emissiveIntensity = base_;
      if (spec.pulse && r.animation !== 'NONE' && r.animation !== 'MICRO_JITTER_LOCAL') {
        v.userData.__dtPulse = { base: base_, hz: spec.pulse.hz, amplitude: spec.pulse.amplitude, animation: r.animation };
      }
    }
    const mod = r.ghost ? this.modifiers.get('GHOSTED') : r.xray ? this.modifiers.get('XRAY') : null;
    if (mod) { v.transparent = true; v.opacity = mod.opacity; v.depthWrite = !!mod.depthWrite; }
    v.name = `${base.name}__${r.state}${r.xray ? '_XRAY' : ''}${r.ghost ? '_GHOST' : ''}`;
    this.variants.set(key, v);
    return v;
  }

  #focus(ids, { direction, distanceFactor, minDistance, ghostKeep, xray }) {
    const box = new THREE.Box3();
    for (const id of ids) { const n = this.nodes.get(id); if (n) box.expandByObject(n); }
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.06);
    const dir = direction ? new THREE.Vector3(...direction).normalize()
      : (this.camera ? this.camera.position.clone().sub(centre).normalize() : new THREE.Vector3(0.6, 0.5, 0.6).normalize());
    const toPos = centre.clone().add(dir.multiplyScalar(Math.max(radius * distanceFactor, minDistance)));
    this.ghosted = new Set(ghostKeep || []);
    for (const [id, m] of this.sources) if (m.has('focus:xray')) this.#removeSource(id, 'focus:xray');
    for (const id of xray) this.#addSource(id, 'focus:xray', {});
    this.#flush();
    if (this.camera) {
      this.focusTween = { t0: this.time, fromPos: this.camera.position.clone(), toPos,
                          fromTarget: this.controls ? this.controls.target.clone() : centre.clone(), toTarget: centre };
    }
    return { centre: centre.toArray(), radius, position: toPos.toArray() };
  }

  #jitter() {
    const amp = 0.0003;
    for (const [id, r] of this.effective) {
      if (r.animation !== 'MICRO_JITTER_LOCAL' || r.state === 'NORMAL') continue;
      const node = this.nodes.get(id);
      if (!node || node.isMesh) continue;              // only multi-primitive groups: child offsets never fight the explode mixer
      for (const child of node.children) if (child.isMesh) child.position.set((Math.random() - 0.5) * amp, (Math.random() - 0.5) * amp, (Math.random() - 0.5) * amp);
    }
  }

  #emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}
