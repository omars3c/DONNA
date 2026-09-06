import { useState, useEffect, useRef, useCallback } from "react";

// ─── Data ────────────────────────────────────────────────────────────────────

const BOOT_LINES = [
  "FRYDAY TACTICAL OS v5.1.0 — BOOT SEQUENCE...",
  "Cryptographic handshake: VERIFIED [AES-512]",
  "Satellite uplink: ONLINE [3 NODES]",
  "Biometric auth: OMAR ALKINDI — CONFIRMED",
  "Threat matrix loaded: 847 active signatures",
  "Classification level: TOP SECRET // SCI",
  "All systems nominal. Standing by.",
];

const SYS_METRICS = [
  { key: "CPU",    val: 94,  unit: "%",    warn: 90  },
  { key: "RAM",    val: 72,  unit: "%",    warn: 85  },
  { key: "NET ↑", val: 183, unit: "Mb/s", warn: 500 },
  { key: "NET ↓", val: 16,  unit: "Mb/s", warn: 500 },
  { key: "SIG",   val: 99,  unit: "%",    warn: 70  },
];

const ITINERARY = [
  { time: "06:00", event: "INTEL BRIEF — SITUATION ROOM B",  status: "done",    cls: "S"  },
  { time: "08:30", event: "SATELLITE PASS — SECTOR 7-G",     status: "active",  cls: "TS" },
  { time: "10:15", event: "JOINT STAFF CALL — ENCRYPTED",    status: "pending", cls: "S"  },
  { time: "13:00", event: "ASSET EXTRACTION — WINDOW OPEN",  status: "pending", cls: "TS" },
  { time: "15:30", event: "THREAT ANALYSIS REVIEW",          status: "pending", cls: "U"  },
  { time: "17:00", event: "SITREP TO COMMAND",               status: "pending", cls: "S"  },
];

const ALERTS = [
  { t: "08:14:33", msg: "UAS-7G entered exclusion zone — bearing 042", type: "crit" },
  { t: "08:09:11", msg: "Satellite uplink degraded — restored 4.2s",   type: "warn" },
  { t: "07:55:02", msg: "Authentication token rotated",                 type: "info" },
  { t: "07:31:47", msg: "Anomalous RF signature: sector 7-G",           type: "warn" },
  { t: "07:22:05", msg: "Perimeter sensor grid: nominal",               type: "info" },
];

const DIALOGUE = [
  { from: "sys",  text: "FRYDAY online. All systems nominal. Good morning, Omar. UAS activity detected in sector 7-G — recommend immediate threat assessment." },
  { from: "user", text: "Show me the threat vectors for sector 7-G." },
  { from: "sys",  text: "Two hostile contacts: UAS-7G at bearing 042, range 14.2 km — and UAS-11B at bearing 307, range 32.8 km. Both exhibiting loiter patterns consistent with ISR collection. Probability of hostile intent: 78%. Recommend engagement authorization." },
  { from: "user", text: "What's the extraction window for ALPHA-3?" },
  { from: "sys",  text: "ALPHA-3 extraction window opens at 13:00 local. Route BRAVO-7 is clear. Recommend staging at grid 37S NB 4421 8834 no later than 12:15." },
];

// ─── Fryday Sphere ────────────────────────────────────────────────────────────

type Ripple = { id: number; x: number; y: number; ts: number };

function FridaySphere({ size }: { size: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const ripples = useRef<Ripple[]>([]);
  const rippleId = useRef(0);
  const hovered = useRef(false);
  const mousePos = useRef({ x: 0, y: 0 });
  const frameRef = useRef(0);
  const startT = useRef(performance.now());
  const speaking = useRef(false);
  const speakT = useRef(0);

  const cx = size / 2, cy = size / 2;
  const R = size * 0.36;

  const addRipple = useCallback((x: number, y: number) => {
    ripples.current.push({ id: rippleId.current++, x, y, ts: performance.now() });
    speaking.current = true;
    speakT.current = performance.now();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;

    function draw(now: number) {
      const t = (now - startT.current) / 1000;
      ctx.clearRect(0, 0, size, size);

      const hover = hovered.current;
      const speak = speaking.current && (now - speakT.current) < 2500;
      if (!speak) speaking.current = false;

      // ── Outer ambient glow ──
      const outerGlow = ctx.createRadialGradient(cx, cy, R * 0.8, cx, cy, R * 2.2);
      outerGlow.addColorStop(0, `rgba(212,168,32,${hover ? 0.07 : 0.04})`);
      outerGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = outerGlow;
      ctx.beginPath(); ctx.arc(cx, cy, R * 2.2, 0, Math.PI * 2); ctx.fill();

      // ── Range rings (faint, like radar) ──
      [1.6, 1.3, 1.05].forEach((frac, i) => {
        ctx.beginPath();
        ctx.arc(cx, cy, R * frac, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(200,170,60,${0.04 + i * 0.02})`;
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 6]);
        ctx.stroke();
        ctx.setLineDash([]);
      });

      // ── Sphere base ──
      const baseGrad = ctx.createRadialGradient(
        cx - R * 0.3, cy - R * 0.3, R * 0.1,
        cx, cy, R
      );
      const pulse = Math.sin(t * 1.2) * 0.5 + 0.5;
      const alpha1 = hover ? 0.55 : 0.35 + pulse * 0.06;
      const alpha2 = hover ? 0.28 : 0.18 + pulse * 0.04;
      baseGrad.addColorStop(0,   `rgba(80,64,18,${alpha1})`);
      baseGrad.addColorStop(0.5, `rgba(40,32,8,${alpha2})`);
      baseGrad.addColorStop(1,   `rgba(6,8,9,0.9)`);
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fillStyle = baseGrad;
      ctx.fill();

      // ── Sphere border glow ──
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(212,168,32,${hover ? 0.7 : 0.35 + pulse * 0.15})`;
      ctx.lineWidth = hover ? 1.5 : 1;
      ctx.shadowColor = "#d4a820";
      ctx.shadowBlur = hover ? 18 : 8;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // ── Highlight (specular) ──
      const hiGrad = ctx.createRadialGradient(cx - R*0.35, cy - R*0.38, R*0.02, cx - R*0.2, cy - R*0.28, R*0.55);
      hiGrad.addColorStop(0, "rgba(255,240,180,0.12)");
      hiGrad.addColorStop(1, "rgba(255,240,180,0)");
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fillStyle = hiGrad;
      ctx.fill();

      // ── Rotating orbit rings ──
      const rings = [
        { tilt: 20, speed: 0.4,  color: `rgba(212,168,32,${hover ? 0.55 : 0.32})`, lw: 1.2 },
        { tilt: 70, speed: -0.25,color: `rgba(180,140,20,${hover ? 0.45 : 0.22})`, lw: 0.8 },
        { tilt: 45, speed: 0.18, color: `rgba(200,160,30,${hover ? 0.35 : 0.16})`, lw: 0.6 },
      ];
      rings.forEach(({ tilt, speed, color, lw }) => {
        const ang = t * speed;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(ang);
        ctx.scale(1, Math.sin((tilt * Math.PI) / 180));
        ctx.beginPath();
        ctx.ellipse(0, 0, R * 0.98, R * 0.98, 0, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = lw;
        ctx.shadowColor = "#d4a820";
        ctx.shadowBlur = hover ? 6 : 2;
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.restore();
      });

      // ── Meridian lines (longitude) ──
      for (let i = 0; i < 6; i++) {
        const ang = (i / 6) * Math.PI + t * 0.08;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(ang);
        ctx.beginPath();
        ctx.ellipse(0, 0, R * 0.98, R * 0.15, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(200,170,60,${hover ? 0.12 : 0.06})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
        ctx.restore();
      }

      // ── Latitude lines (parallels) ──
      [-0.5, -0.25, 0, 0.25, 0.5].forEach(lat => {
        const y0 = cy + R * lat;
        const rLat = Math.sqrt(Math.max(0, R * R - (R * lat) * (R * lat)));
        ctx.save();
        ctx.beginPath();
        ctx.ellipse(cx, y0, rLat * 0.98, rLat * 0.15, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(200,170,60,${hover ? 0.1 : 0.05})`;
        ctx.lineWidth = 0.4;
        ctx.stroke();
        ctx.restore();
      });

      // ── Speaking: audio wave bars around equator ──
      if (speak) {
        const age = (now - speakT.current) / 2500;
        const bars = 32;
        for (let i = 0; i < bars; i++) {
          const ang = (i / bars) * Math.PI * 2;
          const wave = Math.abs(Math.sin(t * 6 + i * 0.7)) * (1 - age);
          const h = R * 0.08 * wave + R * 0.02;
          const x1 = cx + R * Math.cos(ang);
          const y1 = cy + R * Math.sin(ang);
          const x2 = cx + (R + h) * Math.cos(ang);
          const y2 = cy + (R + h) * Math.sin(ang);
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.strokeStyle = `rgba(212,168,32,${0.6 * (1 - age)})`;
          ctx.lineWidth = 1.5;
          ctx.shadowColor = "#d4a820";
          ctx.shadowBlur = 4;
          ctx.stroke();
          ctx.shadowBlur = 0;
        }
      }

      // ── Hover: mouse light ──
      if (hover) {
        const mx = mousePos.current.x, my = mousePos.current.y;
        const dist = Math.hypot(mx - cx, my - cy);
        if (dist < R) {
          const lightGrad = ctx.createRadialGradient(mx, my, 0, mx, my, R * 0.5);
          lightGrad.addColorStop(0, "rgba(255,240,160,0.12)");
          lightGrad.addColorStop(1, "rgba(0,0,0,0)");
          ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2);
          ctx.save(); ctx.clip();
          ctx.fillStyle = lightGrad; ctx.fillRect(0, 0, size, size);
          ctx.restore();
        }
      }

      // ── Ripple waves ──
      ripples.current = ripples.current.filter(rp => now - rp.ts < 1200);
      ripples.current.forEach(rp => {
        const age = (now - rp.ts) / 1200;
        const maxR = R * 1.8;
        for (let ring = 0; ring < 3; ring++) {
          const rr = maxR * (age - ring * 0.12);
          if (rr < 0) return;
          ctx.beginPath();
          ctx.arc(cx, cy, rr, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(212,168,32,${Math.max(0, 0.5 - age * 0.5 - ring * 0.12)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });

      // ── Center label ──
      ctx.save();
      ctx.font = `bold ${size * 0.055}px Orbitron, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = `rgba(212,168,32,${hover ? 0.95 : 0.75 + pulse * 0.1})`;
      ctx.shadowColor = "#d4a820";
      ctx.shadowBlur = hover ? 18 : 8;
      ctx.fillText("FRYDAY", cx, cy - size * 0.025);
      ctx.restore();

      ctx.save();
      ctx.font = `${size * 0.028}px JetBrains Mono, monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = `rgba(200,170,60,${speak ? 0.8 : 0.35})`;
      ctx.fillText(speak ? "PROCESSING..." : "TACTICAL AI", cx, cy + size * 0.042);
      ctx.restore();

      frameRef.current = requestAnimationFrame(draw);
    }

    frameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameRef.current);
  }, [size, cx, cy, R]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ cursor: "crosshair" }}
      onMouseEnter={() => { hovered.current = true; }}
      onMouseLeave={() => { hovered.current = false; }}
      onMouseMove={e => {
        const rect = canvasRef.current!.getBoundingClientRect();
        mousePos.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      }}
      onClick={e => {
        const rect = canvasRef.current!.getBoundingClientRect();
        addRipple(e.clientX - rect.left, e.clientY - rect.top);
      }}
    />
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pad(n: number) { return String(n).padStart(2, "0"); }

function StatusDot({ ok = true, blink = false }: { ok?: boolean; blink?: boolean }) {
  return (
    <span className={`inline-block w-1.5 h-1.5 rounded-full flex-none ${blink ? "anim-blink" : ""}`}
      style={{ background: ok ? "#4aaa6a" : "#cc4444", boxShadow: ok ? "0 0 5px #4aaa6a55" : "0 0 5px #cc444455" }} />
  );
}

function ClassBadge({ cls }: { cls: string }) {
  const c = cls === "TS"
    ? "clearance-ts"
    : cls === "S"
    ? "clearance-s"
    : "text-[#4a5a54] border border-[#4a5a54]/30 bg-[#4a5a54]/10";
  return <span className={`font-mono text-[8px] px-1.5 py-0.5 rounded-sm tracking-widest ${c}`}>{cls}</span>;
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [bootIdx, setBootIdx] = useState(0);
  const [booted, setBooted] = useState(false);
  const [time, setTime] = useState(new Date());
  const [bottomTab, setBottomTab] = useState<"command" | "itinerary" | "analytics">("command");
  const [rightTab, setRightTab] = useState<"dialogue" | "operator">("dialogue");
  const [input, setInput] = useState("");
  const [chat, setChat] = useState(DIALOGUE);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const centerRef = useRef<HTMLDivElement>(null);
  const [sphereSize, setSphereSize] = useState(320);

  useEffect(() => {
    if (bootIdx < BOOT_LINES.length) {
      const t = setTimeout(() => setBootIdx(i => i + 1), 310);
      return () => clearTimeout(t);
    } else {
      const t = setTimeout(() => setBooted(true), 500);
      return () => clearTimeout(t);
    }
  }, [bootIdx]);

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  useEffect(() => {
    if (!booted) return;
    const obs = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setSphereSize(Math.min(width, height) * 0.88);
    });
    if (centerRef.current) obs.observe(centerRef.current);
    return () => obs.disconnect();
  }, [booted]);

  function handleSend() {
    const msg = input.trim();
    if (!msg) return;
    setChat(c => [...c, { from: "user", text: msg }]);
    setInput("");
    setTimeout(() => {
      setChat(c => [...c, { from: "sys", text: "Request acknowledged. Running tactical analysis. Stand by for response." }]);
    }, 1000);
  }

  const timeStr = `${pad(time.getHours())}:${pad(time.getMinutes())}:${pad(time.getSeconds())}`;
  const dateStr = time.toLocaleDateString("en-US", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).toUpperCase();

  // ── Boot ──
  if (!booted) {
    return (
      <div className="size-full flex flex-col items-center justify-center tac-grid anim-flicker" style={{ background: "#060809" }}>
        <div className="font-orb text-4xl font-bold tracking-[0.3em] glow-amber txt-amber mb-2">FRYDAY</div>
        <div className="font-mono text-[9px] tracking-[0.4em] txt-dim mb-8">TACTICAL INTELLIGENCE SYSTEM</div>
        <div className="panel w-96 p-5 space-y-1.5">
          <div className="font-mono text-[9px] txt-dim tracking-widest mb-3 border-b pb-2" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
            SYSTEM BOOT LOG
          </div>
          {BOOT_LINES.slice(0, bootIdx).map((line, i) => (
            <div key={i} className="font-mono text-[10px] anim-fade-in flex gap-2"
              style={{ color: i === bootIdx - 1 ? "#d4a820" : "rgba(168,184,176,0.5)" }}>
              <span className="txt-dim">{">"}</span>
              <span>{line}</span>
            </div>
          ))}
          {bootIdx < BOOT_LINES.length && (
            <span className="inline-block w-2 h-3 anim-blink" style={{ background: "#d4a820", marginLeft: 16 }} />
          )}
        </div>
        <div className="mt-5 font-mono text-[9px] txt-dim tracking-[0.3em]">TOP SECRET // SCI // NOFORN</div>
      </div>
    );
  }

  return (
    <div className="size-full flex flex-col tac-grid anim-flicker" style={{ background: "#060809" }}>

      {/* ── TOP BAR ── */}
      <header className="flex-none flex items-center justify-between px-4 h-9 border-b"
        style={{ borderColor: "rgba(200,170,60,0.15)", background: "linear-gradient(90deg,#07090c,#0a0d10,#07090c)" }}>
        <div className="flex items-center gap-4">
          <div className="font-orb font-bold text-sm tracking-[0.25em] txt-amber glow-amber">FRYDAY</div>
          <span className="font-mono text-[8px] txt-dim tracking-widest border-l pl-4" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
            TACTICAL AI v5.1.0
          </span>
          <span className="clearance-ts font-mono text-[8px] px-2 py-0.5 rounded-sm tracking-widest">
            TOP SECRET // SCI
          </span>
        </div>
        <div className="flex items-center gap-5">
          {[
            { lbl: "NEURAL", ok: true },
            { lbl: "SATLINK", ok: true },
            { lbl: "ENCRYPT", ok: true },
            { lbl: "FIREWALL", ok: true },
          ].map(s => (
            <div key={s.lbl} className="flex items-center gap-1.5">
              <StatusDot ok={s.ok} blink={s.ok} />
              <span className="font-mono text-[8px] txt-dim tracking-widest">{s.lbl}</span>
            </div>
          ))}
        </div>
        <div className="text-right">
          <div className="font-orb font-bold text-base tracking-widest txt-amber glow-amber">{timeStr}</div>
          <div className="font-mono text-[8px] txt-dim tracking-widest">{dateStr} · UTC-5</div>
        </div>
      </header>

      {/* ── BODY ── */}
      <div className="flex-1 flex overflow-hidden min-h-0">

        {/* ── LEFT SIDEBAR ── */}
        <aside className="flex-none w-[68px] border-r flex flex-col"
          style={{ borderColor: "rgba(200,170,60,0.1)" }}>
          <div className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
            <div className="font-mono text-[7px] txt-dim tracking-widest mb-2 text-center">SYS</div>
            {SYS_METRICS.map(m => (
              <div key={m.key} className="text-center py-1 border-b" style={{ borderColor: "rgba(200,170,60,0.07)" }}>
                <div className="font-mono text-[7px] txt-dim">{m.key}</div>
                <div className={`font-mono text-[10px] font-medium ${m.val > m.warn ? "txt-red" : "txt-amber"}`}>{m.val}</div>
                <div className="font-mono text-[7px] txt-dim">{m.unit}</div>
              </div>
            ))}
          </div>
          <div className="p-2 border-t text-center" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
            <div className="font-mono text-[7px] txt-dim tracking-widest">AI CORE</div>
            <div className="flex justify-center mt-1"><StatusDot ok blink /></div>
            <div className="font-mono text-[7px] txt-green mt-0.5">ACTIVE</div>
          </div>
        </aside>

        {/* ── CENTER: SPHERE ── */}
        <main className="flex-1 flex flex-col min-w-0">
          {/* Sphere area */}
          <div ref={centerRef} className="flex-1 flex items-center justify-center overflow-hidden relative min-h-0">
            {/* Corner ticks */}
            {[
              "top-2 left-2 border-t border-l",
              "top-2 right-2 border-t border-r",
              "bottom-[52px] left-2 border-b border-l",
              "bottom-[52px] right-2 border-b border-r",
            ].map(cls => (
              <div key={cls} className={`absolute w-4 h-4 ${cls}`}
                style={{ borderColor: "rgba(200,170,60,0.4)" }} />
            ))}
            {/* Coords */}
            <div className="absolute top-3 left-5 font-mono text-[8px] txt-dim">37S NB 4421 8834</div>
            <div className="absolute top-3 right-5 font-mono text-[8px] txt-dim">ALT 3,420 FT · MACH 2.1</div>
            <div className="absolute bottom-[56px] left-5 font-mono text-[8px] txt-dim">LAT 40.7128°N · LON 74.0060°W</div>
            <div className="absolute bottom-[56px] right-5">
              <span className="font-mono text-[8px] txt-red">⚠ 2 HOSTILE CONTACTS ACTIVE</span>
            </div>
            {/* Hint */}
            <div className="absolute bottom-[36px] left-1/2 -translate-x-1/2 font-mono text-[8px] txt-dim tracking-widest opacity-50">
              CLICK TO ACTIVATE · HOVER TO ILLUMINATE
            </div>

            {sphereSize > 0 && <FridaySphere size={sphereSize} />}
          </div>

          {/* ── BOTTOM TABS ── */}
          <div className="flex-none border-t" style={{ borderColor: "rgba(200,170,60,0.12)" }}>
            <div className="flex border-b" style={{ borderColor: "rgba(200,170,60,0.08)" }}>
              {(["command", "itinerary", "analytics"] as const).map(tab => (
                <button key={tab} onClick={() => setBottomTab(tab)}
                  className={`px-5 py-1.5 font-mono text-[9px] tracking-widest transition-colors ${bottomTab === tab ? "tab-active" : "tab-inactive"}`}>
                  {tab.toUpperCase()}
                </button>
              ))}
            </div>
            <div className="px-4 py-2.5" style={{ minHeight: 76 }}>
              {bottomTab === "command" && (
                <div className="flex gap-2 items-center">
                  <span className="font-mono text-[10px] txt-amber">{">"}</span>
                  <input className="tac-input flex-1 px-3 py-1.5 rounded-sm"
                    placeholder="Enter tactical command or query..."
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleSend()}
                  />
                  <button onClick={handleSend}
                    className="px-4 py-1.5 font-orb text-[9px] tracking-widest rounded-sm transition-all hover:brightness-110 active:scale-95"
                    style={{ background: "rgba(200,170,60,0.12)", border: "1px solid rgba(200,170,60,0.35)", color: "#d4a820" }}>
                    TRANSMIT
                  </button>
                  <div className="flex items-center gap-1.5 ml-2">
                    <StatusDot ok blink />
                    <span className="font-mono text-[8px] txt-dim">MIC ACTIVE</span>
                  </div>
                </div>
              )}
              {bottomTab === "itinerary" && (
                <div className="grid grid-cols-3 gap-2">
                  {ITINERARY.map((item, i) => (
                    <div key={i} className="flex items-start gap-2 p-2 rounded-sm"
                      style={{
                        background: item.status === "active" ? "rgba(200,170,60,0.06)" : "transparent",
                        border: `1px solid ${item.status === "active" ? "rgba(200,170,60,0.2)" : "rgba(200,170,60,0.06)"}`,
                      }}>
                      <span className="font-mono text-[9px] txt-amber flex-none">{item.time}</span>
                      <span className="font-mono text-[9px] txt-main flex-1 leading-relaxed">{item.event}</span>
                      <ClassBadge cls={item.cls} />
                    </div>
                  ))}
                </div>
              )}
              {bottomTab === "analytics" && (
                <div className="flex items-end gap-1.5 h-14">
                  {[72,45,88,61,94,53,77,40,85,68,92,55,78,63,89,44,80].map((v, i) => (
                    <div key={i} className="flex-1 rounded-sm"
                      style={{
                        height: `${(v / 100) * 48}px`,
                        background: v > 80 ? "rgba(204,68,68,0.55)" : v > 60 ? "rgba(212,168,32,0.45)" : "rgba(74,170,106,0.35)",
                        border: "1px solid rgba(200,170,60,0.12)",
                        animation: `bar-wave ${0.8 + i * 0.11}s ease-in-out infinite alternate`,
                      }}
                    />
                  ))}
                  <div className="text-right ml-3 flex-none">
                    <div className="font-mono text-[8px] txt-dim">THREAT INDEX</div>
                    <div className="font-orb text-lg txt-red font-bold">74.2</div>
                    <div className="font-mono text-[8px] txt-red">↑ ELEVATED</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </main>

        {/* ── RIGHT PANEL ── */}
        <aside className="flex-none w-[300px] border-l flex flex-col"
          style={{ borderColor: "rgba(200,170,60,0.12)" }}>
          <div className="flex-none flex border-b" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
            {(["dialogue", "operator"] as const).map(tab => (
              <button key={tab} onClick={() => setRightTab(tab)}
                className={`flex-1 py-2 font-mono text-[9px] tracking-widest transition-colors ${rightTab === tab ? "tab-active" : "tab-inactive"}`}>
                {tab === "operator" ? "OPERATOR" : "DIALOGUE"}
              </button>
            ))}
          </div>

          {rightTab === "dialogue" && (
            <>
              <div className="flex-none border-b overflow-y-auto" style={{ borderColor: "rgba(200,170,60,0.08)", maxHeight: 100 }}>
                {ALERTS.map((a, i) => (
                  <div key={i} className="flex gap-2 px-3 py-1.5 border-b items-start" style={{ borderColor: "rgba(200,170,60,0.05)" }}>
                    <span className="font-mono text-[8px] txt-dim flex-none mt-0.5">{a.t}</span>
                    <span className={`font-mono text-[9px] leading-relaxed flex-1 ${a.type === "crit" ? "txt-red" : a.type === "warn" ? "txt-amber" : "txt-dim"}`}>
                      {a.msg}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
                {chat.map((m, i) => (
                  <div key={i} className={`anim-fade-in flex ${m.from === "user" ? "justify-end" : "justify-start"}`}>
                    {m.from === "sys" && (
                      <div className="max-w-[88%]">
                        <div className="font-mono text-[8px] txt-amber mb-1 tracking-widest">FRYDAY</div>
                        <div className="px-3 py-2 rounded-sm text-[11px] leading-relaxed txt-main"
                          style={{ background: "rgba(200,170,60,0.04)", border: "1px solid rgba(200,170,60,0.12)" }}>
                          {m.text}
                        </div>
                      </div>
                    )}
                    {m.from === "user" && (
                      <div className="max-w-[85%]">
                        <div className="font-mono text-[8px] txt-dim mb-1 tracking-widest text-right">OMAR // ALKINDI</div>
                        <div className="px-3 py-2 rounded-sm text-[11px] leading-relaxed"
                          style={{ background: "rgba(74,170,106,0.07)", border: "1px solid rgba(74,170,106,0.2)", color: "#a8d8b8" }}>
                          {m.text}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div className="flex-none border-t px-3 py-2.5 flex gap-2" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
                <input className="tac-input flex-1 px-2.5 py-1.5 rounded-sm text-[11px]"
                  placeholder="Type a command or question..."
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && handleSend()}
                />
                <button onClick={handleSend}
                  className="px-3 py-1.5 font-orb text-[8px] tracking-widest rounded-sm transition-all hover:brightness-110 active:scale-95"
                  style={{ background: "rgba(200,170,60,0.12)", border: "1px solid rgba(200,170,60,0.3)", color: "#d4a820" }}>
                  SEND
                </button>
              </div>
            </>
          )}

          {rightTab === "operator" && (
            <div className="flex-1 overflow-y-auto p-4 space-y-5">
              <div className="flex items-center gap-4 pb-4 border-b" style={{ borderColor: "rgba(200,170,60,0.1)" }}>
                <div className="w-14 h-14 rounded-sm flex items-center justify-center border relative"
                  style={{ borderColor: "rgba(200,170,60,0.3)", background: "rgba(200,170,60,0.06)" }}>
                  <svg className="w-8 h-8" fill="none" stroke="#d4a820" strokeWidth="1.2" viewBox="0 0 24 24">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <div className="absolute bottom-0.5 right-0.5 w-2 h-2 rounded-full anim-blink"
                    style={{ background: "#4aaa6a", boxShadow: "0 0 5px #4aaa6a" }} />
                </div>
                <div>
                  <div className="font-orb font-bold text-sm txt-amber glow-amber tracking-widest">OMAR</div>
                  <div className="font-mono text-[9px] txt-dim tracking-widest">ALKINDI, O.</div>
                  <div className="flex items-center gap-2 mt-1.5">
                    <ClassBadge cls="TS" />
                    <span className="font-mono text-[8px] txt-green">ONLINE</span>
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <div className="font-mono text-[8px] txt-dim tracking-widest mb-2">// IDENTIFICATION</div>
                {[
                  { k: "BADGE NO.", v: "TIS-00742" },
                  { k: "ROLE",      v: "TACTICAL AI OPERATOR" },
                  { k: "UNIT",      v: "JOINT INTEL CMD" },
                  { k: "STATION",   v: "PENTAGON — RING C" },
                  { k: "SESSION",   v: "14:22:41 ELAPSED" },
                ].map(f => (
                  <div key={f.k} className="flex justify-between items-center py-1 border-b" style={{ borderColor: "rgba(200,170,60,0.06)" }}>
                    <span className="font-mono text-[9px] txt-dim">{f.k}</span>
                    <span className="font-mono text-[9px] txt-amber">{f.v}</span>
                  </div>
                ))}
              </div>
              <div className="space-y-2">
                <div className="font-mono text-[8px] txt-dim tracking-widest mb-2">// CLEARANCES</div>
                {[
                  { lbl: "TOP SECRET / SCI",  granted: true  },
                  { lbl: "SIGINT ACCESS",      granted: true  },
                  { lbl: "HUMINT ACCESS",      granted: true  },
                  { lbl: "NUCLEAR AUTH",       granted: false },
                  { lbl: "PRESIDENTIAL BRIEF", granted: false },
                ].map(c => (
                  <div key={c.lbl} className="flex justify-between items-center">
                    <span className="font-mono text-[9px] txt-dim">{c.lbl}</span>
                    <StatusDot ok={c.granted} />
                  </div>
                ))}
              </div>
              <div className="space-y-1.5">
                <div className="font-mono text-[8px] txt-dim tracking-widest mb-2">// RECENT ACTIVITY</div>
                {[
                  "Queried sector 7-G threat vectors",
                  "Accessed ALPHA-3 extraction data",
                  "Reviewed satellite pass schedule",
                ].map((a, i) => (
                  <div key={i} className="font-mono text-[9px] txt-dim py-1 border-b flex gap-2"
                    style={{ borderColor: "rgba(200,170,60,0.05)" }}>
                    <span className="txt-amber">›</span>{a}
                  </div>
                ))}
              </div>
              <button className="w-full py-1.5 font-mono text-[9px] tracking-widest rounded-sm transition-all hover:brightness-110 mt-2"
                style={{ background: "rgba(204,68,68,0.1)", border: "1px solid rgba(204,68,68,0.25)", color: "#cc4444" }}>
                TERMINATE SESSION
              </button>
            </div>
          )}
        </aside>
      </div>

      {/* ── BOTTOM STATUS BAR ── */}
      <footer className="flex-none flex items-center justify-between px-4 h-6 border-t"
        style={{ borderColor: "rgba(200,170,60,0.1)", background: "#07090c" }}>
        <div className="flex items-center gap-5">
          {["JARVIS LINK: ACTIVE", "AES-512: ENGAGED", "PERIMETER: CLEAR"].map(s => (
            <span key={s} className="font-mono text-[8px] txt-dim tracking-widest">{s}</span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <StatusDot ok blink />
          <span className="font-mono text-[8px] txt-dim tracking-widest">FRYDAY TACTICAL — ALL SYSTEMS NOMINAL</span>
        </div>
        <div className="font-mono text-[8px] txt-dim tracking-widest">PENTAGON · RING C · SUBLEVEL 3</div>
      </footer>
    </div>
  );
}
