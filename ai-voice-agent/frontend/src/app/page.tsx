/* eslint-disable @next/next/no-sync-scripts */
"use client";

import { useEffect, useRef, useState } from "react";

type AnalysisItem = { status: string; detail: string };
type InputAnalysis = {
  guardrails: {
    toxicity: AnalysisItem;
    bank_topic: AnalysisItem;
    language: AnalysisItem;
  };
  input_analysis: {
    kyc: AnalysisItem;
    sentiment: AnalysisItem;
    churn: AnalysisItem;
  };
};

type WsMsg =
  | { type: "transcript"; text: string }
  | { type: "tts_begin"; format: "pcm_s16le"; sample_rate: number }
  | { type: "tts_first_token" }
  | { type: "tts_end" }
  | {
      type: "graph_result";
      service_type: string;
      messages: { role: string; content: string }[];
      interrupt?: any;
      analysis?: InputAnalysis;
    }
  | { type: "input_analysis"; analysis: InputAnalysis }
  | { type: "guardrails_available"; available: boolean; fms_guardrails_available?: boolean; nemo_guardrails_available?: boolean }
  | { type: "guardrails_status"; enabled: boolean }
  | { type: "guardrails_mode"; mode: string }
  | { type: "error"; error: string };

function pcmToWavBlob(pcm: Int16Array, sampleRate: number): Blob {
  const numChannels = 1;
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = pcm.byteLength;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);
  new Uint8Array(buffer, 44).set(new Uint8Array(pcm.buffer));
  return new Blob([buffer], { type: "audio/wav" });
}

async function blobToBase64(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function bytesToInt16View(bytes: Uint8Array): Int16Array {
  if (bytes.byteLength % 2 === 0 && bytes.byteOffset % 2 === 0) {
    return new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
  }
  const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  return new Int16Array(buf);
}

// ─── Crinkled Bank Note SVG ──────────────────────────────────────────────────
function TalkingBankNote({ isTalking, className }: { isTalking: boolean; className?: string }) {
  // Crinkled note outline — wavy, slightly rumpled edges like a real bill
  const noteOutline =
    "M 38 42 Q 55 37 110 40 Q 180 33 250 38 Q 320 32 390 37 Q 430 41 445 45" +
    " Q 448 75 450 110 Q 446 145 448 180 Q 450 215 448 250 Q 445 272 440 278" +
    " Q 410 285 340 280 Q 270 287 200 282 Q 130 287 80 282 Q 48 279 42 275" +
    " Q 38 255 36 220 Q 40 185 38 150 Q 36 115 38 80 Z";

  return (
    <svg viewBox="0 0 490 320" className={className} xmlns="http://www.w3.org/2000/svg">
      <defs>
        {/* Paper texture noise */}
        <filter id="paper-grain" x="0%" y="0%" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4" seed="2" result="noise" />
          <feColorMatrix type="saturate" values="0" in="noise" result="grayNoise" />
          <feBlend in="SourceGraphic" in2="grayNoise" mode="multiply" />
        </filter>
        {/* Crinkle fold shadow/highlight strips */}
        <linearGradient id="crinkleV" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#000" stopOpacity="0" />
          <stop offset="18%" stopColor="#000" stopOpacity="0.06" />
          <stop offset="22%" stopColor="#fff" stopOpacity="0.12" />
          <stop offset="26%" stopColor="#000" stopOpacity="0.04" />
          <stop offset="42%" stopColor="#fff" stopOpacity="0.08" />
          <stop offset="46%" stopColor="#000" stopOpacity="0.1" />
          <stop offset="55%" stopColor="#fff" stopOpacity="0.06" />
          <stop offset="62%" stopColor="#000" stopOpacity="0.08" />
          <stop offset="68%" stopColor="#fff" stopOpacity="0.14" />
          <stop offset="72%" stopColor="#000" stopOpacity="0.05" />
          <stop offset="82%" stopColor="#fff" stopOpacity="0.07" />
          <stop offset="88%" stopColor="#000" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#000" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="crinkleH" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#000" stopOpacity="0" />
          <stop offset="20%" stopColor="#000" stopOpacity="0.04" />
          <stop offset="25%" stopColor="#fff" stopOpacity="0.1" />
          <stop offset="35%" stopColor="#000" stopOpacity="0.07" />
          <stop offset="50%" stopColor="#fff" stopOpacity="0.05" />
          <stop offset="60%" stopColor="#000" stopOpacity="0.09" />
          <stop offset="65%" stopColor="#fff" stopOpacity="0.12" />
          <stop offset="75%" stopColor="#000" stopOpacity="0.04" />
          <stop offset="85%" stopColor="#fff" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#000" stopOpacity="0" />
        </linearGradient>
        {/* Soft drop shadow under note */}
        <filter id="note-shadow" x="-8%" y="-8%" width="120%" height="120%">
          <feDropShadow dx="3" dy="5" stdDeviation="6" floodColor="#000" floodOpacity="0.5" />
        </filter>
        {/* Fine engraving line pattern */}
        <pattern id="engrave" x="0" y="0" width="4" height="4" patternUnits="userSpaceOnUse">
          <line x1="0" y1="2" x2="4" y2="2" stroke="#2E6B45" strokeWidth="0.3" opacity="0.3" />
        </pattern>
        {/* Circular guilloché for seal */}
        <pattern id="guilloche" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="2.2" fill="none" stroke="#2E6B45" strokeWidth="0.3" opacity="0.4" />
        </pattern>
      </defs>

      <g className={isTalking ? "banknote-talking" : ""} style={{ transformOrigin: "245px 160px" }}>

        {/* ── Note body with shadow ── */}
        <g filter="url(#note-shadow)">
          <path d={noteOutline} fill="#E8E4D4" stroke="#8B8878" strokeWidth="1.2" />
        </g>

        {/* Paper texture overlay */}
        <path d={noteOutline} fill="#DDD8C4" opacity="0.3" filter="url(#paper-grain)" />

        {/* Engraving line fill */}
        <path d={noteOutline} fill="url(#engrave)" />

        {/* ── Crinkle wrinkle lines ── */}
        <path d="M 130 36 Q 136 110 128 165 Q 135 220 130 284" stroke="#9B9686" strokeWidth="0.6" opacity="0.5" fill="none" />
        <path d="M 205 34 Q 200 130 206 165 Q 200 230 204 282" stroke="#9B9686" strokeWidth="0.4" opacity="0.35" fill="none" />
        <path d="M 330 34 Q 324 120 332 170 Q 326 220 330 280" stroke="#9B9686" strokeWidth="0.6" opacity="0.45" fill="none" />
        <path d="M 400 38 Q 395 145 402 220 Q 397 255 400 278" stroke="#9B9686" strokeWidth="0.4" opacity="0.3" fill="none" />
        <path d="M 38 110 Q 170 105 245 112 Q 340 104 448 110" stroke="#9B9686" strokeWidth="0.5" opacity="0.4" fill="none" />
        <path d="M 36 210 Q 150 216 245 208 Q 350 215 448 212" stroke="#9B9686" strokeWidth="0.5" opacity="0.35" fill="none" />

        {/* Crinkle shadow/highlight overlays */}
        <path d={noteOutline} fill="url(#crinkleV)" />
        <path d={noteOutline} fill="url(#crinkleH)" />

        {/* ── Green inner border (like real US bill) ── */}
        <path
          d="M 55 55 Q 245 50 430 57 Q 435 160 430 268 Q 245 275 55 270 Q 50 160 55 55 Z"
          fill="none" stroke="#2E6B45" strokeWidth="1.8"
        />
        <path
          d="M 59 59 Q 245 54 426 61 Q 431 160 426 264 Q 245 271 59 266 Q 54 160 59 59 Z"
          fill="none" stroke="#2E6B45" strokeWidth="0.6" opacity="0.6"
        />

        {/* ── Header text ── */}
        <text x="245" y="74" textAnchor="middle" fontSize="6.5" fontWeight="600" fill="#2E6B45" fontFamily="serif" letterSpacing="3.5" opacity="0.7">ACME RESERVE NOTE</text>
        <text x="245" y="90" textAnchor="middle" fontSize="12" fontWeight="700" fill="#2E6B45" fontFamily="serif" letterSpacing="2.5">THE ACME BANK OF AMERICA</text>

        {/* ── Left seal ── */}
        <circle cx="105" cy="200" r="26" fill="url(#guilloche)" stroke="#2E6B45" strokeWidth="1.5" />
        <circle cx="105" cy="200" r="22" fill="none" stroke="#2E6B45" strokeWidth="0.8" />
        <circle cx="105" cy="200" r="17" fill="none" stroke="#2E6B45" strokeWidth="0.5" />
        <text x="105" y="197" textAnchor="middle" fontSize="5.5" fontWeight="700" fill="#2E6B45" fontFamily="serif">ACME</text>
        <text x="105" y="206" textAnchor="middle" fontSize="5" fontWeight="600" fill="#2E6B45" fontFamily="serif">BANK</text>

        {/* ── Right seal / treasury ── */}
        <circle cx="390" cy="130" r="24" fill="none" stroke="#2E6B45" strokeWidth="1.5" />
        <circle cx="390" cy="130" r="20" fill="url(#guilloche)" stroke="#2E6B45" strokeWidth="0.8" />
        <text x="390" y="128" textAnchor="middle" fontSize="5.5" fontWeight="700" fill="#2E6B45" fontFamily="serif">DEPT OF</text>
        <text x="390" y="136" textAnchor="middle" fontSize="5.5" fontWeight="700" fill="#2E6B45" fontFamily="serif">TREASURY</text>

        {/* ── Corner denominations ── */}
        <text x="80" y="78" textAnchor="middle" fontSize="24" fontWeight="700" fill="#2E6B45" fontFamily="serif">1</text>
        <text x="410" y="78" textAnchor="middle" fontSize="24" fontWeight="700" fill="#2E6B45" fontFamily="serif">1</text>
        <text x="80" y="264" textAnchor="middle" fontSize="24" fontWeight="700" fill="#2E6B45" fontFamily="serif">1</text>
        <text x="410" y="264" textAnchor="middle" fontSize="24" fontWeight="700" fill="#2E6B45" fontFamily="serif">1</text>

        {/* ── Serial numbers ── */}
        <text x="145" y="115" fontSize="6.5" fontWeight="600" fill="#2E6B45" fontFamily="monospace" letterSpacing="1">D 06E137531 A</text>
        <text x="275" y="245" fontSize="6.5" fontWeight="600" fill="#2E6B45" fontFamily="monospace" letterSpacing="1">D 06E137531 A</text>

        {/* ── District number ── */}
        <circle cx="88" cy="128" r="13" fill="none" stroke="#2E6B45" strokeWidth="1.2" />
        <text x="88" y="133" textAnchor="middle" fontSize="15" fontWeight="700" fill="#2E6B45" fontFamily="serif">12</text>

        {/* ── Central portrait oval ── */}
        <ellipse cx="245" cy="168" rx="58" ry="68" fill="none" stroke="#2E6B45" strokeWidth="1.5" />
        <ellipse cx="245" cy="168" rx="53" ry="63" fill="#E0DCCC" stroke="#2E6B45" strokeWidth="0.8" />
        {/* Engraving texture in portrait */}
        <ellipse cx="245" cy="168" rx="53" ry="63" fill="url(#engrave)" opacity="0.5" />

        {/* ── Doge (Shiba Inu) face ── */}
        <g>
          {/* Head shape — rounded Shiba face */}
          <ellipse cx="245" cy="162" rx="36" ry="38" fill="#D4A44C" stroke="#4A6B52" strokeWidth="0.8" />
          {/* Inner face lighter fur patch */}
          <ellipse cx="245" cy="168" rx="26" ry="28" fill="#ECC872" opacity="0.7" />
          {/* Cheek fur markings */}
          <path d="M 215 155 Q 222 160 218 170" fill="#ECC872" stroke="#4A6B52" strokeWidth="0.3" opacity="0.5" />
          <path d="M 275 155 Q 268 160 272 170" fill="#ECC872" stroke="#4A6B52" strokeWidth="0.3" opacity="0.5" />

          {/* Ears — pointy Shiba ears */}
          <path d="M 218 138 L 208 108 L 230 128 Z" fill="#C49040" stroke="#4A6B52" strokeWidth="0.7" />
          <path d="M 214 132 L 210 114 L 226 126" fill="#E8B860" stroke="none" opacity="0.6" />
          <path d="M 272 138 L 282 108 L 260 128 Z" fill="#C49040" stroke="#4A6B52" strokeWidth="0.7" />
          <path d="M 276 132 L 280 114 L 264 126" fill="#E8B860" stroke="none" opacity="0.6" />

          {/* Fine engraving lines across face */}
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <path key={`fl-${i}`} d={`M ${216 + i * 2} ${140 + i * 2} Q 245 ${145 + i * 1.5} ${274 - i * 2} ${140 + i * 2}`} fill="none" stroke="#7A8B72" strokeWidth="0.25" opacity="0.35" />
          ))}

          {/* Eyes — big round Shiba eyes */}
          <ellipse cx="232" cy="152" rx="8" ry="8.5" fill="#FFF" stroke="#3A5542" strokeWidth="0.8" />
          <ellipse cx="234" cy="154" rx="5" ry="5.5" fill="#1A1A1A" />
          <circle cx="236" cy="150" r="2.5" fill="#FFF" />
          <circle cx="232" cy="156" r="1" fill="#FFF" opacity="0.5" />

          <ellipse cx="258" cy="152" rx="8" ry="8.5" fill="#FFF" stroke="#3A5542" strokeWidth="0.8" />
          <ellipse cx="260" cy="154" rx="5" ry="5.5" fill="#1A1A1A" />
          <circle cx="262" cy="150" r="2.5" fill="#FFF" />
          <circle cx="258" cy="156" r="1" fill="#FFF" opacity="0.5" />

          {/* Eyebrows — expressive Shiba brows */}
          <path d="M 222 143 Q 232 139 242 144" fill="none" stroke="#3A5542" strokeWidth="0.7" />
          <path d="M 248 144 Q 258 139 268 143" fill="none" stroke="#3A5542" strokeWidth="0.7" />

          {/* Nose — big round Shiba nose */}
          <ellipse cx="245" cy="168" rx="7" ry="5" fill="#1A1A1A" stroke="#3A5542" strokeWidth="0.5" />
          <ellipse cx="243" cy="166" rx="2" ry="1.5" fill="#444" opacity="0.5" />

          {/* Nose bridge line */}
          <path d="M 245 163 L 245 168" stroke="#3A5542" strokeWidth="0.4" />

          {/* Whisker dots */}
          <circle cx="228" cy="172" r="0.8" fill="#4A6B52" opacity="0.5" />
          <circle cx="224" cy="175" r="0.8" fill="#4A6B52" opacity="0.5" />
          <circle cx="226" cy="178" r="0.8" fill="#4A6B52" opacity="0.5" />
          <circle cx="262" cy="172" r="0.8" fill="#4A6B52" opacity="0.5" />
          <circle cx="266" cy="175" r="0.8" fill="#4A6B52" opacity="0.5" />
          <circle cx="264" cy="178" r="0.8" fill="#4A6B52" opacity="0.5" />
        </g>

        {/* Mouth — Shiba smile / talking */}
        {isTalking ? (
          <g>
            <ellipse cx="245" cy="180" rx="12" ry="8" fill="#6B3A3A" stroke="#3A5542" strokeWidth="0.8" />
            <path d="M 235 177 Q 245 174 255 177" fill="none" stroke="#3A5542" strokeWidth="0.5" />
            <ellipse cx="245" cy="183" rx="5" ry="2.5" fill="#D46A6A" />
          </g>
        ) : (
          <g>
            {/* Classic Shiba smile — W shape */}
            <path d="M 237 174 Q 241 180 245 174 Q 249 180 253 174" fill="none" stroke="#3A5542" strokeWidth="0.9" strokeLinecap="round" />
            {/* Tongue peeking out */}
            <ellipse cx="245" cy="179" rx="4" ry="3" fill="#D4888B" stroke="#3A5542" strokeWidth="0.4" opacity="0.7" />
          </g>
        )}

        {/* ── Bottom text ── */}
        <text x="245" y="260" textAnchor="middle" fontSize="10" fontWeight="700" fill="#2E6B45" fontFamily="serif" letterSpacing="3.5">ONE DOGE DOLLAR</text>

        {/* ── Signature lines ── */}
        <line x1="108" y1="232" x2="190" y2="232" stroke="#2E6B45" strokeWidth="0.5" />
        <text x="149" y="240" textAnchor="middle" fontSize="4.5" fill="#2E6B45" fontFamily="serif">Secretary of the Treasury</text>
        <path d="M 118 230 Q 130 225 142 230 Q 154 235 166 228 Q 175 224 184 229" fill="none" stroke="#2E6B45" strokeWidth="0.5" opacity="0.7" />

        <line x1="300" y1="232" x2="382" y2="232" stroke="#2E6B45" strokeWidth="0.5" />
        <text x="341" y="240" textAnchor="middle" fontSize="4.5" fill="#2E6B45" fontFamily="serif">Treasurer of Acme Bank</text>
        <path d="M 310 230 Q 322 225 334 229 Q 346 234 358 227 Q 367 223 376 228" fill="none" stroke="#2E6B45" strokeWidth="0.5" opacity="0.7" />

        {/* ── Extra crinkle highlights ── */}
        <path d="M 75 92 Q 105 88 135 95 Q 160 100 190 90" stroke="#FFF" strokeWidth="0.7" opacity="0.18" fill="none" />
        <path d="M 295 220 Q 330 215 365 222 Q 388 226 415 218" stroke="#FFF" strokeWidth="0.6" opacity="0.14" fill="none" />
        <path d="M 50 175 Q 75 170 100 178 Q 125 182 150 173" stroke="#FFF" strokeWidth="0.5" opacity="0.12" fill="none" />
        <path d="M 340 80 Q 365 76 390 84 Q 410 88 425 82" stroke="#FFF" strokeWidth="0.5" opacity="0.1" fill="none" />
      </g>
    </svg>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────────
export default function Home() {
  const [wsUrl, setWsUrl] = useState(() => {
    if (typeof window === "undefined") return "ws://127.0.0.1:8765";
    // In production (served via nginx), proxy through same origin at /ws.
    // In local dev, connect directly to the backend.
    const isLocalDev = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    if (isLocalDev) return "ws://127.0.0.1:8765";
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws`;
  });
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<string>("idle");
  const [transcript, setTranscript] = useState<string>("");
  const [serviceType, setServiceType] = useState<string>("");
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [error, setError] = useState<string>("");
  const [textToSend, setTextToSend] = useState<string>("I'd like to apply for a credit card");
  const [ttsStreamStatus, setTtsStreamStatus] = useState<string>("idle");
  const [ttsStreamChunks, setTtsStreamChunks] = useState<number>(0);
  const [ttsStreamBytes, setTtsStreamBytes] = useState<number>(0);
  const [ttsOutSampleRate, setTtsOutSampleRate] = useState<number>(0);
  const [ttsTtftMs, setTtsTtftMs] = useState<number>(0);
  const [ttsTtfbMs, setTtsTtfbMs] = useState<number>(0);
  const [ttsRecordEnabled, setTtsRecordEnabled] = useState<boolean>(true);
  const [ttsRecordedUrl, setTtsRecordedUrl] = useState<string>("");
  const [ttsRecordedFilename, setTtsRecordedFilename] = useState<string>("");
  const [ttsRecordedSampleRate, setTtsRecordedSampleRate] = useState<number>(0);
  const [ttsRecordedDurationMs, setTtsRecordedDurationMs] = useState<number>(0);
  const [ttsRecordedBytes, setTtsRecordedBytes] = useState<number>(0);
  const [micDevices, setMicDevices] = useState<MediaDeviceInfo[]>([]);
  const [micDeviceId, setMicDeviceId] = useState<string>("default");
  const [controlsOpen, setControlsOpen] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [guardrailsAvailable, setGuardrailsAvailable] = useState(false);
  const [guardrailsEnabled, setGuardrailsEnabled] = useState(false);
  const [fmsAvailable, setFmsAvailable] = useState(false);
  const [nemoAvailable, setNemoAvailable] = useState(false);
  const [guardrailsMode, setGuardrailsMode] = useState<string>("none");
  const [analysis, setAnalysis] = useState<InputAnalysis | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const ttsReceivingBinaryRef = useRef<boolean>(false);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const pcmRef = useRef<Int16Array[]>([]);

  const sampleRate = 16000;

  // ===== Streaming TTS: scheduled AudioBufferSourceNode playback =====
  const ttsCtxRef = useRef<AudioContext | null>(null);
  const ttsSampleRateRef = useRef<number>(24000);
  const ttsNextPlayTimeRef = useRef<number>(0);
  const ttsScheduledSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const ttsPrebufferChunksRef = useRef<ArrayBuffer[]>([]);
  const ttsPrebufferSamplesRef = useRef<number>(0);
  const ttsPrebufferingRef = useRef<boolean>(true);
  const ttsPrebufferMs = 300;

  const ttsReqStartedAtMsRef = useRef<number>(0);
  const ttsFirstTokenAtMsRef = useRef<number>(0);
  const ttsFirstAudioAtMsRef = useRef<number>(0);
  const ttsStreamBytesRef = useRef<number>(0);
  const ttsStreamChunksRef = useRef<number>(0);
  const ttsRxStartedAtMsRef = useRef<number>(0);
  const ttsRxLastAtMsRef = useRef<number>(0);
  const ttsRxInSamplesRef = useRef<number>(0);
  const [ttsGenRealtimeX, setTtsGenRealtimeX] = useState<number>(0);

  // Recording (capture original PCM from model).
  const ttsRecordedBuffersRef = useRef<ArrayBuffer[]>([]);
  const ttsRecordedBytesLenRef = useRef<number>(0);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const ttsStreamStatusRef = useRef<string>("idle");

  const isSpeaking = ttsStreamStatus === "buffering" || ttsStreamStatus === "playing" || ttsStreamStatus === "draining";

  // Auto-scroll conversation
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, waiting]);

  // ─── TTS Playback (AudioBufferSourceNode scheduling) ──────────────
  const ensureTtsContext = async (): Promise<AudioContext> => {
    if (ttsCtxRef.current && ttsCtxRef.current.state !== "closed") {
      if (ttsCtxRef.current.state === "suspended") {
        await ttsCtxRef.current.resume();
      }
      return ttsCtxRef.current;
    }
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    ttsCtxRef.current = ctx;
    setTtsOutSampleRate(ctx.sampleRate);
    return ctx;
  };

  const schedulePcmChunk = (ctx: AudioContext, pcmBuf: ArrayBuffer, inRate: number) => {
    const int16 = new Int16Array(pcmBuf);
    if (int16.length === 0) return;
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }
    const buffer = ctx.createBuffer(1, float32.length, inRate);
    buffer.getChannelData(0).set(float32);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    const now = ctx.currentTime;
    if (ttsNextPlayTimeRef.current < now) {
      ttsNextPlayTimeRef.current = now;
    }
    source.start(ttsNextPlayTimeRef.current);
    ttsScheduledSourcesRef.current.push(source);
    ttsNextPlayTimeRef.current += buffer.duration;
  };

  const flushPrebuffer = (ctx: AudioContext, inRate: number) => {
    for (const chunk of ttsPrebufferChunksRef.current) {
      schedulePcmChunk(ctx, chunk, inRate);
    }
    ttsPrebufferChunksRef.current = [];
    ttsPrebufferSamplesRef.current = 0;
    ttsPrebufferingRef.current = false;
    setTtsStreamStatus("playing");
  };

  const stopTtsStream = (opts?: { resetStats?: boolean }) => {
    // Stop all scheduled sources
    for (const src of ttsScheduledSourcesRef.current) {
      try { src.stop(); } catch {}
    }
    ttsScheduledSourcesRef.current = [];
    ttsNextPlayTimeRef.current = 0;
    ttsPrebufferChunksRef.current = [];
    ttsPrebufferSamplesRef.current = 0;
    ttsPrebufferingRef.current = true;
    ttsReceivingBinaryRef.current = false;
    setTtsStreamStatus("idle");
    setWaiting(false);
  };

  const clearTtsRecording = () => {
    setTtsRecordedUrl("");
    setTtsRecordedFilename("");
    setTtsRecordedSampleRate(0);
    setTtsRecordedDurationMs(0);
    setTtsRecordedBytes(0);
    ttsRecordedBuffersRef.current = [];
    ttsRecordedBytesLenRef.current = 0;
  };

  const finalizeTtsRecording = () => {
    if (!ttsRecordEnabled) return;
    const sr = ttsRecordedSampleRate || ttsSampleRateRef.current;
    if (!sr) return;
    const bufs = ttsRecordedBuffersRef.current;
    const totalBytes = ttsRecordedBytesLenRef.current;
    if (!bufs.length || !totalBytes) return;
    const joinedBytes = new Uint8Array(totalBytes);
    let offB = 0;
    for (const b of bufs) {
      joinedBytes.set(new Uint8Array(b), offB);
      offB += b.byteLength;
    }
    const evenLen = joinedBytes.length - (joinedBytes.length % 2);
    const i16 = bytesToInt16View(joinedBytes.subarray(0, evenLen));
    const wav = pcmToWavBlob(i16, sr);
    const durationMs = (i16.length / sr) * 1000;
    const url = URL.createObjectURL(wav);
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    setTtsRecordedUrl(url);
    setTtsRecordedFilename(`tts-stream-${ts}.wav`);
    setTtsRecordedBytes(wav.size);
    setTtsRecordedDurationMs(durationMs);
  };

  useEffect(() => {
    ttsStreamStatusRef.current = ttsStreamStatus;
  }, [ttsStreamStatus]);

  // Revoke old recorded URLs to avoid leaks.
  const prevTtsRecordedUrlRef = useRef<string>("");
  useEffect(() => {
    const prev = prevTtsRecordedUrlRef.current;
    if (prev && prev !== ttsRecordedUrl) URL.revokeObjectURL(prev);
    prevTtsRecordedUrlRef.current = ttsRecordedUrl;
    return () => {
      if (ttsRecordedUrl) URL.revokeObjectURL(ttsRecordedUrl);
    };
  }, [ttsRecordedUrl]);

  // Generation speed stats (updated on interval).
  useEffect(() => {
    const id = window.setInterval(() => {
      setTtsStreamBytes(ttsStreamBytesRef.current);
      setTtsStreamChunks(ttsStreamChunksRef.current);
      if (
        ttsStreamStatusRef.current !== "idle" &&
        ttsRxStartedAtMsRef.current > 0 &&
        ttsRxLastAtMsRef.current >= ttsRxStartedAtMsRef.current &&
        ttsSampleRateRef.current > 0
      ) {
        const elapsedS = Math.max(
          0.001,
          (ttsRxLastAtMsRef.current - ttsRxStartedAtMsRef.current) / 1000
        );
        const audioS = ttsRxInSamplesRef.current / ttsSampleRateRef.current;
        setTtsGenRealtimeX(audioS / elapsedS);
      }
    }, 200);
    return () => window.clearInterval(id);
  }, []);

  // ─── WebSocket ────────────────────────────────────────────────────
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef<number>(1000);
  const shouldReconnectRef = useRef<boolean>(true);

  const scheduleReconnect = () => {
    if (!shouldReconnectRef.current) return;
    if (reconnectTimerRef.current) return;
    const delay = reconnectDelayRef.current;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connect();
    }, delay);
    // Exponential backoff capped at 10s
    reconnectDelayRef.current = Math.min(delay * 2, 10000);
  };

  const connect = () => {
    setError("");
    shouldReconnectRef.current = true;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      wsRef.current = ws;
      setConnected(true);
      setStatus("connected");
      reconnectDelayRef.current = 1000; // reset backoff on success
    };
    ws.onclose = () => {
      setConnected(false);
      setStatus("disconnected");
      wsRef.current = null;
      scheduleReconnect();
    };
    ws.onerror = () => setError("WebSocket error");
    ws.onmessage = async (evt) => {
      try {
        // ── Binary frames: TTS audio chunks ──
        if (typeof evt.data !== "string") {
          if (!ttsReceivingBinaryRef.current) return;
          const handleBuffer = async (buf: ArrayBuffer) => {
            const len = buf.byteLength;
            if (!len) return;
            ttsStreamBytesRef.current += len;
            ttsStreamChunksRef.current += 1;
            ttsRxLastAtMsRef.current = Date.now();
            if (ttsFirstAudioAtMsRef.current === 0) {
              ttsFirstAudioAtMsRef.current = ttsRxLastAtMsRef.current;
              if (ttsReqStartedAtMsRef.current > 0) {
                setTtsTtfbMs(ttsFirstAudioAtMsRef.current - ttsReqStartedAtMsRef.current);
              }
            }
            const inRate = ttsSampleRateRef.current || 24000;
            const inSamples = Math.floor(len / 2);
            ttsRxInSamplesRef.current += inSamples;

            // Recording
            if (ttsRecordEnabled) {
              ttsRecordedBuffersRef.current.push(buf.slice(0));
              ttsRecordedBytesLenRef.current += buf.byteLength;
            }

            // Schedule playback
            const ctx = ttsCtxRef.current;
            if (!ctx) return;
            if (ctx.state === "suspended") await ctx.resume();

            if (ttsPrebufferingRef.current) {
              ttsPrebufferChunksRef.current.push(buf);
              ttsPrebufferSamplesRef.current += inSamples;
              const prebufferSamples = Math.floor(inRate * ttsPrebufferMs / 1000);
              if (ttsPrebufferSamplesRef.current >= prebufferSamples) {
                flushPrebuffer(ctx, inRate);
              }
            } else {
              schedulePcmChunk(ctx, buf, inRate);
            }
          };

          if (evt.data instanceof ArrayBuffer) {
            void handleBuffer(evt.data);
            return;
          }
          if (evt.data instanceof Blob) {
            void evt.data.arrayBuffer().then((buf) => handleBuffer(buf));
            return;
          }
          return;
        }

        // ── JSON messages ──
        const msg = JSON.parse(evt.data) as WsMsg;
        if (msg.type === "transcript") setTranscript(msg.text);

        if (msg.type === "tts_begin") {
          stopTtsStream();
          ttsSampleRateRef.current = msg.sample_rate;
          ttsReceivingBinaryRef.current = true;
          ttsFirstAudioAtMsRef.current = 0;
          ttsFirstTokenAtMsRef.current = 0;
          setTtsTtftMs(0);
          setTtsTtfbMs(0);
          setTtsStreamStatus("buffering");
          ttsStreamChunksRef.current = 0;
          ttsStreamBytesRef.current = 0;
          ttsRxStartedAtMsRef.current = Date.now();
          ttsRxLastAtMsRef.current = ttsRxStartedAtMsRef.current;
          ttsRxInSamplesRef.current = 0;
          setTtsStreamChunks(0);
          setTtsStreamBytes(0);
          setTtsGenRealtimeX(0);
          if (ttsRecordEnabled) {
            clearTtsRecording();
            setTtsRecordedSampleRate(msg.sample_rate);
          }
          // Ensure AudioContext exists and is running.
          await ensureTtsContext();
        }

        if (msg.type === "tts_first_token") {
          if (ttsFirstTokenAtMsRef.current === 0) {
            ttsFirstTokenAtMsRef.current = Date.now();
            if (ttsReqStartedAtMsRef.current > 0) {
              setTtsTtftMs(ttsFirstTokenAtMsRef.current - ttsReqStartedAtMsRef.current);
            }
          }
        }

        if (msg.type === "tts_end") {
          ttsReceivingBinaryRef.current = false;
          if (ttsReqStartedAtMsRef.current > 0 && ttsFirstTokenAtMsRef.current > 0) {
            setTtsTtftMs(ttsFirstTokenAtMsRef.current - ttsReqStartedAtMsRef.current);
          }
          if (ttsReqStartedAtMsRef.current > 0 && ttsFirstAudioAtMsRef.current > 0) {
            setTtsTtfbMs(ttsFirstAudioAtMsRef.current - ttsReqStartedAtMsRef.current);
          }
          // Flush any remaining prebuffer
          const ctx = ttsCtxRef.current;
          const inRate = ttsSampleRateRef.current || 24000;
          if (ctx && ttsPrebufferingRef.current && ttsPrebufferChunksRef.current.length > 0) {
            flushPrebuffer(ctx, inRate);
          }
          setTtsStreamStatus("draining");
          finalizeTtsRecording();
          // Wait for scheduled audio to finish, then clean up.
          const endTime = ttsNextPlayTimeRef.current;
          const check = setInterval(() => {
            const c = ttsCtxRef.current;
            if (!c || c.currentTime >= endTime) {
              stopTtsStream();
              clearInterval(check);
            }
          }, 200);
        }

        if (msg.type === "input_analysis") {
          setAnalysis(msg.analysis);
        }
        if (msg.type === "graph_result") {
          setServiceType(msg.service_type);
          setMessages(msg.messages);
          if (msg.analysis) setAnalysis(msg.analysis);
        }
        if (msg.type === "guardrails_available") {
          setGuardrailsAvailable(msg.available);
          setFmsAvailable(msg.fms_guardrails_available ?? msg.available);
          setNemoAvailable(msg.nemo_guardrails_available ?? false);
        }
        if (msg.type === "guardrails_status") {
          setGuardrailsEnabled(msg.enabled);
        }
        if (msg.type === "guardrails_mode") {
          setGuardrailsMode(msg.mode);
        }
        if (msg.type === "error") setError(msg.error);
      } catch (e) {
        console.error("WS message handling failed:", e);
      }
    };
  };

  const disconnect = () => {
    shouldReconnectRef.current = false;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  };

  // Auto-connect on mount
  useEffect(() => {
    connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Microphone recording ────────────────────────────────────────
  const startRecording = async () => {
    setError("");
    setTranscript("");
    pcmRef.current = [];
    if (!connected || !wsRef.current) {
      setError("Connect to WS server first.");
      return;
    }
    setStatus("requesting mic\u2026");
    try {
      const constraints: MediaStreamConstraints =
        micDeviceId && micDeviceId !== "default"
          ? { audio: { deviceId: { exact: micDeviceId } } }
          : { audio: true };
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia(constraints);
      } catch (err: any) {
        if (micDeviceId && micDeviceId !== "default") {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          setMicDeviceId("default");
        } else {
          throw err;
        }
      }
      mediaStreamRef.current = stream;
    } catch (e: any) {
      setStatus("mic permission denied");
      setError(e?.message || "Microphone permission denied/unavailable in this browser.");
      return;
    }
    const stream = mediaStreamRef.current!;
    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioCtxRef.current = audioCtx;
    const source = audioCtx.createMediaStreamSource(stream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    processorRef.current = processor;
    source.connect(processor);
    processor.connect(audioCtx.destination);
    setStatus("recording");
    processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      const inRate = e.inputBuffer.sampleRate;
      const ratio = inRate / sampleRate;
      const outLen = Math.floor(input.length / ratio);
      const out = new Int16Array(outLen);
      for (let i = 0; i < outLen; i++) {
        const idx = Math.floor(i * ratio);
        const s = Math.max(-1, Math.min(1, input[idx]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      pcmRef.current.push(out);
    };
  };

  const stopAndSend = async () => {
    setStatus("stopping");
    processorRef.current?.disconnect();
    processorRef.current = null;
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    const chunks = pcmRef.current;
    const total = chunks.reduce((acc, c) => acc + c.length, 0);
    const joined = new Int16Array(total);
    let offset = 0;
    for (const c of chunks) {
      joined.set(c, offset);
      offset += c.length;
    }
    const wav = pcmToWavBlob(joined, sampleRate);
    const b64 = await blobToBase64(wav);
    setStatus("sending");
    setWaiting(true);
    wsRef.current?.send(JSON.stringify({ type: "audio_wav_b64", audio_b64: b64 }));
    setStatus("sent (awaiting response)");
  };

  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close();
      ttsCtxRef.current?.close();
    };
  }, []);

  const toggleGuardrails = () => {
    if (!connected || !wsRef.current) return;
    const newState = !guardrailsEnabled;
    wsRef.current.send(JSON.stringify({ type: "set_guardrails", enabled: newState }));
  };

  const fmsEnabled = guardrailsMode === "fms" || guardrailsMode === "both";
  const nemoEnabled = guardrailsMode === "nemo" || guardrailsMode === "both";
  const anyGuardrailsActive = guardrailsMode !== "none";

  const sendGuardrailsMode = (mode: string) => {
    if (!connected || !wsRef.current) return;
    wsRef.current.send(JSON.stringify({ type: "set_guardrails_mode", mode }));
    setGuardrailsMode(mode);
  };

  const toggleFms = () => {
    const newFms = !fmsEnabled;
    const newMode = newFms
      ? (nemoEnabled ? "both" : "fms")
      : (nemoEnabled ? "nemo" : "none");
    sendGuardrailsMode(newMode);
  };

  const toggleNemo = () => {
    const newNemo = !nemoEnabled;
    const newMode = newNemo
      ? (fmsEnabled ? "both" : "nemo")
      : (fmsEnabled ? "fms" : "none");
    sendGuardrailsMode(newMode);
  };

  const sendText = () => {
    setError("");
    if (!connected || !wsRef.current) {
      setError("Connect to WS server first.");
      return;
    }
    ttsReqStartedAtMsRef.current = Date.now();
    ttsFirstTokenAtMsRef.current = 0;
    ttsFirstAudioAtMsRef.current = 0;
    setTtsTtftMs(0);
    setTtsTtfbMs(0);
    // Prime audio context inside user gesture so playback isn't blocked.
    void ensureTtsContext();
    setWaiting(true);
    wsRef.current.send(JSON.stringify({ type: "text", text: textToSend }));
  };

  const speakStream = () => {
    setError("");
    if (!connected || !wsRef.current) {
      setError("Connect to WS server first.");
      return;
    }
    ttsReqStartedAtMsRef.current = Date.now();
    ttsFirstTokenAtMsRef.current = 0;
    ttsFirstAudioAtMsRef.current = 0;
    setTtsTtftMs(0);
    setTtsTtfbMs(0);
    void ensureTtsContext();
    wsRef.current.send(JSON.stringify({ type: "tts_text", text: textToSend }));
  };

  const sendWavFile = async (file: File) => {
    setError("");
    if (!connected || !wsRef.current) {
      setError("Connect to WS server first.");
      return;
    }
    ttsReqStartedAtMsRef.current = Date.now();
    ttsFirstTokenAtMsRef.current = 0;
    ttsFirstAudioAtMsRef.current = 0;
    setTtsTtftMs(0);
    setTtsTtfbMs(0);
    const b64 = await blobToBase64(file);
    wsRef.current.send(JSON.stringify({ type: "audio_wav_b64", audio_b64: b64 }));
  };

  useEffect(() => {
    const loadDevices = async () => {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        setMicDevices(devices.filter((d) => d.kind === "audioinput"));
      } catch {}
    };
    void loadDevices();
  }, []);

  // Helper: get the last agent message for the speech bubble
  const lastAgentMessage = [...messages].reverse().find(
    (m) => m.role !== "human" && m.role !== "interrupt" && !m.content.startsWith("Routing to")
  );

  // ─── UI ───────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-rh-gray-95 text-rh-gray-10">
      {/* ─── Nav Bar ─────────────────────────────────────────────── */}
      <nav className="flex-none h-14 flex items-center px-6 border-b border-rh-gray-80 bg-rh-gray-95">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <div className="w-5 h-1 bg-rh-red rounded-sm" />
            <div className="w-2 h-2 bg-rh-red rounded-sm" />
          </div>
          <h1 className="text-lg font-bold" style={{ fontFamily: "'Red Hat Display', sans-serif" }}>
            Acme Bank - AI Banking Assistant
          </h1>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs">
            <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-rh-gray-50"}`} />
            <span className="text-rh-gray-40">{connected ? "Connected" : "Disconnected"}</span>
          </div>
          {anyGuardrailsActive && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-rh-red/20 text-rh-red border border-rh-red/30 font-semibold uppercase tracking-wider">
              {guardrailsMode === "both" ? "FMS+NeMo Guardrails" : guardrailsMode === "fms" ? "FMS Guardrails" : "NeMo Guardrails"}
            </span>
          )}
          <button
            onClick={() => setControlsOpen(!controlsOpen)}
            className="text-xs px-3 py-1.5 rounded border border-rh-gray-70 text-rh-gray-40 hover:text-white hover:border-rh-gray-50 transition-colors"
          >
            Controls {controlsOpen ? "\u25B2" : "\u25BC"}
          </button>
        </div>
      </nav>

      {/* ─── Controls Panel (collapsible) ────────────────────────── */}
      {controlsOpen && (
        <div className="flex-none border-b border-rh-gray-80 bg-rh-gray-90 px-6 py-4 animate-fade-in-up">
          <div className={`max-w-5xl mx-auto grid gap-4 ${(fmsAvailable || nemoAvailable) ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
            <div className="space-y-2">
              <label className="text-xs text-rh-gray-40 uppercase tracking-wider font-semibold">WebSocket URL</label>
              <input
                className="w-full rounded bg-rh-gray-95 border border-rh-gray-70 px-3 py-2 text-sm text-white placeholder-rh-gray-50 focus:border-rh-red focus:ring-1 focus:ring-rh-red focus:outline-none"
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  className="rounded bg-rh-red text-white px-3 py-1.5 text-xs font-semibold hover:bg-rh-red-dark disabled:opacity-40 transition-colors"
                  onClick={connect}
                  disabled={connected}
                >
                  Connect
                </button>
                <button
                  className="rounded border border-rh-gray-70 text-rh-gray-40 px-3 py-1.5 text-xs hover:text-white disabled:opacity-40 transition-colors"
                  onClick={disconnect}
                  disabled={!connected}
                >
                  Disconnect
                </button>
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-rh-gray-40 uppercase tracking-wider font-semibold">Microphone</label>
              <select
                className="w-full rounded bg-rh-gray-95 border border-rh-gray-70 px-3 py-2 text-sm text-white focus:border-rh-red focus:outline-none"
                value={micDeviceId}
                onChange={(e) => setMicDeviceId(e.target.value)}
              >
                <option value="default">Default</option>
                {micDevices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || `Mic (${d.deviceId.slice(0, 8)}\u2026)`}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-rh-gray-40 uppercase tracking-wider font-semibold">Quick Test</label>
              <textarea
                className="w-full min-h-[56px] rounded bg-rh-gray-95 border border-rh-gray-70 px-3 py-2 text-sm text-white placeholder-rh-gray-50 focus:border-rh-red focus:outline-none resize-none"
                value={textToSend}
                onChange={(e) => setTextToSend(e.target.value)}
                rows={2}
              />
              <div className="flex gap-2">
                <button
                  className="rounded bg-rh-red text-white px-3 py-1.5 text-xs font-semibold hover:bg-rh-red-dark disabled:opacity-40 transition-colors"
                  onClick={sendText}
                  disabled={!connected}
                >
                  Send Text
                </button>
                <button
                  className="rounded border border-rh-gray-70 text-rh-gray-40 px-3 py-1.5 text-xs hover:text-white disabled:opacity-40 transition-colors"
                  onClick={speakStream}
                  disabled={!connected}
                >
                  TTS Only
                </button>
                <label className="rounded border border-rh-gray-70 text-rh-gray-40 px-3 py-1.5 text-xs hover:text-white cursor-pointer transition-colors">
                  Upload WAV
                  <input
                    type="file"
                    accept="audio/wav"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void sendWavFile(f);
                    }}
                    disabled={!connected}
                  />
                </label>
              </div>
            </div>
            {(fmsAvailable || nemoAvailable) && (
            <div className="space-y-2">
              <label className="text-xs text-rh-gray-40 uppercase tracking-wider font-semibold">Guardrails</label>
              {fmsAvailable && (
              <div className="flex items-center gap-3">
                <button
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-rh-red focus:ring-offset-2 focus:ring-offset-rh-gray-90 disabled:opacity-40 ${
                    fmsEnabled ? "bg-rh-red" : "bg-rh-gray-70"
                  }`}
                  onClick={toggleFms}
                  disabled={!connected}
                  role="switch"
                  aria-checked={fmsEnabled}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                      fmsEnabled ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
                <span className={`text-sm font-medium ${fmsEnabled ? "text-rh-red" : "text-rh-gray-40"}`}>
                  FMS
                </span>
              </div>
              )}
              {nemoAvailable && (
              <div className="flex items-center gap-3">
                <button
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-rh-red focus:ring-offset-2 focus:ring-offset-rh-gray-90 disabled:opacity-40 ${
                    nemoEnabled ? "bg-rh-red" : "bg-rh-gray-70"
                  }`}
                  onClick={toggleNemo}
                  disabled={!connected}
                  role="switch"
                  aria-checked={nemoEnabled}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                      nemoEnabled ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
                <span className={`text-sm font-medium ${nemoEnabled ? "text-rh-red" : "text-rh-gray-40"}`}>
                  NeMo
                </span>
              </div>
              )}
              <p className="text-[10px] text-rh-gray-50">
                {guardrailsMode === "both"
                  ? "FMS + NeMo active"
                  : guardrailsMode === "fms"
                  ? "FMS detectors active (jailbreak, profanity, gibberish)"
                  : guardrailsMode === "nemo"
                  ? "NeMo content safety active"
                  : "Direct LLM access (no content filtering)"}
              </p>
            </div>
            )}
          </div>
          <div className="max-w-5xl mx-auto mt-3 pt-3 border-t border-rh-gray-70">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-rh-gray-40">
              <span>TTS: <span className="text-rh-gray-20">{ttsStreamStatus}</span></span>
              <span>Gen: <span className="text-rh-gray-20">{ttsGenRealtimeX.toFixed(2)}x</span></span>
              <span>TTFT: <span className="text-rh-gray-20">{ttsTtftMs ? `${ttsTtftMs}ms` : "-"}</span></span>
              <span>TTFB: <span className="text-rh-gray-20">{ttsTtfbMs ? `${ttsTtfbMs}ms` : "-"}</span></span>
              <span>Chunks: <span className="text-rh-gray-20">{ttsStreamChunks}</span></span>
              <span>Bytes: <span className="text-rh-gray-20">{ttsStreamBytes}</span></span>
              <span>outHz: <span className="text-rh-gray-20">{ttsOutSampleRate || "-"}</span></span>
              {ttsRecordedUrl && (
                <>
                  <span>Recorded: <span className="text-rh-gray-20">{(ttsRecordedDurationMs / 1000).toFixed(2)}s</span></span>
                  <a href={ttsRecordedUrl} download={ttsRecordedFilename} className="text-rh-red hover:underline">Download WAV</a>
                </>
              )}
              <button onClick={() => stopTtsStream()} className="text-rh-red hover:underline">Stop Playback</button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Main Content ────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">

        {/* ─── Left: Bank Note + Action Buttons ──────────────────── */}
        <div className="flex-none lg:w-[420px] flex flex-col items-center justify-center p-6 lg:p-10 gap-6">
          <div className="relative">
            <TalkingBankNote
              isTalking={isSpeaking}
              className="w-48 h-48 lg:w-64 lg:h-64 drop-shadow-2xl"
            />
            {isSpeaking && (
              <div className="absolute -bottom-2 left-1/2 -translate-x-1/2 flex gap-1">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-rh-red"
                    style={{ animation: `pulse-red 1s ${i * 0.2}s infinite` }}
                  />
                ))}
              </div>
            )}
          </div>
          {lastAgentMessage && (
            <div className="max-w-xs text-center bg-rh-gray-90 border border-rh-gray-70 rounded-2xl px-4 py-3 text-sm text-rh-gray-20 animate-fade-in-up relative">
              <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 bg-rh-gray-90 border-l border-t border-rh-gray-70 rotate-45" />
              <span className="relative">{lastAgentMessage.content}</span>
            </div>
          )}
          <div className="text-xs text-rh-gray-50">
            {status === "recording" ? (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-rh-red animate-pulse-red" />
                Recording...
              </span>
            ) : (
              status
            )}
          </div>
          <div className="flex gap-4">
            <button
              className="rounded-xl px-8 py-4 text-lg font-bold transition-all disabled:opacity-30
                bg-rh-green text-white hover:bg-rh-green-dark
                shadow-lg hover:shadow-xl active:scale-95"
              style={{ minWidth: 120 }}
              onClick={() => {
                void ensureTtsContext();
                startRecording();
              }}
              disabled={!connected || status === "recording"}
            >
              TALK
            </button>
            <button
              className="rounded-xl px-8 py-4 text-lg font-bold transition-all disabled:opacity-30
                bg-rh-red text-white hover:bg-rh-red-dark
                shadow-lg hover:shadow-xl active:scale-95"
              style={{ minWidth: 120 }}
              onClick={stopAndSend}
              disabled={!connected || status !== "recording"}
            >
              SEND
            </button>
          </div>
          <div className="w-full max-w-xs flex gap-2">
            <input
              className="flex-1 rounded-lg bg-rh-gray-90 border border-rh-gray-70 px-3 py-2 text-sm text-white placeholder-rh-gray-50 focus:border-rh-red focus:ring-1 focus:ring-rh-red focus:outline-none"
              placeholder="Type a message..."
              value={textToSend}
              onChange={(e) => setTextToSend(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendText();
                }
              }}
            />
            <button
              className="rounded-lg bg-rh-red text-white px-4 py-2 text-sm font-semibold hover:bg-rh-red-dark disabled:opacity-40 transition-colors"
              onClick={sendText}
              disabled={!connected}
            >
              Send
            </button>
          </div>
          {error && (
            <div className="w-full max-w-xs rounded-lg border border-red-900 bg-rh-red-bg/60 px-3 py-2 text-xs text-red-200">
              {error}
            </div>
          )}
        </div>

        {/* ─── Center: Transcript + Conversation ──────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden border-l border-rh-gray-80">
          <div className="flex-none border-b border-rh-gray-80">
            <div className="px-6 py-3 border-b border-rh-gray-80 flex items-center justify-between">
              <h2 className="text-sm font-semibold" style={{ fontFamily: "'Red Hat Display', sans-serif" }}>
                Agent Transcript
              </h2>
              {serviceType && (
                <span className="text-xs px-2 py-0.5 rounded bg-rh-red/20 text-rh-red border border-rh-red/30">
                  {serviceType}
                </span>
              )}
            </div>
            <div className="px-6 py-3 max-h-32 overflow-y-auto rh-scroll">
              <p className="text-sm text-rh-gray-20 whitespace-pre-wrap">
                {transcript || "Waiting for speech..."}
              </p>
            </div>
          </div>
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-none px-6 py-3 border-b border-rh-gray-80">
              <h2 className="text-sm font-semibold" style={{ fontFamily: "'Red Hat Display', sans-serif" }}>
                Conversation History
              </h2>
            </div>
            <div className="flex-1 overflow-y-auto rh-scroll px-6 py-4 space-y-3">
              {messages.length ? (
                messages.filter((m) => m.role !== "interrupt").map((m, i) => {
                  const isHuman = m.role === "human";
                  const isRouting = m.content.startsWith("Routing to");
                  if (isRouting) {
                    return (
                      <div key={i} className="flex justify-center">
                        <span className="text-xs text-rh-gray-50 bg-rh-gray-90 px-3 py-1 rounded-full">
                          {m.content}
                        </span>
                      </div>
                    );
                  }
                  return (
                    <div key={i} className={`flex ${isHuman ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                          isHuman
                            ? "bg-rh-red/15 border border-rh-red/20 text-rh-gray-10"
                            : "bg-rh-gray-90 border border-rh-gray-70 text-rh-gray-20"
                        }`}
                      >
                        <div className="text-[10px] uppercase tracking-wider text-rh-gray-50 mb-1 font-semibold">
                          {m.role}
                        </div>
                        <div className="text-sm whitespace-pre-wrap">{m.content}</div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="flex-1 flex items-center justify-center text-rh-gray-50 text-sm">
                  Say something to start a conversation...
                </div>
              )}
              {waiting && (
                <div className="flex justify-start">
                  <div className="bg-rh-gray-90 border border-rh-gray-70 rounded-2xl px-5 py-3 flex items-center gap-2">
                    <svg className="w-4 h-4 animate-spin text-rh-red" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    <span className="text-sm text-rh-gray-40">Thinking...</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>
        </div>

        {/* ─── Right: Analysis Sidebar ─────────────────────────────── */}
        <div className="flex-none w-[280px] border-l border-rh-gray-80 overflow-y-auto rh-scroll p-5 space-y-6 hidden lg:block">
          {/* Guardrails */}
          <div>
            <h3 className="text-sm font-bold mb-3" style={{ fontFamily: "'Red Hat Display', sans-serif" }}>
              Guardrails
            </h3>
            <div className="space-y-2">
              <AnalysisCard
                label="Toxicity Guardrail"
                item={analysis?.guardrails.toxicity}
              />
              <AnalysisCard
                label="Banking Topic Guardrail"
                item={analysis?.guardrails.bank_topic}
              />
              <AnalysisCard
                label="Language Support"
                item={analysis?.guardrails.language}
              />
            </div>
          </div>

          {/* Input Analysis */}
          <div>
            <h3 className="text-sm font-bold mb-3" style={{ fontFamily: "'Red Hat Display', sans-serif" }}>
              Input Analysis
            </h3>
            <div className="space-y-2">
              <AnalysisCard
                label="KYC Detection"
                item={analysis?.input_analysis.kyc}
              />
              <AnalysisCard
                label="Sentiment Analysis"
                item={analysis?.input_analysis.sentiment}
              />
              <AnalysisCard
                label="Churn Prediction"
                item={analysis?.input_analysis.churn}
              />
            </div>
          </div>

          <button
            className="w-full rounded-lg border border-rh-gray-70 text-rh-gray-40 px-3 py-2 text-xs hover:text-white hover:border-rh-gray-50 transition-colors"
            onClick={() => setAnalysis(null)}
          >
            Clear
          </button>
        </div>
      </div>
      <div className="flex-none h-px bg-gradient-to-r from-rh-red via-rh-red/20 to-transparent" />
    </div>
  );
}

// ─── Analysis Card Component ──────────────────────────────────────────────────
function AnalysisCard({ label, item }: { label: string; item?: AnalysisItem }) {
  if (!item) {
    return (
      <div className="rounded-lg border border-rh-gray-70 bg-rh-gray-90 px-3 py-2.5 flex items-center gap-2">
        <span className="text-base">--</span>
        <span className="text-xs text-rh-gray-50">{label}: Waiting</span>
      </div>
    );
  }

  const statusConfig: Record<string, { icon: string; bg: string; border: string }> = {
    passed:   { icon: "\u2705", bg: "bg-green-950/50", border: "border-green-800/60" },
    detected: { icon: "\u2139\uFE0F", bg: "bg-blue-950/50", border: "border-blue-800/60" },
    none:     { icon: "\u2705", bg: "bg-green-950/50", border: "border-green-800/60" },
    positive: { icon: "\u2705", bg: "bg-green-950/50", border: "border-green-800/60" },
    low:      { icon: "\u2705", bg: "bg-green-950/50", border: "border-green-800/60" },
    neutral:  { icon: "\u26A0\uFE0F", bg: "bg-yellow-950/50", border: "border-yellow-800/60" },
    warning:  { icon: "\u26A0\uFE0F", bg: "bg-yellow-950/50", border: "border-yellow-800/60" },
    medium:   { icon: "\u26A0\uFE0F", bg: "bg-yellow-950/50", border: "border-yellow-800/60" },
    negative: { icon: "\u26A0\uFE0F", bg: "bg-yellow-950/50", border: "border-yellow-800/60" },
    failed:   { icon: "\uD83D\uDED1", bg: "bg-red-950/50", border: "border-red-800/60" },
    high:     { icon: "\uD83D\uDED1", bg: "bg-red-950/50", border: "border-red-800/60" },
  };

  const cfg = statusConfig[item.status] || statusConfig.neutral;

  return (
    <div className={`rounded-lg border ${cfg.border} ${cfg.bg} px-3 py-2.5 flex items-center gap-2 transition-all animate-fade-in-up`}>
      <span className="text-base flex-none">{cfg.icon}</span>
      <span className="text-xs text-rh-gray-20">
        {label}: <span className="font-semibold">{item.detail}</span>
      </span>
    </div>
  );
}
